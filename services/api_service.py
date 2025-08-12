import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
import time
import json
from config import Config

logger = logging.getLogger(__name__)

class APIService:
    def __init__(self):
        self.config = Config()
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'ETF-Analyzer/1.0'})
        self.cache = {}  # Prosty cache w pamięci
        self.cache_ttl = self.config.CACHE_TTL_SECONDS  # Z config
    
    def get_etf_data(self, ticker: str) -> Dict:
        """
        Pobiera kompletne dane ETF z różnych źródeł w kolejności priorytetu
        """
        try:
            # Sprawdzenie cache
            cache_key = f"etf_data_{ticker}"
            if cache_key in self.cache and time.time() - self.cache[cache_key]['timestamp'] < self.cache_ttl:
                logger.info(f"Using cached data for {ticker}")
                return self.cache[cache_key]['data']
            
            data = {}
            
            # 1. PRIORYTET: Financial Modeling Prep - główne źródło
            fmp_data = self._get_fmp_data(ticker)
            if fmp_data:
                data.update(fmp_data)
                logger.info(f"FMP data retrieved for {ticker}")
            
            # 2. BACKUP: EOD Historical Data - ceny historyczne
            if not data.get('current_price'):
                eodhd_data = self._get_eodhd_data(ticker)
                if eodhd_data:
                    data.update(eodhd_data)
                    logger.info(f"EODHD backup data retrieved for {ticker}")
            
            # 3. FALLBACK: Tiingo - ostatnia cena
            if not data.get('current_price'):
                tiingo_data = self._get_tiingo_data(ticker)
                if tiingo_data:
                    data.update(tiingo_data)
                    logger.info(f"Tiingo fallback data retrieved for {ticker}")
            
            # Sprawdzenie minimalnych wymaganych danych
            if not data.get('current_price'):
                logger.error(f"No price data available for {ticker} from any source")
                return None
            
            # Cache danych
            self.cache[cache_key] = {
                'data': data,
                'timestamp': time.time()
            }
            
            return data
            
        except Exception as e:
            logger.error(f"Error getting ETF data for {ticker}: {str(e)}")
            return None
    
    def _get_fmp_data(self, ticker: str) -> Optional[Dict]:
        """
        Pobiera dane z Financial Modeling Prep (PRIORYTET 1)
        """
        if not self.config.FMP_API_KEY:
            return None
            
        try:
            # 1. Profile - podstawowe dane
            profile_url = f"{self.config.FMP_BASE_URL}/profile/{ticker}"
            profile_params = {'apikey': self.config.FMP_API_KEY}
            
            profile_response = self._make_request_with_retry(profile_url, params=profile_params)
            if profile_response and profile_response.status_code == 200:
                profile_data = profile_response.json()
                if profile_data and len(profile_data) > 0:
                    profile = profile_data[0]
                    
                    fmp_data = {
                        'ticker': ticker,
                        'name': profile.get('companyName', ticker),
                        'current_price': float(profile.get('price', 0)),
                        'sector': profile.get('sector'),
                        'industry': profile.get('industry'),
                        'market_cap': profile.get('mktCap'),
                        'beta': profile.get('beta'),
                        'last_dividend': profile.get('lastDiv'),
                        'exchange': profile.get('exchange'),
                        'is_etf': profile.get('isEtf', False)
                    }
                    
                    # 2. Historia dywidend
                    dividend_url = f"{self.config.FMP_BASE_URL}/historical-price-full/stock_dividend/{ticker}"
                    dividend_response = self._make_request_with_retry(dividend_url, params=profile_params)
                    if dividend_response and dividend_response.status_code == 200:
                        dividend_data = dividend_response.json()
                        if 'historical' in dividend_data:
                            fmp_data['fmp_dividends'] = dividend_data['historical']
                            
                            # Obliczanie yield i częstotliwości
                            if fmp_data['current_price'] and fmp_data['last_dividend']:
                                fmp_data['current_yield'] = (fmp_data['last_dividend'] / fmp_data['current_price']) * 100
                                fmp_data['frequency'] = self._determine_frequency_from_dividends(dividend_data['historical'])
                    
                    # 3. Ceny historyczne (miesięczne)
                    price_url = f"{self.config.FMP_BASE_URL}/historical-price-full/{ticker}"
                    price_response = self._make_request_with_retry(price_url, params=profile_params)
                    if price_response and price_response.status_code == 200:
                        price_data = price_response.json()
                        if 'historical' in price_data:
                            fmp_data['fmp_prices'] = price_data['historical']
                    
                    return fmp_data
            
        except Exception as e:
            logger.error(f"FMP error for {ticker}: {str(e)}")
        
        return None
    
    def _get_eodhd_data(self, ticker: str) -> Optional[Dict]:
        """
        Pobiera dane z EOD Historical Data (BACKUP - ceny historyczne)
        """
        if not self.config.EODHD_API_KEY:
            return None
            
        try:
            # Miesięczne ceny (ostatnie 15 lat)
            price_url = f"{self.config.EODHD_BASE_URL}/eod/{ticker}"
            price_params = {
                'api_token': self.config.EODHD_API_KEY,
                'fmt': 'json',
                'period': 'm',
                'limit': 180  # 15 lat * 12 miesięcy
            }
            
            price_response = self._make_request_with_retry(price_url, params=price_params)
            if price_response and price_response.status_code == 200:
                price_data = price_response.json()
                if price_data and len(price_data) > 0:
                    # Najnowsza cena jako current_price
                    latest_price = price_data[0]
                    current_price = float(latest_price.get('close', 0))
                    
                    if current_price > 0:
                        return {
                            'eodhd_current_price': current_price,
                            'eodhd_prices': price_data,
                            'eodhd_latest_date': latest_price.get('date')
                        }
            
        except Exception as e:
            logger.error(f"EODHD error for {ticker}: {str(e)}")
        
        return None
    
    def _get_tiingo_data(self, ticker: str) -> Optional[Dict]:
        """
        Pobiera dane z Tiingo (FALLBACK - ostatnia cena)
        """
        if not self.config.TIINGO_API_KEY:
            return None
            
        try:
            headers = {'Authorization': f'Token {self.config.TIINGO_API_KEY}'}
            
            # Ostatnia cena
            price_url = f"{self.config.TIINGO_BASE_URL}/daily/{ticker}/prices"
            price_response = self._make_request_with_retry(price_url, headers=headers)
            
            if price_response and price_response.status_code == 200:
                price_data = price_response.json()
                if price_data and len(price_data) > 0:
                    latest_price = price_data[0]
                    current_price = float(latest_price.get('close', 0))
                    
                    if current_price > 0:
                        return {
                            'tiingo_current_price': current_price,
                            'tiingo_latest_date': latest_price.get('date')
                        }
            
        except Exception as e:
            logger.error(f"Tiingo error for {ticker}: {str(e)}")
        
        return None
    
    def _make_request_with_retry(self, url: str, params: Dict = None, headers: Dict = None, max_retries: int = None) -> Optional[requests.Response]:
        """
        Wykonuje request z retry logic i exponential backoff
        """
        if max_retries is None:
            max_retries = self.config.MAX_RETRIES
            
        for attempt in range(max_retries):
            try:
                if params:
                    response = self.session.get(url, params=params, timeout=10)
                elif headers:
                    response = self.session.get(url, headers=headers, timeout=10)
                else:
                    response = self.session.get(url, timeout=10)
                
                if response.status_code == 200:
                    return response
                elif response.status_code == 429:  # Rate limit
                    wait_time = (self.config.RETRY_DELAY_BASE ** attempt) * 2  # Exponential backoff
                    logger.warning(f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}")
                    time.sleep(wait_time)
                else:
                    logger.warning(f"HTTP {response.status_code} for {url}, attempt {attempt + 1}")
                    
            except Exception as e:
                logger.error(f"Request error for {url}: {str(e)}, attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(self.config.RETRY_DELAY_BASE ** attempt)  # Exponential backoff
        
        return None
    
    def _determine_frequency_from_dividends(self, dividends: List[Dict]) -> str:
        """
        Określa częstotliwość dywidend na podstawie analizy wzorca czasowego
        """
        if not dividends or len(dividends) < 2:
            return 'unknown'
        
        try:
            # Analiza ostatnich 12 miesięcy
            recent_dividends = dividends[:12]  # FMP zwraca od najnowszych
            
            if len(recent_dividends) < 2:
                return 'unknown'
            
            # Analiza wzorca czasowego - sprawdzamy odstępy między dywidendami
            dates = []
            for dividend in recent_dividends:
                if 'date' in dividend:
                    try:
                        dividend_date = datetime.strptime(dividend['date'], '%Y-%m-%d')
                        dates.append(dividend_date)
                    except (ValueError, TypeError):
                        continue
            
            if len(dates) < 2:
                return 'unknown'
            
            # Sortowanie dat od najstarszej do najnowszej
            dates.sort()
            
            # Obliczanie średnich odstępów między dywidendami
            intervals = []
            for i in range(1, len(dates)):
                interval = (dates[i] - dates[i-1]).days
                intervals.append(interval)
            
            if not intervals:
                return 'unknown'
            
            avg_interval = sum(intervals) / len(intervals)
            
            # Określanie częstotliwości na podstawie średniego odstępu
            if avg_interval <= 35:  # ~1 miesiąc
                return 'monthly'
            elif avg_interval <= 100:  # ~3 miesiące
                return 'quarterly'
            elif avg_interval <= 400:  # ~1 rok
                return 'annual'
            else:
                return 'unknown'
                
        except Exception as e:
            logger.warning(f"Error determining dividend frequency: {str(e)}")
            return 'unknown'
    
    def get_historical_prices(self, ticker: str, years: int = 15) -> List[Dict]:
        """
        Pobiera historyczne ceny ETF z FMP lub EODHD
        """
        try:
            # Próba z FMP
            if self.config.FMP_API_KEY:
                price_url = f"{self.config.FMP_BASE_URL}/historical-price-full/{ticker}"
                price_params = {'apikey': self.config.FMP_API_KEY}
                
                price_response = self._make_request_with_retry(price_url, params=price_params)
                if price_response and price_response.status_code == 200:
                    price_data = price_response.json()
                    if 'historical' in price_data:
                        return self._convert_fmp_prices_to_monthly(price_data['historical'], years)
            
            # Fallback do EODHD
            if self.config.EODHD_API_KEY:
                price_url = f"{self.config.EODHD_BASE_URL}/eod/{ticker}"
                price_params = {
                    'api_token': self.config.EODHD_API_KEY,
                    'fmt': 'json',
                    'period': 'm',
                    'limit': years * 12
                }
                
                price_response = self._make_request_with_retry(price_url, params=price_params)
                if price_response and price_response.status_code == 200:
                    price_data = price_response.json()
                    if price_data:
                        return self._convert_eodhd_prices_to_monthly(price_data)
            
        except Exception as e:
            logger.error(f"Error getting historical prices for {ticker}: {str(e)}")
        
        return []
    
    def _convert_fmp_prices_to_monthly(self, prices: List[Dict], years: int) -> List[Dict]:
        """
        Konwertuje ceny FMP na miesięczne
        """
        monthly_data = []
        cutoff_date = datetime.now() - timedelta(days=years*365)
        
        for price in prices:
            price_date = datetime.strptime(price['date'], '%Y-%m-%d')
            if price_date >= cutoff_date:
                monthly_data.append({
                    'date': price_date.date(),
                    'close_price': float(price['close']),
                    'open_price': float(price['open']),
                    'high_price': float(price['high']),
                    'low_price': float(price['low']),
                    'volume': int(price['volume'])
                })
        
        return monthly_data
    
    def _convert_eodhd_prices_to_monthly(self, prices: List[Dict]) -> List[Dict]:
        """
        Konwertuje ceny EODHD na miesięczne
        """
        monthly_data = []
        
        for price in prices:
            price_date = datetime.strptime(price['date'], '%Y-%m-%d')
            monthly_data.append({
                'date': price_date.date(),
                'close_price': float(price['close']),
                'open_price': float(price['open']),
                'high_price': float(price['high']),
                'low_price': float(price['low']),
                'volume': int(price['volume'])
            })
        
        return monthly_data
    
    def get_dividend_history(self, ticker: str, years: int = 15) -> List[Dict]:
        """
        Pobiera historię dywidend ETF z FMP
        """
        try:
            if not self.config.FMP_API_KEY:
                return []
            
            dividend_url = f"{self.config.FMP_BASE_URL}/historical-price-full/stock_dividend/{ticker}"
            dividend_params = {'apikey': self.config.FMP_API_KEY}
            
            dividend_response = self._make_request_with_retry(dividend_url, params=dividend_params)
            if dividend_response and dividend_response.status_code == 200:
                dividend_data = dividend_response.json()
                if 'historical' in dividend_data:
                    # Debug logging
                    total_dividends = len(dividend_data['historical'])
                    logger.info(f"FMP API returned {total_dividends} total dividends for {ticker}")
                    
                    cutoff_date = datetime.now() - timedelta(days=years*365)
                    logger.info(f"Filtering dividends from {cutoff_date.date()} onwards")
                    
                    dividend_list = []
                    filtered_count = 0
                    for dividend in dividend_data['historical']:
                        try:
                            dividend_date = datetime.strptime(dividend['date'], '%Y-%m-%d')
                            if dividend_date >= cutoff_date:
                                # FMP API zwraca 'dividend' a nie 'amount'
                                dividend_amount = dividend.get('dividend') or dividend.get('amount', 0)
                                if dividend_amount:
                                    dividend_list.append({
                                        'payment_date': dividend_date.date(),
                                        'amount': float(dividend_amount),
                                        'ex_date': None,  # FMP nie ma ex-date
                                        'record_date': dividend.get('recordDate'),
                                        'declaration_date': dividend.get('declarationDate')
                                    })
                                    filtered_count += 1
                        except (KeyError, ValueError) as e:
                            logger.warning(f"Error parsing dividend data for {ticker}: {str(e)}")
                            continue
                    
                    logger.info(f"After filtering: {filtered_count} dividends for {ticker} (from {total_dividends} total)")
                    return dividend_list
            
        except Exception as e:
            logger.error(f"Error getting dividend history for {ticker}: {str(e)}")
        
        return []
