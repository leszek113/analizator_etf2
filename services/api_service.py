import requests
import pandas as pd
import os
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
import logging
import time
import json
from config import Config
from models import db

logger = logging.getLogger(__name__)

class APIService:
    def __init__(self):
        self.config = Config()
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'ETF-Analyzer/1.0'})
        
        # Rate limiting - oszczędność tokenów API (ładowanie z bazy danych)
        # Opóźnione ładowanie - tylko gdy potrzebne
        self.api_calls = None
        
        self.cache = {}  # Prosty cache w pamięci
        self.cache_ttl = self.config.CACHE_TTL_SECONDS  # Z config

    def _load_api_limits_from_db(self) -> Dict:
        """
        Ładuje limity API z bazy danych lub tworzy domyślne jeśli nie istnieją
        """
        try:
            from models import APILimit, db
            
            api_limits = {}
            default_limits = {
                'fmp': {'count': 0, 'last_reset': datetime.now(), 'daily_limit': 500},
                'eodhd': {'count': 0, 'last_reset': datetime.now(), 'daily_limit': 100},
                'tiingo': {'count': 0, 'last_reset': datetime.now(), 'daily_limit': 50}
            }
            
            for api_type, default_info in default_limits.items():
                # Próba pobrania z bazy
                api_limit = APILimit.query.filter_by(api_type=api_type).first()
                
                if api_limit:
                    # Sprawdzenie czy trzeba zresetować licznik (nowy dzień)
                    now = datetime.now()
                    if (now - api_limit.last_reset).days >= 1:
                        api_limit.current_count = 0
                        api_limit.last_reset = now
                        db.session.commit()
                        logger.info(f"API limit reset for {api_type} - new day started")
                    
                    api_limits[api_type] = {
                        'count': api_limit.current_count,
                        'last_reset': api_limit.last_reset,
                        'daily_limit': api_limit.daily_limit
                    }
                else:
                    # Tworzenie nowego wpisu w bazie
                    new_limit = APILimit(
                        api_type=api_type,
                        current_count=default_info['count'],
                        daily_limit=default_info['daily_limit'],
                        last_reset=default_info['last_reset']
                    )
                    db.session.add(new_limit)
                    db.session.commit()
                    
                    api_limits[api_type] = default_info
                    logger.info(f"Created new API limit record for {api_type}")
            
            logger.info(f"Loaded API limits from database: {api_limits}")
            return api_limits
            
        except Exception as e:
            logger.error(f"Error loading API limits from database: {str(e)}")
            # Fallback do domyślnych wartości
            return {
                'fmp': {'count': 0, 'last_reset': datetime.now(), 'daily_limit': 500},
                'eodhd': {'count': 0, 'last_reset': datetime.now(), 'daily_limit': 100},
                'tiingo': {'count': 0, 'last_reset': datetime.now(), 'daily_limit': 50}
            }

    def _ensure_api_limits_loaded(self):
        """Zapewnia że limity API są załadowane"""
        if self.api_calls is None:
            self.api_calls = self._load_api_limits_from_db()

    def _check_rate_limit(self, api_type: str) -> bool:
        """
        Sprawdza czy nie przekroczyliśmy limitu API dla danego typu
        
        Args:
            api_type: Typ API ('fmp', 'eodhd', 'tiingo')
            
        Returns:
            True jeśli możemy wykonać zapytanie, False jeśli limit przekroczony
        """
        self._ensure_api_limits_loaded()
        
        if api_type not in self.api_calls:
            return True
        
        api_info = self.api_calls[api_type]
        now = datetime.now()
        
        # Reset licznika co 24 godziny
        if (now - api_info['last_reset']).days >= 1:
            api_info['count'] = 0
            api_info['last_reset'] = now
            api_info['minute_count'] = 0  # Reset minutowego licznika
            api_info['minute_reset'] = now  # Reset minutowego timera
            logger.info(f"API limit reset for {api_type} - new day started")
            
            # Reset w bazie danych
            try:
                from models import APILimit
                api_limit = APILimit.query.filter_by(api_type=api_type).first()
                if api_limit:
                    api_limit.current_count = 0
                    api_limit.last_reset = now
                    api_limit.updated_at = now
                    db.session.commit()
                    logger.info(f"Reset API limit in database for {api_type}")
            except Exception as e:
                logger.error(f"Error resetting API limit in database for {api_type}: {str(e)}")
        
        # Inicjalizacja minutowych liczników jeśli nie istnieją
        if 'minute_count' not in api_info:
            api_info['minute_count'] = 0
            api_info['minute_reset'] = now
        
        # Reset minutowego licznika co minutę
        if (now - api_info['minute_reset']).total_seconds() >= 60:
            api_info['minute_count'] = 0
            api_info['minute_reset'] = now
            logger.info(f"Minute rate limit reset for {api_type}")
        
        # Sprawdzanie minutowego limitu (tylko dla FMP)
        if api_type == 'fmp':
            minute_limit = 5  # FMP: 5 wywołań na minutę
            if api_info['minute_count'] >= minute_limit:
                seconds_until_reset = 60 - (now - api_info['minute_reset']).total_seconds()
                logger.warning(f"⚠️  MINUTE RATE LIMIT for FMP: {api_info['minute_count']}/{minute_limit} calls")
                logger.warning(f"⏳ Wait {seconds_until_reset:.0f} seconds for minute reset")
                return False
        
        # Sprawdzanie dziennego limitu
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
        Zwiększa licznik wywołań API dla danego typu
        
        Args:
            api_type: Typ API ('fmp', 'eodhd', 'tiingo')
        """
        self._ensure_api_limits_loaded()
        
        if api_type not in self.api_calls:
            return
        
        api_info = self.api_calls[api_type]
        api_info['count'] += 1
        
        # Aktualizacja minutowego licznika dla FMP
        if api_type == 'fmp':
            if 'minute_count' not in api_info:
                api_info['minute_count'] = 0
                api_info['minute_reset'] = datetime.now()
            api_info['minute_count'] += 1
            logger.info(f"FMP API call: {api_info['minute_count']}/5 per minute, {api_info['count']}/500 per day")
        
        # Aktualizacja w bazie danych
        try:
            from models import APILimit
            api_limit = APILimit.query.filter_by(api_type=api_type).first()
            if api_limit:
                api_limit.current_count = api_info['count']
                api_limit.updated_at = datetime.now()
                db.session.commit()
        except Exception as e:
            logger.error(f"Error updating API limit in database for {api_type}: {str(e)}")
        
        logger.info(f"API call incremented for {api_type}: {api_info['count']}")

    def get_api_status(self) -> Dict:
        """
        Zwraca aktualny status wszystkich tokenów API
        
        Returns:
            Dict z informacjami o statusie każdego API
        """
        self._ensure_api_limits_loaded()
        
        status = {}
        now = datetime.now()
        
        for api_type in ['fmp', 'eodhd', 'tiingo']:
            if api_type in self.api_calls:
                api_info = self.api_calls[api_type]
                now = datetime.now()
                
                # Obliczanie czasu do resetu
                next_reset = api_info['last_reset'] + timedelta(days=1)
                hours_until_reset = (next_reset - now).total_seconds() / 3600
                
                # Status minutowego limitu dla FMP
                minute_status = "OK"
                if api_type == 'fmp' and 'minute_count' in api_info:
                    minute_limit = 5
                    if api_info['minute_count'] >= minute_limit:
                        minute_status = "LIMIT REACHED"
                    elif api_info['minute_count'] >= minute_limit * 0.8:
                        minute_status = "WARNING"
                
                status[api_type] = {
                    'current_usage': api_info['count'],
                    'daily_limit': api_info['daily_limit'],
                    'hours_until_reset': hours_until_reset,
                    'last_reset': api_info['last_reset'].strftime('%Y-%m-%d %H:%M:%S'),
                    'next_reset': next_reset.strftime('%Y-%m-%d %H:%M:%S'),
                    'remaining_calls': api_info['daily_limit'] - api_info['count'],
                    'usage_percentage': round((api_info['count'] / api_info['daily_limit']) * 100, 1),
                    'limit_status': 'OK' if api_info['count'] < api_info['daily_limit'] else 'LIMIT REACHED',
                    'minute_status': minute_status if api_type == 'fmp' else 'N/A',
                    'minute_usage': f"{api_info.get('minute_count', 0)}/5" if api_type == 'fmp' else 'N/A'
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
            
            # 2. BACKUP: EOD Historical Data - ceny historyczne + dywidendy
            if not data.get('current_price'):
                eodhd_data = self._get_eodhd_data(ticker)
                if eodhd_data:
                    data.update(eodhd_data)
                    logger.info(f"EODHD backup data retrieved for {ticker}")
                    
                    # Dodanie cen historycznych do cache
                    if 'eodhd_prices' in eodhd_data:
                        data['eodhd_prices'] = eodhd_data['eodhd_prices']  # Zachowuję oryginalną nazwę
                        logger.info(f"Added EODHD prices to cache for {ticker}")
                    
                    # Dodanie dywidend do cache
                    if 'eodhd_dividends' in eodhd_data:
                        data['eodhd_dividends'] = eodhd_data['eodhd_dividends']  # Zachowuję oryginalną nazwę
                        logger.info(f"Added EODHD dividends to cache for {ticker}")
            
            # 3. FALLBACK: Tiingo - ostatnia cena
            if not data.get('current_price'):
                tiingo_data = self._get_tiingo_data(ticker)
                if tiingo_data:
                    data.update(tiingo_data)
                    logger.info(f"Tiingo fallback data retrieved for {ticker}")
            
            # Sprawdzenie minimalnych wymaganych danych - cena musi być dostępna
            current_price = data.get('current_price')
            if not current_price:
                # Sprawdź backup sources
                current_price = data.get('eodhd_current_price')
                if not current_price:
                    current_price = data.get('tiingo_current_price')
                
            if not current_price:
                logger.error(f"No price data available for {ticker} from any source")
                return None
            
            # Upewniam się, że current_price jest ustawione
            data['current_price'] = current_price
            
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
                    
                    # Logowanie wszystkich dostępnych pól z profilu FMP
                    logger.info(f"FMP profile data for {ticker}: {profile}")
                    
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
                        'is_etf': profile.get('isEtf', False),
                        'inception_date': profile.get('ipoDate')  # Data utworzenia ETF na rynku (IPO date)
                    }
                    
                    # Logowanie inception_date (IPO date)
                    logger.info(f"FMP inception_date for {ticker}: {profile.get('ipoDate')}")
                    
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
        Pobiera dane z EOD Historical Data (BACKUP - ceny historyczne + dywidendy)
        """
        if not self.config.EODHD_API_KEY:
            return None
            
        try:
            eodhd_data = {}
            
            # 1. Miesięczne ceny (ostatnie 15 lat)
            price_url = f"{self.config.EODHD_BASE_URL}/eod/{ticker}"
            price_params = {
                'api_token': self.config.EODHD_API_KEY,
                'fmt': 'json',
                'period': 'm',
                'limit': 180  # 15 lat * 12 miesięcy
            }
            
            price_response = self._make_request_with_retry(price_url, params=price_params)
            if price_response and price_response.status_code == 200:
                # Zwiększanie licznika API calls
                self._increment_api_call('eodhd')
                
                price_data = price_response.json()
                if price_data and len(price_data) > 0:
                    # Najnowsza cena jako current_price
                    latest_price = price_data[0]
                    current_price = float(latest_price.get('close', 0))
                    
                    if current_price > 0:
                        eodhd_data.update({
                            'eodhd_current_price': current_price,
                            'eodhd_prices': price_data,
                            'eodhd_latest_date': latest_price.get('date')
                        })
            
            # 2. Próba pobrania dywidend (jeśli endpoint istnieje)
            try:
                dividend_url = f"{self.config.EODHD_BASE_URL}/div/{ticker}"
                dividend_params = {
                    'api_token': self.config.EODHD_API_KEY,
                    'fmt': 'json',
                    'limit': 200  # Ostatnie 200 dywidend
                }
                
                dividend_response = self._make_request_with_retry(dividend_url, params=dividend_params)
                if dividend_response and dividend_response.status_code == 200:
                    dividend_data = dividend_response.json()
                    if dividend_data and len(dividend_data) > 0:
                        logger.info(f"EODHD returned {len(dividend_data)} dividends for {ticker}")
                        eodhd_data['eodhd_dividends'] = dividend_data
                    else:
                        logger.info(f"EODHD returned empty dividend data for {ticker}")
                else:
                    logger.info(f"EODHD dividend endpoint not available for {ticker} (HTTP {dividend_response.status_code if dividend_response else 'No response'})")
            except Exception as e:
                logger.info(f"EODHD dividend endpoint error for {ticker}: {str(e)}")
            
            return eodhd_data if eodhd_data else None
            
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
                    # Dodanie szczegółowego logowania dla debugowania
                    try:
                        response_text = response.text[:200]  # Pierwsze 200 znaków
                        logger.info(f"Response content: {response_text}")
                    except:
                        pass
                    
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
                    # Zwiększanie licznika API calls
                    self._increment_api_call('fmp')
                    
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
    
    def get_historical_weekly_prices(self, ticker: str, years: int = 15, normalize_splits: bool = True) -> List[Dict]:
        """
        Pobiera historyczne ceny tygodniowe ETF z FMP z opcjonalną normalizacją splitu
        
        Args:
            ticker: Symbol ETF
            years: Liczba lat historii
            normalize_splits: Czy normalizować split akcji
            
        Returns:
            Lista cen tygodniowych z ostatnich X lat
        """
        try:
            if not self.config.FMP_API_KEY:
                return []
            
            # Sprawdzanie rate limit
            if not self._check_rate_limit('fmp'):
                logger.warning(f"Rate limit reached for FMP, skipping {ticker}")
                return []
            
            # Pobieranie cen tygodniowych z FMP
            price_url = f"{self.config.FMP_BASE_URL}/historical-price-full/{ticker}?serietype=weekly"
            price_params = {'apikey': self.config.FMP_API_KEY}
            
            price_response = self._make_request_with_retry(price_url, params=price_params)
            if price_response and price_response.status_code == 200:
                # Zwiększanie licznika API calls
                self._increment_api_call('fmp')
                
                price_data = price_response.json()
                if 'historical' in price_data:
                    weekly_data = self._convert_fmp_prices_to_weekly(price_data['historical'], years)
                    
                    # Normalizacja splitu jeśli wymagana
                    if normalize_splits and weekly_data:
                        splits = self.get_stock_splits(ticker)
                        if splits:
                            logger.info(f"Found {len(splits)} splits for {ticker}, normalizing weekly prices")
                            weekly_data = self.normalize_prices_for_splits(weekly_data, splits)
                    
                    return weekly_data
                else:
                    logger.warning(f"No historical data in FMP response for {ticker}")
            else:
                logger.warning(f"FMP API request failed for {ticker}: {price_response.status_code if price_response else 'No response'}")
            
            # Fallback do EODHD (tylko jeśli FMP nie dało danych)
            if self.config.EODHD_API_KEY:
                price_url = f"{self.config.EODHD_BASE_URL}/eod/{ticker}"
                price_params = {
                    'api_token': self.config.EODHD_API_KEY,
                    'fmt': 'json',
                    'period': 'w',
                    'limit': years * 52  # 52 tygodnie na rok
                }
                
                price_response = self._make_request_with_retry(price_url, params=price_params)
                if price_response and price_response.status_code == 200:
                    price_data = price_response.json()
                    if price_data:
                        weekly_data = self._convert_eodhd_prices_to_weekly(price_data)
                        
                        # Normalizacja splitu jeśli wymagana
                        if normalize_splits and weekly_data:
                            splits = self.get_stock_splits(ticker)
                            if splits:
                                logger.info(f"Found {len(splits)} splits for {ticker}, normalizing weekly prices")
                                weekly_data = self.normalize_prices_for_splits(weekly_data, splits)
                        
                        return weekly_data
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting historical weekly prices for {ticker}: {str(e)}")
        
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
    
    def _convert_fmp_prices_to_weekly(self, prices: List[Dict], years: int) -> List[Dict]:
        """
        Konwertuje ceny FMP na tygodniowe
        """
        weekly_data = []
        cutoff_date = datetime.now() - timedelta(days=years*365)
        
        for price in prices:
            price_date = datetime.strptime(price['date'], '%Y-%m-%d')
            if price_date >= cutoff_date:
                weekly_data.append({
                    'date': price_date.date(),
                    'close': float(price['close']),
                    'open': float(price['open']),
                    'high': float(price['high']),
                    'low': float(price['low']),
                    'volume': int(price['volume'])
                })
        
        return weekly_data
    
    def _convert_eodhd_prices_to_weekly(self, prices: List[Dict]) -> List[Dict]:
        """
        Konwertuje ceny EODHD na tygodniowe
        """
        weekly_data = []
        
        for price in prices:
            price_date = datetime.strptime(price['date'], '%Y-%m-%d')
            weekly_data.append({
                'date': price_date.date(),
                'close': float(price['close']),
                'open': float(price['open']),
                'high': float(price['high']),
                'low': float(price['low']),
                'volume': int(price['volume'])
            })
        
        return weekly_data
    
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
                # Zwiększanie licznika API calls
                self._increment_api_call('fmp')
                
                dividend_data = dividend_response.json()
                if 'historical' in dividend_data:
                    # Dividend data processing
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

    def calculate_dividend_streak_growth(self, ticker: str, dividends_from_db: List = None) -> Dict:
        """
        Oblicza aktualny Dividend Streak Growth dla ETF
        
        Args:
            ticker: Ticker ETF
            dividends_from_db: Lista dywidend z bazy danych (opcjonalna)
        
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
            # Użyj danych z bazy jeśli podane, w przeciwnym razie pobierz z API
            if dividends_from_db:
                dividends = dividends_from_db
                logger.info(f"Using {len(dividends)} dividends from database for {ticker} DSG calculation")
            else:
                # Fallback do API (tylko gdy konieczne)
                logger.info(f"No database dividends provided for {ticker}, fetching from API")
                dividends = self.get_dividend_history(ticker, years=20)
            
            if not dividends or len(dividends) == 0:
                return {
                    'current_streak': 0,
                    'total_years': 0,
                    'streak_start_year': None,
                    'last_dividend_change': 'Brak dywidend',
                    'calculation_method': 'no dividends'
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
            
            # PRAWIDŁOWA LOGIKA: Sprawdzamy wszystkie lata wstecz aż do spadku
            # Nie kończymy na pierwszym spadku - szukamy najdłuższego streak
            current_streak = 0
            streak_start_year = None
            max_streak = 0
            max_streak_start_year = None
            
            # Sprawdzamy wszystkie lata wstecz
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
                    
                    # Aktualizuj maksymalny streak
                    if current_streak > max_streak:
                        max_streak = current_streak
                        max_streak_start_year = streak_start_year
                else:
                    # Dywidenda nie wzrosła - reset streak ale kontynuuj sprawdzanie
                    if current_streak > 0:
                        # Aktualizuj maksymalny streak przed resetem
                        if current_streak > max_streak:
                            max_streak = current_streak
                            max_streak_start_year = streak_start_year
                    
                    # Reset streak
                    current_streak = 0
                    streak_start_year = None
            
            # Użyj maksymalnego streak (nie tylko aktualnego)
            final_streak = max_streak
            final_streak_start_year = max_streak_start_year
            
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
                'current_streak': final_streak,
                'total_years': len(years),
                'streak_start_year': final_streak_start_year,
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
                # Zwiększanie licznika API calls
                self._increment_api_call('fmp')
                
                splits_data = splits_response.json()
                logger.info(f"Splits response for {ticker}: {splits_data}")
                if isinstance(splits_data, list):
                    return splits_data
                elif isinstance(splits_data, dict) and 'historical' in splits_data:
                    return splits_data['historical']
            
        except Exception as e:
            logger.error(f"Error getting stock splits for {ticker}: {str(e)}")
        
        # Fallback: split data z konfiguracji
        from config import Config
        config = Config()
        if ticker in config.KNOWN_SPLITS:
            logger.info(f"Using configured split data for {ticker}")
            return config.KNOWN_SPLITS[ticker]
        
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
    
    def get_current_price(self, ticker: str) -> Optional[float]:
        """
        Pobiera aktualną cenę ETF z dostępnych źródeł API
        
        Args:
            ticker: Ticker ETF
            
        Returns:
            Aktualna cena lub None jeśli nie udało się pobrać
        """
        try:
            # Próba pobrania z FMP (najlepsze źródło)
            if self._check_rate_limit('fmp'):
                try:
                    fmp_price = self._get_fmp_current_price(ticker)
                    if fmp_price:
                        self._increment_api_call('fmp')
                        logger.info(f"Got current price for {ticker} from FMP: ${fmp_price}")
                        return fmp_price
                except Exception as e:
                    logger.warning(f"FMP price fetch failed for {ticker}: {str(e)}")
            
            # Fallback do EODHD
            if self._check_rate_limit('eodhd'):
                try:
                    eodhd_price = self._get_eodhd_current_price(ticker)
                    if eodhd_price:
                        self._increment_api_call('eodhd')
                        logger.info(f"Got current price for {ticker} from EODHD: ${eodhd_price}")
                        return eodhd_price
                except Exception as e:
                    logger.warning(f"EODHD price fetch failed for {ticker}: {str(e)}")
            
            # Fallback do Tiingo
            if self._check_rate_limit('tiingo'):
                try:
                    tiingo_price = self._get_tiingo_current_price(ticker)
                    if tiingo_price:
                        self._increment_api_call('tiingo')
                        logger.info(f"Got current price for {ticker} from Tiingo: ${tiingo_price}")
                        return tiingo_price
                except Exception as e:
                    logger.warning(f"Tiingo price fetch failed for {ticker}: {str(e)}")
            
            logger.error(f"Failed to get current price for {ticker} from all sources")
            return None
            
        except Exception as e:
            logger.error(f"Error getting current price for {ticker}: {str(e)}")
            return None
    
    def _get_fmp_current_price(self, ticker: str) -> Optional[float]:
        """Pobiera aktualną cenę z FMP API"""
        try:
            url = f"{self.config.FMP_BASE_URL}/quote/{ticker}"
            params = {'apikey': self.config.FMP_API_KEY}
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data and len(data) > 0:
                return float(data[0].get('price', 0))
            
            return None
            
        except Exception as e:
            logger.warning(f"FMP current price fetch error for {ticker}: {str(e)}")
            return None
    
    def _get_eodhd_current_price(self, ticker: str) -> Optional[float]:
        """Pobiera aktualną cenę z EODHD API"""
        try:
            url = f"{self.config.EODHD_BASE_URL}/real-time/{ticker}"
            params = {'api_token': self.config.EODHD_API_KEY, 'fmt': 'json'}
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data:
                return float(data.get('close', 0))
            
            return None
            
        except Exception as e:
            logger.warning(f"EODHD current price fetch error for {ticker}: {str(e)}")
            return None
    
    def _get_tiingo_current_price(self, ticker: str) -> Optional[float]:
        """Pobiera aktualną cenę z Tiingo API"""
        try:
            url = f"{self.config.TIINGO_BASE_URL}/tiingo/daily/{ticker}/prices"
            params = {'token': self.config.TIINGO_API_KEY}
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data and len(data) > 0:
                return float(data[0].get('close', 0))
            
            return None
            
        except Exception as e:
            logger.warning(f"Tiingo current price fetch error for {ticker}: {str(e)}")
            return None

    def calculate_break_even_dividends(self, ticker: str, dividends_from_db: List = None, prices_from_db: List = None, target_percentage: float = 5.0) -> Dict:
        """
        Oblicza break-even time dla dywidend dla każdego miesiąca inwestycji
        
        Args:
            ticker: Symbol ETF
            dividends_from_db: Lista dywidend z bazy danych
            prices_from_db: Lista cen miesięcznych z bazy danych
            target_percentage: Docelowy procent ROI (domyślnie 5.0%)
            
        Returns:
            Słownik z danymi break-even dla każdego miesiąca
        """
        try:
            from models import db
            from services.database_service import DatabaseService
            
            db_service = DatabaseService()
            
            # Pobieranie danych jeśli nie podano
            if dividends_from_db is None:
                etf = db_service.get_etf_by_ticker(ticker)
                if not etf:
                    return {'error': f'ETF {ticker} not found'}
                dividends_from_db = db_service.get_etf_dividends(etf.id)
            
            if prices_from_db is None:
                etf = db_service.get_etf_by_ticker(ticker)
                if not etf:
                    return {'error': f'ETF {ticker} not found'}
                prices_from_db = db_service.get_monthly_prices(etf.id)
            
            # Pobieranie stawki podatku
            tax_rate = db_service.get_dividend_tax_rate()
            
            # Przygotowanie danych
            investment_amount = 1000  # $1000 miesięcznie
            target_return = investment_amount * (target_percentage / 100)  # Dynamiczny cel ROI
            
            # Grupowanie dywidend po miesiącach
            dividends_by_month = {}
            for dividend in dividends_from_db:
                month_key = f"{dividend.payment_date.year}-{dividend.payment_date.month:02d}"
                if month_key not in dividends_by_month:
                    dividends_by_month[month_key] = []
                dividends_by_month[month_key].append(dividend.normalized_amount or dividend.amount)
            
            # Grupowanie cen po miesiącach
            prices_by_month = {}
            for price in prices_from_db:
                month_key = f"{price.date.year}-{price.date.month:02d}"
                prices_by_month[month_key] = price.close_price
            
            # Obliczanie break-even time dla każdego miesiąca
            break_even_results = []
            
            for month_key in sorted(prices_by_month.keys()):
                if month_key not in prices_by_month:
                    continue
                
                price = prices_by_month[month_key]
                year, month = month_key.split('-')
                
                # Obliczanie liczby jednostek (2 miejsca po przecinku)
                units = round(investment_amount / price, 2)
                
                # Symulacja portfela - śledzenie dywidend netto
                cumulative_dividends = 0
                months_to_break_even = 0
                break_even_achieved = False
                
                # Sprawdzanie kolejnych miesięcy po inwestycji
                for future_month_key in sorted(dividends_by_month.keys()):
                    if future_month_key < month_key:
                        continue
                    
                    if future_month_key in dividends_by_month:
                        # Suma dywidend netto z tego miesiąca dla naszych jednostek
                        monthly_dividend = sum(dividends_by_month[future_month_key])
                        net_dividend = monthly_dividend * units * (1 - tax_rate / 100)
                        cumulative_dividends += net_dividend
                        
                        if cumulative_dividends >= target_return:
                            months_to_break_even = months_to_break_even
                            break_even_achieved = True
                            break
                    
                    months_to_break_even += 1
                
                # Jeśli nie osiągnięto break-even, ustawiamy None
                if not break_even_achieved:
                    months_to_break_even = None
                
                break_even_results.append({
                    'month': month_key,
                    'year': int(year),
                    'month_num': int(month),
                    'price': round(price, 4),
                    'units': units,
                    'months_to_break_even': months_to_break_even,
                    'cumulative_dividends': round(cumulative_dividends, 4)
                })
            
            return {
                'ticker': ticker.upper(),
                'investment_amount': investment_amount,
                'target_percentage': target_percentage,
                'target_return': target_return,
                'tax_rate': tax_rate,
                'data': break_even_results,
                'count': len(break_even_results)
            }
            
        except Exception as e:
            logger.error(f"Error calculating break-even dividends for {ticker}: {str(e)}")
            return {'error': str(e)}

    def calculate_macd(self, price_data, fast_period=8, slow_period=17, signal_period=9):
        """
        Oblicza MACD (Moving Average Convergence Divergence) dla danych cenowych
        
        Args:
            price_data (list): Lista słowników z kluczami 'date' i 'close'
            fast_period (int): Okres szybkiej EMA (domyślnie 8)
            slow_period (int): Okres wolnej EMA (domyślnie 17)
            signal_period (int): Okres linii sygnałowej (domyślnie 9)
            
        Returns:
            list: Lista słowników z danymi MACD
        """
        try:
            if not price_data or len(price_data) < slow_period:
                logger.warning(f"Za mało danych dla MACD: {len(price_data) if price_data else 0} < {slow_period}")
                return []
            
            # Konwersja danych na pandas DataFrame
            df = pd.DataFrame(price_data)
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df = df.dropna()
            
            if len(df) < slow_period:
                logger.warning(f"Po konwersji za mało danych dla MACD: {len(df)} < {slow_period}")
                return []
            
            logger.info(f"Rozpoczynam obliczanie MACD: {len(df)} cen, fast={fast_period}, slow={slow_period}, signal={signal_period}")
            
            # Obliczanie EMA
            fast_ema = df['close'].ewm(span=fast_period, adjust=False).mean()
            slow_ema = df['close'].ewm(span=slow_period, adjust=False).mean()
            
            # MACD Line = Fast EMA - Slow EMA
            macd_line = fast_ema - slow_ema
            
            # Signal Line = EMA z MACD Line
            signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
            
            # Histogram = MACD Line - Signal Line
            histogram = macd_line - signal_line
            
            # Przygotowanie danych wynikowych
            macd_data = []
            for i in range(len(df)):
                if i >= slow_period - 1:  # Zaczynamy od momentu gdy mamy wszystkie EMA
                    macd_data.append({
                        'date': df.iloc[i]['date'],
                        'macd_line': float(macd_line.iloc[i]),
                        'signal_line': float(signal_line.iloc[i]),
                        'histogram': float(histogram.iloc[i]),
                        'current_price': float(df.iloc[i]['close'])
                    })
            
            logger.info(f"MACD obliczony: {len(macd_data)} punktów z {len(df)} cen")
            if macd_data:
                logger.info(f"Przykład MACD data[0]: {macd_data[0]}")
                logger.info(f"Pola w MACD data[0]: {list(macd_data[0].keys())}")
            
            return macd_data
            
        except Exception as e:
            logger.error(f"Błąd podczas obliczania MACD: {str(e)}")
            return []

    def calculate_stochastic_oscillator(self, prices: List[Dict], lookback_period: int = 36, 
                                      smoothing_factor: int = 12, sma_period: int = 12) -> List[Dict]:
        """
        Oblicza Stochastic Oscillator dla cen tygodniowych
        
        Args:
            prices: Lista cen z polami 'date' i 'close' (znormalizowane)
            lookback_period: Okres lookback dla %K (domyślnie 36)
            smoothing_factor: Współczynnik wygładzania dla %K (domyślnie 12)
            sma_period: Okres SMA dla %D (domyślnie 12)
            
        Returns:
            Lista z datami i wartościami %K, %D
        """
        try:
            logger.info(f"Rozpoczynam obliczanie Stochastic Oscillator: {len(prices)} cen, lookback={lookback_period}, smoothing={smoothing_factor}, sma={sma_period}")
            
            # Sprawdź format danych
            if prices and len(prices) > 0:
                sample_price = prices[0]
                logger.info(f"Przykładowa cena: {sample_price}")
                logger.info(f"Typ date: {type(sample_price['date'])}, Typ close: {type(sample_price['close'])}")
            
            # Sample data for testing
            if len(prices) >= 3:
                sample_prices = [
                    {'date': '2020-01-01', 'close': 10.0},
                    {'date': '2020-01-08', 'close': 12.0},
                    {'date': '2020-01-15', 'close': 11.0}
                ]
                logger.info(f"Using sample data for testing: {sample_prices}")
            
            if len(prices) < lookback_period:
                logger.warning(f"Za mało danych dla Stochastic Oscillator: {len(prices)} < {lookback_period}")
                return []
            
            # Sortowanie cen od najstarszych do najnowszych
            sorted_prices = sorted(prices, key=lambda x: datetime.strptime(x['date'], '%Y-%m-%d').date() if isinstance(x['date'], str) else x['date'])
            logger.info(f"Ceny posortowane: {len(sorted_prices)} punktów od {sorted_prices[0]['date']} do {sorted_prices[-1]['date']}")
            
            stochastic_data = []
            
            # Obliczanie %K dla każdego punktu
            for i in range(lookback_period - 1, len(sorted_prices)):
                current_price = sorted_prices[i]['close']
                
                # Znajdź najwyższą i najniższą cenę w okresie lookback
                lookback_prices = sorted_prices[i - lookback_period + 1:i + 1]
                high_prices = [p['close'] for p in lookback_prices]
                low_prices = [p['close'] for p in lookback_prices]
                
                highest_high = max(high_prices)
                lowest_low = min(low_prices)
                
                # Oblicz %K
                if highest_high == lowest_low:
                    k_percent = 50.0  # Jeśli wszystkie ceny są takie same
                else:
                    k_percent = ((current_price - lowest_low) / (highest_high - lowest_low)) * 100
                
                stochastic_data.append({
                    'date': sorted_prices[i]['date'],
                    'k_percent': k_percent,
                    'highest_high': highest_high,
                    'lowest_low': lowest_low,
                    'current_price': current_price
                })
            
            logger.info(f"Obliczono %K dla {len(stochastic_data)} punktów")
            
            # Wygładzanie %K (SMA)
            if len(stochastic_data) >= smoothing_factor:
                for i in range(smoothing_factor - 1, len(stochastic_data)):
                    k_values = [stochastic_data[j]['k_percent'] for j in range(i - smoothing_factor + 1, i + 1)]
                    smoothed_k = sum(k_values) / len(k_values)
                    stochastic_data[i]['k_percent_smoothed'] = smoothed_k
                
                # Dodaj brakujące klucze dla pierwszych punktów
                for i in range(smoothing_factor - 1):
                    stochastic_data[i]['k_percent_smoothed'] = stochastic_data[i]['k_percent']
                
                logger.info(f"Wygładzono %K dla {len(stochastic_data)} punktów")
            else:
                logger.warning(f"Za mało danych dla wygładzania %K: {len(stochastic_data)} < {smoothing_factor}")
                # Jeśli nie ma wystarczająco danych, użyj surowych wartości %K
                for data in stochastic_data:
                    data['k_percent_smoothed'] = data['k_percent']
            
            # Obliczanie %D (SMA z wygładzonego %K)
            if len(stochastic_data) >= sma_period:
                for i in range(sma_period - 1, len(stochastic_data)):
                    smoothed_k_values = [stochastic_data[j]['k_percent_smoothed'] for j in range(i - sma_period + 1, i + 1)]
                    d_percent = sum(smoothed_k_values) / len(smoothed_k_values)
                    stochastic_data[i]['d_percent'] = d_percent
                
                # Dodaj brakujące klucze dla pierwszych punktów
                for i in range(sma_period - 1):
                    stochastic_data[i]['d_percent'] = stochastic_data[i]['k_percent_smoothed']
                
                logger.info(f"Obliczono %D dla {len(stochastic_data)} punktów")
            else:
                logger.warning(f"Za mało danych dla obliczenia %D: {len(stochastic_data)} < {sma_period}")
                # Jeśli nie ma wystarczająco danych, użyj wygładzonych wartości %K jako %D
                for data in stochastic_data:
                    data['d_percent'] = data['k_percent_smoothed']
            
            # Teraz wszystkie punkty mają wymagane klucze
            final_data = stochastic_data
            
            logger.info(f"Stochastic Oscillator obliczony: {len(final_data)} punktów z {len(prices)} cen")
            
            # Data validation
            if stochastic_data:
                logger.info(f"Sample stochastic_data[0]: {stochastic_data[0]}")
                logger.info(f"Fields in stochastic_data[0]: {list(stochastic_data[0].keys())}")
            
            # Data verification
            if final_data:
                logger.info(f"PIERWSZY PUNKT: {final_data[0]}")
                logger.info(f"OSTATNI PUNKT: {final_data[-1]}")
            else:
                logger.warning("BRAK DANYCH W FINAL_DATA!")
                logger.warning(f"stochastic_data ma {len(stochastic_data)} punktów")
                if stochastic_data:
                    logger.warning(f"Przykład stochastic_data[0]: {stochastic_data[0]}")
            
            return final_data
            
        except Exception as e:
            logger.error(f"Error calculating Stochastic Oscillator: {str(e)}")
            return []

    def get_historical_daily_prices(self, ticker: str, days: int = 365, normalize_splits: bool = True) -> List[Dict]:
        """
        Pobiera historyczne ceny dzienne ETF z EODHD lub FMP z opcjonalną normalizacją splitu
        
        Args:
            ticker: Symbol ETF
            days: Liczba dni historii (domyślnie 365)
            normalize_splits: Czy normalizować split akcji
            
        Returns:
            Lista cen dziennych z ostatnich X dni
        """
        try:
            daily_data = []
            
            # PRIORYTET 1: EODHD (lepszy dla cen dziennych)
            if self.config.EODHD_API_KEY:
                # Sprawdzanie rate limit
                if not self._check_rate_limit('eodhd'):
                    logger.warning(f"Rate limit reached for EODHD, trying FMP for {ticker}")
                else:
                    price_url = f"{self.config.EODHD_BASE_URL}/eod/{ticker}"
                    price_params = {
                        'api_token': self.config.EODHD_API_KEY,
                        'fmt': 'json',
                        'period': 'd',  # dzienne
                        'limit': days
                    }
                    
                    price_response = self._make_request_with_retry(price_url, params=price_params)
                    if price_response and price_response.status_code == 200:
                        # Zwiększanie licznika API calls
                        self._increment_api_call('eodhd')
                        
                        price_data = price_response.json()
                        if price_data:
                            daily_data = self._convert_eodhd_prices_to_daily(price_data)
                            
                            # Normalizacja splitu jeśli wymagana
                            if normalize_splits and daily_data:
                                splits = self.get_stock_splits(ticker)
                                if splits:
                                    logger.info(f"Found {len(splits)} splits for {ticker}, normalizing daily prices")
                                    daily_data = self.normalize_prices_for_splits(daily_data, splits)
                            
                            logger.info(f"Successfully got {len(daily_data)} daily prices from EODHD for {ticker}")
                            return daily_data
            
            # PRIORYTET 2: FMP (fallback)
            if not daily_data and self.config.FMP_API_KEY:
                # Sprawdzanie rate limit
                if not self._check_rate_limit('fmp'):
                    logger.warning(f"Rate limit reached for FMP, skipping {ticker}")
                    return []
                
                price_url = f"{self.config.FMP_BASE_URL}/historical-price-full/{ticker}"
                price_params = {'apikey': self.config.FMP_API_KEY}
                
                price_response = self._make_request_with_retry(price_url, params=price_params)
                if price_response and price_response.status_code == 200:
                    # Zwiększanie licznika API calls
                    self._increment_api_call('fmp')
                    
                    price_data = price_response.json()
                    if 'historical' in price_data:
                        daily_data = self._convert_fmp_prices_to_daily(price_data['historical'], days)
                        
                        # Normalizacja splitu jeśli wymagana
                        if normalize_splits and daily_data:
                            splits = self.get_stock_splits(ticker)
                            if splits:
                                logger.info(f"Found {len(splits)} splits for {ticker}, normalizing daily prices")
                                daily_data = self.normalize_prices_for_splits(daily_data, splits)
                        
                        logger.info(f"Successfully got {len(daily_data)} daily prices from FMP for {ticker}")
                        return daily_data
            
            # PRIORYTET 3: Tiingo (ostateczny fallback)
            if not daily_data and self.config.TIINGO_API_KEY:
                # Sprawdzanie rate limit
                if not self._check_rate_limit('tiingo'):
                    logger.warning(f"Rate limit reached for Tiingo, skipping {ticker}")
                    return []
                
                # Tiingo ma ograniczone dane historyczne, ale może dać ostatnie ceny
                price_url = f"{self.config.TIINGO_BASE_URL}/{ticker}/prices"
                price_params = {
                    'token': self.config.TIINGO_API_KEY,
                    'startDate': (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'),
                    'endDate': datetime.now().strftime('%Y-%m-%d')
                }
                
                price_response = self._make_request_with_retry(price_url, params=price_params)
                if price_response and price_response.status_code == 200:
                    # Zwiększanie licznika API calls
                    self._increment_api_call('tiingo')
                    
                    price_data = price_response.json()
                    if price_data:
                        daily_data = self._convert_tiingo_prices_to_daily(price_data)
                        logger.info(f"Successfully got {len(daily_data)} daily prices from Tiingo for {ticker}")
                        return daily_data
            
            if not daily_data:
                logger.warning(f"Could not get daily prices for {ticker} from any source")
            
            return daily_data
            
        except Exception as e:
            logger.error(f"Error getting historical daily prices for {ticker}: {str(e)}")
        
        return []
    
    def _convert_fmp_prices_to_daily(self, prices: List[Dict], days: int) -> List[Dict]:
        """
        Konwertuje ceny FMP na dzienne
        """
        daily_data = []
        cutoff_date = datetime.now() - timedelta(days=days)
        
        for price in prices:
            price_date = datetime.strptime(price['date'], '%Y-%m-%d')
            if price_date >= cutoff_date:
                daily_data.append({
                    'date': price_date.date(),
                    'close': float(price['close']),
                    'open': float(price['open']),
                    'high': float(price['high']),
                    'low': float(price['low']),
                    'volume': int(price['volume'])
                })
        
        return daily_data
    
    def _convert_eodhd_prices_to_daily(self, prices: List[Dict]) -> List[Dict]:
        """
        Konwertuje ceny EODHD na dzienne
        """
        daily_data = []
        
        for price in prices:
            price_date = datetime.strptime(price['date'], '%Y-%m-%d')
            daily_data.append({
                'date': price_date.date(),
                'close': float(price['close']),
                'open': float(price['open']),
                'high': float(price['high']),
                'low': float(price['low']),
                'volume': int(price['volume'])
            })
        
        return daily_data
    
    def _convert_tiingo_prices_to_daily(self, prices: List[Dict]) -> List[Dict]:
        """
        Konwertuje ceny Tiingo na dzienne
        """
        daily_data = []
        
        for price in prices:
            try:
                price_date = datetime.strptime(price['date'], '%Y-%m-%d')
                daily_data.append({
                    'date': price_date.date(),
                    'close': float(price['close']),
                    'open': float(price.get('open', price['close'])),
                    'high': float(price.get('high', price['close'])),
                    'low': float(price.get('low', price['close'])),
                    'volume': int(price.get('volume', 0))
                })
            except (KeyError, ValueError) as e:
                logger.warning(f"Error parsing Tiingo price data: {str(e)}")
                continue
        
        return daily_data
    
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
