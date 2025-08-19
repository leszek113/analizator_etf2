import requests
import pandas as pd
import os
from datetime import datetime, timedelta, date
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
        
        # Rate limiting - oszczędność tokenów API
        self.api_calls = {
            'fmp': {'count': 0, 'last_reset': datetime.now(), 'daily_limit': 500},  # FMP free plan
            'eodhd': {'count': 0, 'last_reset': datetime.now(), 'daily_limit': 100},  # EODHD free plan
            'tiingo': {'count': 0, 'last_reset': datetime.now(), 'daily_limit': 50}   # Tiingo free plan
        }
        self.cache = {}  # Prosty cache w pamięci
        self.cache_ttl = self.config.CACHE_TTL_SECONDS  # Z config

    def _check_rate_limit(self, api_type: str) -> bool:
        """
        Sprawdza czy nie przekroczyliśmy limitu API dla danego typu
        
        Args:
            api_type: Typ API ('fmp', 'eodhd', 'tiingo')
            
        Returns:
            True jeśli możemy wykonać zapytanie, False jeśli limit przekroczony
        """
        if api_type not in self.api_calls:
            return True
        
        api_info = self.api_calls[api_type]
        now = datetime.now()
        
        # Reset licznika co 24 godziny
        if (now - api_info['last_reset']).days >= 1:
            api_info['count'] = 0
            api_info['last_reset'] = now
            logger.info(f"API limit reset for {api_type} - new day started")
        
        # Sprawdzanie limitu
        if api_info['count'] >= api_info['daily_limit']:
            # Obliczanie czasu do resetu
            next_reset = api_info['last_reset'] + timedelta(days=1)
            hours_until_reset = (next_reset - now).total_seconds() / 3600
            
            logger.error(f"🚨 DAILY API LIMIT REACHED for {api_type.upper()}: {api_info['count']}/{api_info['daily_limit']}")
            logger.error(f"⏰ Next reset in {hours_until_reset:.1f} hours (at {next_reset.strftime('%Y-%m-%d %H:%M:%S')})")
            logger.error(f"💡 Recommendation: Wait until tomorrow or upgrade API plan")
            
            # Dodatkowe powiadomienie o statusie
            self._log_api_limit_status(api_type, api_info['count'], api_info['daily_limit'], next_reset)
            
            return False
        
        # Ostrzeżenie przy 80% limitu
        warning_threshold = int(api_info['daily_limit'] * 0.8)
        if api_info['count'] >= warning_threshold and api_info['count'] < api_info['daily_limit']:
            remaining_calls = api_info['daily_limit'] - api_info['count']
            logger.warning(f"⚠️  API limit warning for {api_type}: {api_info['count']}/{api_info['daily_limit']} ({remaining_calls} calls remaining)")
        
        return True

    def _log_api_limit_status(self, api_type: str, current_count: int, daily_limit: int, next_reset: datetime) -> None:
        """
        Loguje szczegółowy status wyczerpania tokenów API
        """
        now = datetime.now()
        hours_until_reset = (next_reset - now).total_seconds() / 3600
        
        status_message = f"""
🚨 API TOKEN LIMIT EXHAUSTED - {api_type.upper()}
📊 Current Usage: {current_count}/{daily_limit} calls
⏰ Next Reset: {next_reset.strftime('%Y-%m-%d %H:%M:%S')}
⏳ Time Until Reset: {hours_until_reset:.1f} hours
💡 Action Required: Wait until tomorrow or upgrade API plan
🔗 API Provider: {self._get_api_provider_info(api_type)}
        """
        
        logger.error(status_message.strip())
        
        # Zapisanie do pliku logów dla łatwiejszego dostępu
        self._save_api_limit_log(api_type, current_count, daily_limit, next_reset)

    def _get_api_provider_info(self, api_type: str) -> str:
        """
        Zwraca informacje o dostawcy API
        """
        providers = {
            'fmp': 'Financial Modeling Prep (FMP) - https://financialmodelingprep.com/',
            'eodhd': 'EOD Historical Data - https://eodhistoricaldata.com/',
            'tiingo': 'Tiingo - https://api.tiingo.com/'
        }
        return providers.get(api_type, 'Unknown')

    def _save_api_limit_log(self, api_type: str, current_count: int, daily_limit: int, next_reset: datetime) -> None:
        """
        Zapisuje log wyczerpania tokenów do pliku
        """
        try:
            log_dir = 'logs'
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            log_file = os.path.join(log_dir, 'api_limits.log')
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {api_type.upper()} LIMIT EXHAUSTED\n")
                f.write(f"Usage: {current_count}/{daily_limit}\n")
                f.write(f"Next Reset: {next_reset.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Hours Until Reset: {(next_reset - datetime.now()).total_seconds() / 3600:.1f}\n")
                f.write("-" * 50 + "\n")
                
        except Exception as e:
            logger.error(f"Error saving API limit log: {str(e)}")

    def _increment_api_call(self, api_type: str) -> None:
        """
        Zwiększa licznik wywołań API
        """
        if api_type in self.api_calls:
            self.api_calls[api_type]['count'] += 1
            logger.debug(f"API call to {api_type}: {self.api_calls[api_type]['count']}/{self.api_calls[api_type]['daily_limit']}")

    def get_api_status(self) -> Dict:
        """
        Zwraca aktualny status wszystkich tokenów API
        
        Returns:
            Dict z informacjami o statusie każdego API
        """
        status = {}
        now = datetime.now()
        
        for api_type, api_info in self.api_calls.items():
            # Obliczanie czasu do resetu
            next_reset = api_info['last_reset'] + timedelta(days=1)
            hours_until_reset = (next_reset - now).total_seconds() / 3600
            
            # Status limitu
            limit_status = 'OK'
            if api_info['count'] >= api_info['daily_limit']:
                limit_status = 'EXHAUSTED'
            elif api_info['count'] >= int(api_info['daily_limit'] * 0.8):
                limit_status = 'WARNING'
            
            status[api_type] = {
                'current_usage': api_info['count'],
                'daily_limit': api_info['daily_limit'],
                'remaining_calls': max(0, api_info['daily_limit'] - api_info['count']),
                'limit_status': limit_status,
                'last_reset': api_info['last_reset'].strftime('%Y-%m-%d %H:%M:%S'),
                'next_reset': next_reset.strftime('%Y-%m-%d %H:%M:%S'),
                'hours_until_reset': round(hours_until_reset, 1),
                'usage_percentage': round((api_info['count'] / api_info['daily_limit']) * 100, 1)
            }
        
        return status

    def check_api_health(self) -> Dict:
        """
        Sprawdza zdrowie wszystkich API i zwraca rekomendacje
        
        Returns:
            Dict z rekomendacjami i statusem
        """
        status = self.get_api_status()
        recommendations = []
        critical_apis = []
        
        for api_type, api_status in status.items():
            if api_status['limit_status'] == 'EXHAUSTED':
                critical_apis.append(api_type)
                recommendations.append(f"🚨 {api_type.upper()}: Limit wyczerpany. Czekaj {(api_status['hours_until_reset'])}h do resetu.")
            elif api_status['limit_status'] == 'WARNING':
                recommendations.append(f"⚠️  {api_type.upper()}: {api_status['remaining_calls']} wywołań pozostało. Rozważ oszczędzanie.")
        
        if not critical_apis:
            recommendations.append("✅ Wszystkie API działają normalnie")
        
        return {
            'status': status,
            'recommendations': recommendations,
            'critical_apis': critical_apis,
            'can_continue': len(critical_apis) == 0
        }
    
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
            
            # Zwiększanie licznika API calls
            if 'fmp' in data:
                self._increment_api_call('fmp')
            if 'eodhd' in data:
                self._increment_api_call('eodhd')
            if 'tiingo' in data:
                self._increment_api_call('tiingo')
            
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
        
        # Sprawdzanie rate limit
        if not self._check_rate_limit('fmp'):
            logger.warning(f"Rate limit reached for FMP, skipping {ticker}")
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
    
    def get_historical_prices(self, ticker: str, years: int = 15, normalize_splits: bool = True) -> List[Dict]:
        """
        Pobiera historyczne ceny ETF z FMP lub EODHD z opcjonalną normalizacją splitu
        
        Args:
            ticker: Symbol ETF
            years: Liczba lat historii
            normalize_splits: Czy normalizować split akcji
        """
        try:
            monthly_data = []
            
            # Próba z FMP
            if self.config.FMP_API_KEY:
                price_url = f"{self.config.FMP_BASE_URL}/historical-price-full/{ticker}"
                price_params = {'apikey': self.config.FMP_API_KEY}
                
                price_response = self._make_request_with_retry(price_url, params=price_params)
                if price_response and price_response.status_code == 200:
                    price_data = price_response.json()
                    if 'historical' in price_data:
                        monthly_data = self._convert_fmp_prices_to_monthly(price_data['historical'], years)
                        if monthly_data:
                            pass  # Mamy dane z FMP
                        else:
                            monthly_data = []
            
            # Fallback do EODHD (tylko jeśli FMP nie dało danych)
            if not monthly_data and self.config.EODHD_API_KEY:
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
                        monthly_data = self._convert_eodhd_prices_to_monthly(price_data)
            
            # Normalizacja splitu jeśli wymagana
            if normalize_splits and monthly_data:
                splits = self.get_stock_splits(ticker)
                if splits:
                    logger.info(f"Found {len(splits)} splits for {ticker}, normalizing prices")
                    monthly_data = self.normalize_prices_for_splits(monthly_data, splits)
            
            return monthly_data
            
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
                    'close': float(price['close']),  # Zmienione na 'close' dla kompatybilności
                    'open': float(price['open']),    # Zmienione na 'open' dla kompatybilności
                    'high': float(price['high']),    # Zmienione na 'high' dla kompatybilności
                    'low': float(price['low']),      # Zmienione na 'low' dla kompatybilności
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
                'close': float(price['close']),  # Zmienione na 'close' dla kompatybilności
                'open': float(price['open']),    # Zmienione na 'open' dla kompatybilności
                'high': float(price['high']),    # Zmienione na 'high' dla kompatybilności
                'low': float(price['low']),      # Zmienione na 'low' dla kompatybilności
                'volume': int(price['volume'])
            })
        
        return monthly_data
    
    def get_dividend_history(self, ticker: str, years: int = 15, normalize_splits: bool = True, since_date: date = None) -> List[Dict]:
        """
        Pobiera historię dywidend ETF z FMP z opcjonalną normalizacją splitu
        
        Args:
            ticker: Symbol ETF
            years: Liczba lat historii
            normalize_splits: Czy normalizować split akcji
            since_date: Pobierz dywidendy tylko od tej daty (oszczędność tokenów)
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
                    
                    # Określanie daty od której pobieramy dywidendy
                    if since_date:
                        cutoff_date = since_date
                        logger.info(f"Filtering dividends from {cutoff_date} onwards (since_date)")
                    else:
                        cutoff_date = datetime.now() - timedelta(days=years*365)
                        logger.info(f"Filtering dividends from {cutoff_date.date()} onwards (years={years})")
                    
                    dividend_list = []
                    filtered_count = 0
                    for dividend in dividend_data['historical']:
                        try:
                            dividend_date = datetime.strptime(dividend['date'], '%Y-%m-%d')
                            # Upewniam się, że obie daty są tego samego typu
                            dividend_date_only = dividend_date.date() if hasattr(dividend_date, 'date') else dividend_date
                            cutoff_date_only = cutoff_date.date() if hasattr(cutoff_date, 'date') else cutoff_date
                            
                            if dividend_date_only >= cutoff_date_only:
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
                    
                    # Normalizacja splitu jeśli wymagana
                    if normalize_splits and dividend_list:
                        splits = self.get_stock_splits(ticker)
                        if splits:
                            logger.info(f"Found {len(splits)} splits for {ticker}, normalizing dividends")
                            logger.info(f"Split details: {splits}")
                            dividend_list = self.normalize_dividends_for_splits(dividend_list, splits)
                        else:
                            logger.info(f"No splits found for {ticker}")
                    else:
                        logger.info(f"Split normalization {'disabled' if not normalize_splits else 'skipped'} for {ticker}")
                    
                    return dividend_list
            
        except Exception as e:
            logger.error(f"Error getting dividend history for {ticker}: {str(e)}")
        
        return []

    def calculate_dividend_streak_growth(self, ticker: str) -> Dict:
        """
        Oblicza aktualny Dividend Streak Growth dla ETF
        
        Returns:
            Dict z informacjami o DSG:
            {
                'current_streak': int,      # Aktualny streak
                'total_years': int,         # Łączna liczba lat z danymi
                'streak_start_year': int,   # Rok rozpoczęcia aktualnego streak
                'last_dividend_change': str,  # Ostatnia zmiana dywidendy
                'calculation_method': str    # Metoda obliczania
            }
        """
        try:
            # Pobieranie historii dywidend
            dividends = self.get_dividend_history(ticker, years=20)  # Bierzemy więcej lat dla lepszej analizy
            
            if not dividends:
                return {
                    'current_streak': 0,
                    'total_years': 0,
                    'streak_start_year': None,
                    'last_dividend_change': 'N/A',
                    'calculation_method': 'year-over-year average'
                }
            
            # Grupowanie dywidend według roku i obliczanie średniej rocznej
            yearly_dividends = {}
            for dividend in dividends:
                year = dividend['payment_date'].year
                if year not in yearly_dividends:
                    yearly_dividends[year] = []
                yearly_dividends[year].append(dividend['amount'])
            
            # Obliczanie średniej rocznej dla każdego roku
            yearly_averages = {}
            for year, amounts in yearly_dividends.items():
                yearly_averages[year] = sum(amounts) / len(amounts)
            
            # Sortowanie lat rosnąco
            years = sorted(yearly_averages.keys())
            
            if len(years) < 2:
                return {
                    'current_streak': 0,
                    'total_years': len(years),
                    'streak_start_year': None,
                    'last_dividend_change': 'N/A',
                    'calculation_method': 'year-over-year average'
                }
            
            # PRAWIDŁOWA LOGIKA: Start od ostatniego zakończonego roku
            # Sprawdzamy rok po roku wstecz aż do spadku
            current_streak = 0
            streak_start_year = None
            
            # Start: ostatni zakończony rok (np. 2024)
            for i in range(len(years) - 1, 0, -1):
                current_year = years[i]      # np. 2024
                previous_year = years[i - 1] # np. 2023
                
                current_avg = yearly_averages[current_year]    # np. 1.7283
                previous_avg = yearly_averages[previous_year]  # np. 1.7663
                
                if current_avg > previous_avg:
                    # Dywidenda wzrosła rok do roku
                    if current_streak == 0:
                        streak_start_year = current_year
                    current_streak += 1
                else:
                    # Dywidenda nie wzrosła - streak się kończy
                    break
            
            # Określenie ostatniej zmiany dywidendy
            last_change = "N/A"
            if len(years) >= 2:
                last_year = years[-1]
                second_last_year = years[-2]
                if yearly_averages[last_year] > yearly_averages[second_last_year]:
                    last_change = f"Wzrost: {yearly_averages[second_last_year]:.4f} → {yearly_averages[last_year]:.4f}"
                elif yearly_averages[last_year] < yearly_averages[second_last_year]:
                    last_change = f"Spadek: {yearly_averages[second_last_year]:.4f} → {yearly_averages[last_year]:.4f}"
                else:
                    last_change = f"Bez zmian: {yearly_averages[last_year]:.4f}"
            
            return {
                'current_streak': current_streak,
                'total_years': len(years),
                'streak_start_year': streak_start_year,
                'last_dividend_change': last_change,
                'calculation_method': 'year-over-year average'
            }
            
        except Exception as e:
            logger.error(f"Error calculating DSG for {ticker}: {str(e)}")
            return {
                'current_streak': 0,
                'total_years': 0,
                'streak_start_year': None,
                'last_dividend_change': 'N/A',
                'calculation_method': 'error'
            }

    def get_stock_splits(self, ticker: str) -> List[Dict]:
        """
        Pobiera informacje o splitach akcji z FMP API
        
        Returns:
            Lista splitów z datą i stosunkiem
        """
        try:
            if not self.config.FMP_API_KEY:
                return []
            
            splits_url = f"{self.config.FMP_BASE_URL}/stock-split-calendar/{ticker}"
            splits_params = {'apikey': self.config.FMP_API_KEY}
            
            logger.info(f"Fetching splits for {ticker} from: {splits_url}")
            splits_response = self._make_request_with_retry(splits_url, params=splits_params)
            if splits_response and splits_response.status_code == 200:
                splits_data = splits_response.json()
                logger.info(f"Splits response for {ticker}: {splits_data}")
                if isinstance(splits_data, list):
                    return splits_data
                elif isinstance(splits_data, dict) and 'historical' in splits_data:
                    return splits_data['historical']
            
        except Exception as e:
            logger.error(f"Error getting stock splits for {ticker}: {str(e)}")
        
        # Fallback: hardcoded split data dla znanych ETF
        if ticker == 'SCHD':
            logger.info(f"Using hardcoded split data for {ticker}")
            return [{
                'date': '2024-10-11',
                'ratio': 3.0,
                'description': '3:1 Stock Split'
            }]
        
        return []

    def calculate_cumulative_split_ratio(self, splits: List[Dict], target_date: date) -> float:
        """
        Oblicza kumulacyjny współczynnik splitu dla danej daty
        
        Args:
            splits: Lista splitów posortowana od najstarszego do najnowszego
            target_date: Data dla której obliczamy ratio
            
        Returns:
            Kumulacyjny współczynnik splitu
        """
        if not splits:
            return 1.0
        
        cumulative_ratio = 1.0
        
        for split in splits:
            split_date = datetime.strptime(split.get('date', ''), '%Y-%m-%d').date()
            if target_date < split_date:
                # Dywidenda/cena była przed splitem - normalizujemy
                cumulative_ratio *= float(split.get('ratio', 1.0))
        
        return cumulative_ratio

    def normalize_dividends_for_splits(self, dividends: List[Dict], splits: List[Dict]) -> List[Dict]:
        """
        Normalizuje dywidendy uwzględniając split akcji
        
        Args:
            dividends: Lista dywidend
            splits: Lista splitów
            
        Returns:
            Lista znormalizowanych dywidend z oryginalnymi i znormalizowanymi kwotami
        """
        if not splits:
            # Brak splitów - wszystkie kwoty są takie same
            for dividend in dividends:
                dividend['original_amount'] = dividend['amount']
                dividend['normalized_amount'] = dividend['amount']
                dividend['split_ratio_applied'] = 1.0
            return dividends
        
        # Sortowanie splitów od najstarszego do najnowszego
        sorted_splits = sorted(splits, key=lambda x: x.get('date', ''))
        
        normalized_dividends = []
        
        for dividend in dividends:
            dividend_date = dividend['payment_date']
            if isinstance(dividend_date, str):
                dividend_date = datetime.strptime(dividend_date, '%Y-%m-%d').date()
            
            # Obliczanie kumulacyjnego współczynnika splitu
            split_ratio = self.calculate_cumulative_split_ratio(sorted_splits, dividend_date)
            
            # Tworzenie kopii dywidendy z obiema kwotami
            normalized_dividend = dividend.copy()
            original_amount = dividend['amount']
            normalized_dividend['original_amount'] = original_amount
            normalized_dividend['normalized_amount'] = original_amount / split_ratio
            normalized_dividend['split_ratio_applied'] = split_ratio
            
            if split_ratio > 1.0:
                logger.info(f"Normalized dividend: {original_amount} -> {normalized_dividend['normalized_amount']} (split ratio: {split_ratio})")
            
            normalized_dividends.append(normalized_dividend)
        
        return normalized_dividends

    def normalize_prices_for_splits(self, prices: List[Dict], splits: List[Dict]) -> List[Dict]:
        """
        Normalizuje ceny historyczne uwzględniając split akcji
        
        Args:
            prices: Lista cen
            splits: Lista splitów
            
        Returns:
            Lista znormalizowanych cen z oryginalnymi i znormalizowanymi wartościami
        """
        if not splits:
            # Brak splitów - wszystkie ceny są takie same
            for price in prices:
                price['original_close'] = price['close']
                price['normalized_close'] = price['close']
                price['split_ratio_applied'] = 1.0
            return prices
        
        # Sortowanie splitów od najstarszego do najnowszego
        sorted_splits = sorted(splits, key=lambda x: x.get('date', ''))
        
        normalized_prices = []
        
        for price in prices:
            price_date = price['date']
            if isinstance(price_date, str):
                price_date = datetime.strptime(price_date, '%Y-%m-%d').date()
            
            # Obliczanie kumulacyjnego współczynnika splitu
            split_ratio = self.calculate_cumulative_split_ratio(sorted_splits, price_date)
            
            # Tworzenie kopii ceny z obiema wartościami
            normalized_price = price.copy()
            original_close = price['close']
            normalized_price['original_close'] = original_close
            normalized_price['normalized_close'] = original_close / split_ratio
            normalized_price['split_ratio_applied'] = split_ratio
            
            if split_ratio > 1.0:
                logger.info(f"Normalized price: {original_close} -> {normalized_price['normalized_close']} (split ratio: {split_ratio})")
            
            normalized_prices.append(normalized_price)
        
        return normalized_prices
