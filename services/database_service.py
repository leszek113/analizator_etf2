from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Optional
from sqlalchemy.exc import IntegrityError
import logging
from models import db, ETF, ETFPrice, ETFWeeklyPrice, ETFDailyPrice, ETFDividend, ETFSplit, SystemLog, DividendTaxRate
from services.api_service import APIService
import re

logger = logging.getLogger(__name__)

class DatabaseService:
    def __init__(self, api_service: APIService = None):
        self.api_service = api_service or APIService()
    
    def _validate_ticker(self, ticker: str) -> bool:
        """
        Waliduje format ticker
        
        Args:
            ticker: Ticker do walidacji
            
        Returns:
            True jeśli ticker jest poprawny, False w przeciwnym razie
        """
        if not ticker or not isinstance(ticker, str):
            return False
        
        ticker = ticker.upper().strip()
        if not ticker or len(ticker) > 20:
            return False
        
        # Sprawdź czy ticker zawiera tylko dozwolone znaki
        if not re.match(r'^[A-Z0-9]+$', ticker):
            return False
        
        return True
    
    def add_etf(self, ticker: str) -> Optional[ETF]:
        """
        Dodaje nowy ETF do bazy danych wraz z historią
        """
        try:
            # Walidacja inputu
            if not self._validate_ticker(ticker):
                logger.error(f"Invalid ticker format: {ticker}")
                self._log_action('ERROR', f"Invalid ticker format: {ticker}", 'ERROR')
                return None
            
            ticker = ticker.upper().strip()
            
            # Sprawdzenie czy ETF już istnieje
            existing_etf = ETF.query.filter_by(ticker=ticker).first()
            if existing_etf:
                logger.info(f"ETF {ticker} already exists in database")
                return existing_etf
            
            # Pobieranie danych z API (FMP jako główne źródło)
            etf_data = self.api_service.get_etf_data(ticker)
            if not etf_data:
                logger.error(f"Could not fetch data for ETF {ticker}")
                self._log_action('ERROR', f"Failed to fetch data for ETF {ticker}", 'ERROR')
                return None
            
            # Sprawdzenie czy mamy minimalne wymagane dane - cena musi być dostępna
            current_price = etf_data.get('current_price')
            if not current_price:
                # Sprawdź backup sources
                current_price = etf_data.get('eodhd_current_price')
                if not current_price:
                    current_price = etf_data.get('tiingo_current_price')
                
            if not current_price:
                logger.error(f"No price data available for ETF {ticker} from any source")
                self._log_action('ERROR', f"No price data for ETF {ticker}", 'ERROR')
                return None
            
            # Używamy najlepszych dostępnych danych z FMP
            name = etf_data.get('name', ticker)
            current_yield = etf_data.get('current_yield')
            frequency = etf_data.get('frequency', 'unknown')
            
            # Konwersja inception_date z string na date
            inception_date = None
            if etf_data.get('inception_date'):
                try:
                    inception_date = datetime.strptime(etf_data['inception_date'], '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    logger.warning(f"Invalid inception_date format for {ticker}: {etf_data.get('inception_date')}")
            
            # Tworzenie nowego ETF
            new_etf = ETF(
                ticker=ticker.upper(),
                name=name,
                current_price=current_price,
                current_yield=current_yield,
                frequency=frequency,
                inception_date=inception_date,
                last_updated=datetime.now(timezone.utc)
            )
            
            db.session.add(new_etf)
            db.session.flush()  # Aby uzyskać ID
            
            # Dodawanie historii cen
            self._add_historical_prices(new_etf.id, ticker)
            
            # Dodawanie historii dywidend
            self._add_historical_dividends(new_etf.id, ticker)
            
            db.session.commit()
            
            # Logowanie
            self._log_action('ETF_ADDED', f"Added ETF {ticker} with {name} from FMP")
            
            logger.info(f"Successfully added ETF {ticker} to database")
            return new_etf
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error adding ETF {ticker}: {str(e)}")
            self._log_action('ERROR', f"Failed to add ETF {ticker}: {str(e)}", 'ERROR')
            return None
    
    def update_etf_data(self, ticker: str, force_update: bool = False) -> bool:
        """
        Aktualizuje dane istniejącego ETF
        
        Args:
            ticker: Ticker ETF
            force_update: Jeśli True, wymusza pełną aktualizację (15 lat historii)
        """
        try:
            # Sprawdzanie statusu tokenów API przed aktualizacją
            api_health = self._check_api_health_before_update(ticker)
            if not api_health['can_continue']:
                logger.warning(f"API health check failed for {ticker}: {api_health['recommendations']}")
                # Kontynuuj z cache jeśli API niedostępne
                return self._update_from_cache_only(ticker)
            
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                logger.warning(f"ETF {ticker} not found in database")
                return False
            
            # Pobieranie TYLKO podstawowych informacji o ETF (oszczędzamy tokeny API)
            # Ceny będą pobrane przez _check_new_prices
            etf_data = {}
            
            # Aktualizacja tylko jeśli force_update=True
            if force_update:
                try:
                    # Pobieranie tylko podstawowych informacji (bez cen)
                    basic_info = self.api_service.get_etf_basic_info(ticker)
                    if basic_info:
                        etf_data.update(basic_info)
                        logger.info(f"Got basic info for {ticker}: {basic_info}")
                except Exception as e:
                    logger.warning(f"Could not fetch basic info for {ticker}: {str(e)}")
                    # Kontynuuj bez podstawowych informacji
            
            # Aktualizacja danych (bez ceny - będzie pobrana przez _check_new_prices)
            etf.name = etf_data.get('name', etf.name)
            etf.current_yield = etf_data.get('current_yield', etf.current_yield)
            etf.frequency = etf_data.get('frequency', etf.frequency)
            
            # Aktualizacja inception_date jeśli dostępne
            if etf_data.get('inception_date') and not etf.inception_date:
                try:
                    inception_date = datetime.strptime(etf_data['inception_date'], '%Y-%m-%d').date()
                    etf.inception_date = inception_date
                    logger.info(f"Updated inception_date for {ticker}: {inception_date}")
                except (ValueError, TypeError):
                    logger.warning(f"Invalid inception_date format for {ticker}: {etf_data.get('inception_date')}")
            
            etf.last_updated = datetime.now(timezone.utc)
            
            # Sprawdzanie nowych dywidend
            new_dividends = self._check_new_dividends(etf.id, ticker)
            
            # Sprawdzanie nowych cen
            logger.info(f"Calling _check_new_prices for {ticker} with force_update={force_update}")
            logger.info(f"Type of force_update: {type(force_update)}, Value: {force_update}")
            logger.info(f"About to call _check_new_prices with etf.id={etf.id}, ticker={ticker}, force_update={force_update}")
            new_prices = self._check_new_prices(etf.id, ticker, force_update)
            logger.info(f"_check_new_prices returned: {new_prices}")
            
            # Jeśli force_update, pobierz pełną historię (15 lat)
            if force_update:
                logger.info(f"Force update requested for {ticker}, fetching full 15-year history")
                self._fetch_all_historical_dividends(etf.id, ticker, force_update=True)
                self._fetch_historical_monthly_prices(etf.id, ticker, force_update=True)
            
            # Zarządzanie splitami
            split_updated = self._manage_splits(etf.id, ticker)
            
            db.session.commit()
            
            if new_dividends or new_prices or split_updated or force_update:
                self._log_action('ETF_UPDATED', f"Updated ETF {ticker} with new data from FMP")
                logger.info(f"Successfully updated ETF {ticker} with new data")
            else:
                logger.info(f"ETF {ticker} data is up to date")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating ETF {ticker}: {str(e)}")
            self._log_action('ERROR', f"Failed to update ETF {ticker}: {str(e)}", 'ERROR')
            return False
    
    def get_all_etfs(self) -> List[ETF]:
        """
        Pobiera wszystkie ETF z bazy danych
        """
        try:
            return ETF.query.order_by(ETF.ticker).all()
        except Exception as e:
            logger.error(f"Error fetching ETFs: {str(e)}")
            return []
    
    def get_etf_by_ticker(self, ticker: str) -> Optional[ETF]:
        """
        Pobiera ETF po tickerze
        """
        try:
            return ETF.query.filter_by(ticker=ticker.upper()).first()
        except Exception as e:
            logger.error(f"Error fetching ETF {ticker}: {str(e)}")
            return None
    
    def delete_etf(self, ticker: str) -> bool:
        """
        Usuwa ETF wraz z wszystkimi powiązanymi danymi
        """
        try:
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                logger.warning(f"ETF {ticker} not found in database")
                return False
            
            # Pobieranie liczby rekordów do usunięcia
            price_count = ETFPrice.query.filter_by(etf_id=etf.id).count()
            dividend_count = ETFDividend.query.filter_by(etf_id=etf.id).count()
            
            # Usuwanie ETF (cascade usunie wszystkie powiązane dane)
            db.session.delete(etf)
            db.session.commit()
            
            # Logowanie akcji
            self._log_action('ETF_DELETED', 
                           f"Deleted ETF {ticker} with {price_count} prices and {dividend_count} dividends")
            
            logger.info(f"Successfully deleted ETF {ticker} with {price_count} prices and {dividend_count} dividends")
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting ETF {ticker}: {str(e)}")
            self._log_action('ERROR', f"Failed to delete ETF {ticker}: {str(e)}", 'ERROR')
            return False
    
    def get_etf_prices(self, etf_id: int, limit: int = None) -> List[ETFPrice]:
        """
        Pobiera historię cen ETF
        """
        try:
            query = ETFPrice.query.filter_by(etf_id=etf_id).order_by(ETFPrice.date.desc())
            if limit:
                query = query.limit(limit)
            return query.all()
        except Exception as e:
            logger.error(f"Error fetching prices for ETF {etf_id}: {str(e)}")
            return []
    
    def get_etf_dividends(self, etf_id: int, limit: int = None) -> List[ETFDividend]:
        """
        Pobiera historię dywidend ETF
        """
        try:
            query = ETFDividend.query.filter_by(etf_id=etf_id).order_by(ETFDividend.payment_date.desc())
            if limit:
                query = query.limit(limit)
            return query.all()
        except Exception as e:
            logger.error(f"Error fetching dividends for ETF {etf_id}: {str(e)}")
            return []
    
    def get_monthly_prices(self, etf_id: int) -> List[ETFPrice]:
        """Pobiera ceny miesięczne ETF z bazy danych - jedna cena na miesiąc, kończy się na ostatnio zakończonym miesiącu"""
        try:
            # Pobieranie cen miesięcznych, grupowane po roku i miesiącu
            # Używamy raw SQL dla lepszej kontroli nad grupowaniem
            # Wykres kończy się na ostatnio zakończonym miesiącu, nie na bieżącym
            from sqlalchemy import text
            from datetime import datetime, date
            
            # Obliczanie ostatniego miesiąca z danymi
            today = date.today()
            # Sprawdzamy czy mamy dane z bieżącego miesiąca
            current_month_start = date(today.year, today.month, 1)
            
            # Sprawdź czy są ceny z bieżącego miesiąca
            current_month_prices = ETFPrice.query.filter(
                ETFPrice.etf_id == etf_id,
                ETFPrice.date >= current_month_start
            ).first()
            
            if current_month_prices:
                # Mamy ceny z bieżącego miesiąca - używamy dzisiejszej daty
                last_completed_month = today
            else:
                # Brak cen z bieżącego miesiąca - używamy poprzedniego miesiąca
                if today.month == 1:
                    last_completed_month = date(today.year - 1, 12, 1)
                else:
                    last_completed_month = date(today.year, today.month - 1, 1)
            
            query = text("""
                SELECT 
                    id, etf_id, date, close_price, normalized_close_price, split_ratio_applied
                FROM etf_prices 
                WHERE etf_id = :etf_id 
                AND date <= :last_completed_month
                AND date IN (
                    SELECT MAX(date) 
                    FROM etf_prices 
                    WHERE etf_id = :etf_id 
                    AND date <= :last_completed_month
                    GROUP BY strftime('%Y-%m', date)
                )
                ORDER BY date ASC
            """)
            
            result = db.session.execute(query, {
                'etf_id': etf_id, 
                'last_completed_month': last_completed_month.strftime('%Y-%m-%d')
            })
            prices = []
            
            for row in result:
                price = ETFPrice()
                price.id = row.id
                price.etf_id = row.etf_id
                # Konwersja stringa daty na datetime.date
                if isinstance(row.date, str):
                    price.date = datetime.strptime(row.date, '%Y-%m-%d').date()
                else:
                    price.date = row.date
                price.close_price = row.close_price
                price.normalized_close_price = row.normalized_close_price
                price.split_ratio_applied = row.split_ratio_applied
                prices.append(price)
            
            logger.info(f"Retrieved {len(prices)} monthly prices (one per month, ending at {last_completed_month.strftime('%Y-%m')}) for ETF ID {etf_id}")
            return prices
            
        except Exception as e:
            logger.error(f"Error getting monthly prices for ETF ID {etf_id}: {str(e)}")
            return []

    def get_weekly_prices(self, etf_id: int) -> List[ETFWeeklyPrice]:
        """Pobiera ceny tygodniowe ETF z bazy danych - jedna cena na tydzień, kończy się na ostatnio zakończonym tygodniu"""
        try:
            # Pobieranie cen tygodniowych, grupowane po roku i tygodniu
            # Używamy raw SQL dla lepszej kontroli nad grupowaniem
            # Wykres kończy się na ostatnio zakończonym tygodniu, nie na bieżącym
            from sqlalchemy import text
            from datetime import datetime, date
            
            # Obliczanie ostatniego tygodnia z danymi
            today = date.today()
            # Sprawdzamy czy mamy dane z bieżącego tygodnia
            current_week_start = today - timedelta(days=today.weekday())  # Poniedziałek tego tygodnia
            
            # Sprawdź czy są ceny z bieżącego tygodnia
            current_week_prices = ETFWeeklyPrice.query.filter(
                ETFWeeklyPrice.etf_id == etf_id,
                ETFWeeklyPrice.date >= current_week_start
            ).first()
            
            if current_week_prices:
                # Mamy ceny z bieżącego tygodnia - używamy dzisiejszej daty
                last_completed_week = today
            else:
                # Brak cen z bieżącego tygodnia - używamy poprzedniego tygodnia
                last_completed_week = current_week_start - timedelta(days=1)  # Niedziela poprzedniego tygodnia
            
            query = text("""
                SELECT 
                    id, etf_id, date, close_price, normalized_close_price, split_ratio_applied, year, week_of_year
                FROM etf_weekly_prices 
                WHERE etf_id = :etf_id 
                AND date <= :last_completed_week
                AND date IN (
                    SELECT MAX(date) 
                    FROM etf_weekly_prices 
                    WHERE etf_id = :etf_id 
                    AND date <= :last_completed_week
                    GROUP BY year, week_of_year
                )
                ORDER BY date ASC
            """)
            
            result = db.session.execute(query, {
                'etf_id': etf_id, 
                'last_completed_week': last_completed_week.strftime('%Y-%m-%d')
            })
            prices = []
            
            for row in result:
                price = ETFWeeklyPrice()
                price.id = row.id
                price.etf_id = row.etf_id
                # Konwersja stringa daty na datetime.date
                if isinstance(row.date, str):
                    price.date = datetime.strptime(row.date, '%Y-%m-%d').date()
                else:
                    price.date = row.date
                price.close_price = row.close_price
                price.normalized_close_price = row.normalized_close_price
                price.split_ratio_applied = row.split_ratio_applied
                price.year = row.year
                price.week_of_year = row.week_of_year
                prices.append(price)
            
            logger.info(f"Retrieved {len(prices)} weekly prices (one per week, ending at {last_completed_week.strftime('%Y-%m-%d')}) for ETF ID {etf_id}")
            return prices
            
        except Exception as e:
            logger.error(f"Error getting weekly prices for ETF ID {etf_id}: {str(e)}")
            return []

    def _add_historical_prices(self, etf_id: int, ticker: str) -> None:
        """
        Dodaje historyczne ceny ETF - używa danych z cache jeśli dostępne
        """
        try:
            # Próba użycia danych z cache (jeśli były pobrane przez get_etf_data)
            cached_data = self.api_service.cache.get(f"etf_data_{ticker}")
            prices_data = []
            
            # Cache validation
            logger.info(f"Cache check for {ticker}: {list(self.api_service.cache.keys()) if self.api_service.cache else 'Empty cache'}")
            if cached_data:
                logger.info(f"Cache data keys for {ticker}: {list(cached_data['data'].keys())}")
            
            if cached_data and 'fmp_prices' in cached_data['data']:
                # Użyj danych z cache
                logger.info(f"Using cached price data for {ticker}")
                raw_prices = cached_data['data']['fmp_prices']
                prices_data = self._convert_fmp_prices_to_monthly(raw_prices, years=15)
            else:
                # Fallback do API
                logger.info(f"No cached price data for {ticker}, fetching from API")
                prices_data = self.api_service.get_historical_prices(ticker, normalize_splits=True)
            
            if not prices_data:
                logger.warning(f"No price data available for {ticker}")
                return
            
            for price_data in prices_data:
                price = ETFPrice(
                    etf_id=etf_id,
                    date=price_data['date'],
                    close_price=price_data['close'],
                    normalized_close_price=price_data.get('normalized_close', price_data['close']),
                    split_ratio_applied=price_data.get('split_ratio_applied', 1.0)
                )
                db.session.add(price)
            
            logger.info(f"Added {len(prices_data)} historical prices for ETF {ticker}")
            
            # Dodawanie cen tygodniowych
            weekly_prices_data = self.api_service.get_historical_weekly_prices(ticker, normalize_splits=True)
            if weekly_prices_data:
                for price_data in weekly_prices_data:
                    price = ETFWeeklyPrice(
                        etf_id=etf_id,
                        date=price_data['date'],
                        close_price=price_data.get('original_close', price_data['close']),  # Oryginalna cena
                        normalized_close_price=price_data['close'],  # Znormalizowana cena (już jest w 'close')
                        split_ratio_applied=price_data.get('split_ratio_applied', 1.0),
                        year=price_data['date'].year,
                        week_of_year=price_data['date'].isocalendar()[1]
                    )
                    db.session.add(price)
                
                logger.info(f"Added {len(weekly_prices_data)} historical weekly prices for ETF {ticker}")
            
            # Dodawanie cen dziennych (ostatnie 365 dni)
            daily_prices_data = self.api_service.get_historical_daily_prices(ticker, days=365, normalize_splits=True)
            if daily_prices_data:
                for price_data in daily_prices_data:
                    price_date = price_data['date']
                    if isinstance(price_date, str):
                        from datetime import datetime
                        price_date = datetime.strptime(price_date, '%Y-%m-%d').date()
                    
                    price = ETFDailyPrice(
                        etf_id=etf_id,
                        date=price_date,
                        close_price=price_data['close'],
                        normalized_close_price=price_data.get('normalized_close', price_data['close']),
                        split_ratio_applied=price_data.get('split_ratio_applied', 1.0),
                        year=price_date.year,
                        month=price_date.month,
                        day=price_date.day
                    )
                    db.session.add(price)
                
                logger.info(f"Added {len(daily_prices_data)} historical daily prices for ETF {ticker}")
            
        except Exception as e:
            logger.error(f"Error adding historical prices for ETF {ticker}: {str(e)}")
    
    def add_weekly_prices_for_existing_etfs(self, ticker: str) -> bool:
        """
        Dodaje ceny tygodniowe dla istniejącego ETF (jeśli ich nie ma)
        
        Args:
            ticker: Ticker ETF
            
        Returns:
            True jeśli udało się dodać ceny, False w przeciwnym razie
        """
        try:
            # Sprawdź czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                logger.error(f"ETF {ticker} not found")
                return False
            
            # Usuń stare ceny tygodniowe jeśli istnieją
            existing_weekly_prices = ETFWeeklyPrice.query.filter_by(etf_id=etf.id).count()
            if existing_weekly_prices > 0:
                logger.info(f"ETF {ticker} has {existing_weekly_prices} existing weekly prices, removing old data")
                ETFWeeklyPrice.query.filter_by(etf_id=etf.id).delete()
                db.session.commit()
            
            logger.info(f"Adding weekly prices for existing ETF {ticker}")
            
            # Pobierz ceny tygodniowe z API
            weekly_prices_data = self.api_service.get_historical_weekly_prices(ticker, normalize_splits=True)
            if not weekly_prices_data:
                logger.warning(f"No weekly price data available for {ticker}")
                return False
            
            # Dodaj ceny tygodniowe do bazy
            added_count = 0
            for price_data in weekly_prices_data:
                try:
                    price = ETFWeeklyPrice(
                        etf_id=etf.id,
                        date=price_data['date'],
                        close_price=price_data.get('original_close', price_data['close']),  # Oryginalna cena
                        normalized_close_price=price_data['close'],  # Znormalizowana cena (już jest w 'close')
                        split_ratio_applied=price_data.get('split_ratio_applied', 1.0),
                        year=price_data['date'].year,
                        week_of_year=price_data['date'].isocalendar()[1]
                    )
                    db.session.add(price)
                    added_count += 1
                except Exception as e:
                    logger.warning(f"Error adding weekly price for {ticker} on {price_data['date']}: {str(e)}")
                    continue
            
            if added_count > 0:
                db.session.commit()
                logger.info(f"Successfully added {added_count} weekly prices for ETF {ticker}")
                return True
            else:
                logger.warning(f"No weekly prices were added for ETF {ticker}")
                return False
                
        except Exception as e:
            logger.error(f"Error adding weekly prices for ETF {ticker}: {str(e)}")
            db.session.rollback()
            return False

    def _add_historical_dividends(self, etf_id: int, ticker: str) -> None:
        """
        Dodaje historyczne dywidendy ETF - używa danych z cache jeśli dostępne
        """
        try:
            # Próba użycia danych z cache (jeśli były pobrane przez get_etf_data)
            cached_data = self.api_service.cache.get(f"etf_data_{ticker}")
            dividends_data = []
            
            if cached_data and 'fmp_dividends' in cached_data['data']:
                # Użyj danych z cache
                logger.info(f"Using cached dividend data for {ticker}")
                raw_dividends = cached_data['data']['fmp_dividends']
                dividends_data = self._convert_fmp_dividends_to_standard(raw_dividends)
            else:
                # Fallback do API
                logger.info(f"No cached dividend data for {ticker}, fetching from API")
                dividends_data = self.api_service.get_dividend_history(ticker, normalize_splits=True)
            
            if not dividends_data:
                logger.warning(f"No dividend data available for {ticker}")
                return
            
            for dividend_data in dividends_data:
                dividend = ETFDividend(
                    etf_id=etf_id,
                    payment_date=dividend_data['payment_date'],
                    ex_date=dividend_data.get('ex_date'),
                    amount=dividend_data.get('original_amount', dividend_data['amount']),
                    normalized_amount=dividend_data.get('normalized_amount', dividend_data['amount']),
                    split_ratio_applied=dividend_data.get('split_ratio_applied', 1.0)
                )
                db.session.add(dividend)
            
            logger.info(f"Added {len(dividends_data)} historical dividends for ETF {ticker}")
            
        except Exception as e:
            logger.error(f"Error adding historical dividends for ETF {ticker}: {str(e)}")
    
    def _check_new_dividends(self, etf_id: int, ticker: str) -> bool:
        """
        Sprawdza czy są nowe dywidendy do dodania - OSZCZĘDZA TOKENY API
        """
        try:
            # Pobieranie ostatniej dywidendy z bazy
            last_db_dividend = ETFDividend.query.filter_by(etf_id=etf_id).order_by(ETFDividend.payment_date.desc()).first()
            
            if not last_db_dividend:
                logger.info(f"No existing dividends for {ticker}, fetching all historical data")
                # Pierwszy raz - pobierz wszystkie historyczne dane
                return self._fetch_all_historical_dividends(etf_id, ticker)
            
            # Sprawdzanie czy ostatnia dywidenda jest z ostatnich 30 dni
            days_since_last = (date.today() - last_db_dividend.payment_date).days
            if days_since_last < 30:
                logger.info(f"Last dividend for {ticker} is recent ({days_since_last} days ago), no need to check API")
                return False
            
            # Sprawdzanie tylko nowych dywidend od ostatniej daty
            logger.info(f"Checking for new dividends for {ticker} since {last_db_dividend.payment_date}")
            
            # Pobieranie tylko nowych dywidend (od ostatniej daty + 1 dzień)
            new_dividends = self.api_service.get_dividend_history(
                ticker, 
                years=1,  # Tylko 1 rok wstecz - oszczędność tokenów
                normalize_splits=True,
                since_date=last_db_dividend.payment_date + timedelta(days=1)
            )
            
            if not new_dividends:
                logger.info(f"No new dividends found for {ticker}")
                return False
            
            # Filtrowanie tylko rzeczywiście nowych dywidend
            existing_dates = {div.payment_date for div in ETFDividend.query.filter_by(etf_id=etf_id).all()}
            truly_new_dividends = [div for div in new_dividends if div['payment_date'] not in existing_dates]
            
            if not truly_new_dividends:
                logger.info(f"No truly new dividends for {ticker}")
                return False
            
            # Upewniam się, że wszystkie nowe dywidendy mają wymagane klucze
            processed_new_dividends = []
            for dividend_data in truly_new_dividends:
                # Sprawdzanie czy dane mają wymagane klucze
                if 'original_amount' not in dividend_data:
                    # Jeśli nie ma original_amount, używam amount jako original_amount
                    dividend_data['original_amount'] = dividend_data.get('amount', 0)
                
                if 'normalized_amount' not in dividend_data:
                    # Jeśli nie ma normalized_amount, używam original_amount (brak splitów)
                    dividend_data['normalized_amount'] = dividend_data['original_amount']
                
                if 'split_ratio_applied' not in dividend_data:
                    # Jeśli nie ma split_ratio_applied, ustawiam 1.0 (brak splitów)
                    dividend_data['split_ratio_applied'] = 1.0
                
                processed_new_dividends.append(dividend_data)
            
            # Dodawanie nowych dywidend
            for dividend_data in processed_new_dividends:
                dividend = ETFDividend(
                    etf_id=etf_id,
                    payment_date=dividend_data['payment_date'],
                    ex_date=dividend_data['ex_date'],
                    amount=dividend_data['original_amount'],
                    normalized_amount=dividend_data['normalized_amount'],
                    split_ratio_applied=dividend_data['split_ratio_applied']
                )
                db.session.add(dividend)
            
            logger.info(f"Added {len(processed_new_dividends)} new dividends for ETF {ticker}")
            return True
            
        except Exception as e:
            logger.error(f"Error checking new dividends for ETF {ticker}: {str(e)}")
            return False

    def _fetch_all_historical_dividends(self, etf_id: int, ticker: str, force_update: bool = False) -> bool:
        """
        Pobiera wszystkie historyczne dywidendy (15 lat) - używa cache
        
        Args:
            etf_id: ID ETF w bazie danych
            ticker: Ticker ETF
            force_update: Jeśli True, ignoruje cache i pobiera nowe dane
        """
        try:
            if force_update:
                logger.info(f"Force update requested for {ticker}, ignoring cache and fetching fresh dividends")
            else:
                logger.info(f"Fetching all historical dividends for {ticker} (first time)")
            
            # Sprawdzanie czy mamy już dywidendy w bazie
            existing_dividends = ETFDividend.query.filter_by(etf_id=etf_id).count()
            if existing_dividends > 0 and not force_update:
                logger.info(f"ETF {ticker} already has {existing_dividends} dividends in database, skipping historical fetch")
                return True
            
            # Próba użycia danych z cache (jeśli były pobrane przez get_etf_data)
            all_dividends = []
            
            if not force_update and self.api_service.cache.get(f"etf_data_{ticker}"):
                cached_data = self.api_service.cache.get(f"etf_data_{ticker}")
                if cached_data and 'fmp_dividends' in cached_data['data']:
                    # Użyj danych z cache
                    logger.info(f"Using cached dividend data for {ticker} in _fetch_all_historical_dividends")
                    raw_dividends = cached_data['data']['fmp_dividends']
                    all_dividends = self._convert_fmp_dividends_to_standard(raw_dividends)
                else:
                    # Fallback do API
                    logger.info(f"No cached dividend data for {ticker}, fetching from API")
                    all_dividends = self.api_service.get_dividend_history(ticker, years=15, normalize_splits=True)
            else:
                # Force update lub brak cache - pobierz z API
                logger.info(f"{'Force update' if force_update else 'No cached data'} for {ticker}, fetching dividends from API")
                all_dividends = self.api_service.get_dividend_history(ticker, years=15, normalize_splits=True)
            
            # Jeśli nadal brak dywidend, spróbuj EODHD jako backup
            if not all_dividends:
                logger.info(f"No dividends from FMP for {ticker}, trying EODHD backup")
                eodhd_data = self.api_service._get_eodhd_data(ticker)
                if eodhd_data and 'eodhd_dividends' in eodhd_data:
                    logger.info(f"Found EODHD dividends for {ticker}, converting to standard format")
                    all_dividends = self._convert_eodhd_dividends_to_standard(eodhd_data['eodhd_dividends'])
                else:
                    logger.info(f"No EODHD dividends available for {ticker}")
            
            if not all_dividends:
                logger.warning(f"No dividends returned from API for {ticker}")
                return False
            
            # Data structure validation
            if all_dividends:
                sample_dividend = all_dividends[0]
                logger.info(f"Sample dividend data structure for {ticker}: {list(sample_dividend.keys())}")
                logger.info(f"Sample dividend data: {sample_dividend}")
            
            # Upewniam się, że wszystkie dywidendy mają wymagane klucze
            processed_dividends = []
            for dividend_data in all_dividends:
                # Sprawdzanie czy dane mają wymagane klucze
                if 'original_amount' not in dividend_data:
                    # Jeśli nie ma original_amount, używam amount jako original_amount
                    dividend_data['original_amount'] = dividend_data.get('amount', 0)
                
                if 'normalized_amount' not in dividend_data:
                    # Jeśli nie ma normalized_amount, używam original_amount (brak splitów)
                    dividend_data['normalized_amount'] = dividend_data['original_amount']
                
                if 'split_ratio_applied' not in dividend_data:
                    # Jeśli nie ma split_ratio_applied, ustawiam 1.0 (brak splitów)
                    dividend_data['split_ratio_applied'] = 1.0
                
                processed_dividends.append(dividend_data)
            
            # Dodawanie wszystkich dywidend
            added_count = 0
            for dividend_data in processed_dividends:
                try:
                    # Sprawdzanie czy dywidenda już istnieje
                    existing_dividend = ETFDividend.query.filter_by(
                        etf_id=etf_id,
                        payment_date=dividend_data['payment_date']
                    ).first()
                    
                    if not existing_dividend:
                        # Tworzenie nowej dywidendy
                        dividend = ETFDividend(
                            etf_id=etf_id,
                            payment_date=dividend_data['payment_date'],
                            ex_date=dividend_data['ex_date'],
                            amount=dividend_data['original_amount'],
                            normalized_amount=dividend_data['normalized_amount'],
                            split_ratio_applied=dividend_data['split_ratio_applied']
                        )
                        db.session.add(dividend)
                        added_count += 1
                        logger.info(f"Added dividend for {ticker} on {dividend_data['payment_date']}: {dividend_data['original_amount']}")
                    else:
                        logger.info(f"Dividend for {ticker} on {dividend_data['payment_date']} already exists")
                        
                except Exception as e:
                    logger.error(f"Error adding dividend for {ticker} on {dividend_data['payment_date']}: {str(e)}")
                    continue
            
            logger.info(f"Added {added_count} historical dividends for ETF {ticker}")
            return added_count > 0
            
        except Exception as e:
            logger.error(f"Error fetching historical dividends for ETF {ticker}: {str(e)}")
            return False
    
    def _check_new_prices(self, etf_id: int, ticker: str, force_update: bool = False) -> bool:
        """
        Sprawdza czy są nowe ceny do dodania - OSZCZĘDZA TOKENY API
        """
        logger.info(f"_check_new_prices called for {ticker} with force_update={force_update}")
        try:
            # Pobieranie ostatniej ceny z bazy
            last_db_price = ETFPrice.query.filter_by(etf_id=etf_id).order_by(ETFPrice.date.desc()).first()
            
            if not last_db_price:
                logger.info(f"No existing prices for {ticker}, fetching historical prices")
                # Pierwszy raz - pobierz historyczne ceny miesięczne
                return self._fetch_historical_monthly_prices(etf_id, ticker)
            
            # Sprawdzanie czy ostatnia cena jest z dzisiejszego dnia
            today = date.today()
            if last_db_price.date >= today:
                logger.info(f"Last price for {ticker} is from today, no need to check API")
                return False
            
            # Sprawdzanie czy ostatnia cena jest z ostatnich 7 dni (tygodniowe aktualizacje)
            # Jeśli force_update=True, ignorujemy to sprawdzenie
            if not force_update:
                days_since_last = (today - last_db_price.date).days
                if days_since_last < 7:
                    logger.info(f"Last price for {ticker} is recent ({days_since_last} days ago), no need to check API")
                    return False
            
            logger.info(f"Checking for new price for {ticker} (last price: {last_db_price.date})")
            
            # Pobieranie TYLKO aktualnej ceny (oszczędzamy tokeny API)
            current_price = None
            
            # Próba FMP (główne źródło)
            try:
                current_price = self.api_service.get_current_price_fmp(ticker)
                if current_price:
                    logger.info(f"Got current price from FMP for {ticker}: {current_price}")
            except Exception as e:
                logger.warning(f"FMP price fetch failed for {ticker}: {str(e)}")
            
            # Fallback: EODHD
            if not current_price:
                try:
                    current_price = self.api_service.get_current_price_eodhd(ticker)
                    if current_price:
                        logger.info(f"Got current price from EODHD for {ticker}: {current_price}")
                except Exception as e:
                    logger.warning(f"EODHD price fetch failed for {ticker}: {str(e)}")
            
            # Fallback: Tiingo
            if not current_price:
                try:
                    current_price = self.api_service.get_current_price_tiingo(ticker)
                    if current_price:
                        logger.info(f"Got current price from Tiingo for {ticker}: {current_price}")
                except Exception as e:
                    logger.warning(f"Tiingo price fetch failed for {ticker}: {str(e)}")
            
            if not current_price:
                logger.warning(f"No current price available for {ticker} from any source")
                return False
            
            # Dodawanie nowej ceny
            new_price = ETFPrice(
                etf_id=etf_id,
                date=today,
                close_price=current_price,
                normalized_close_price=current_price,  # Dla nowych cen split ratio = 1.0
                split_ratio_applied=1.0
            )
            db.session.add(new_price)
            
            logger.info(f"Added new price for ETF {ticker}: {current_price}")
            return True
            
        except Exception as e:
            logger.error(f"Error checking new prices for ETF {ticker}: {str(e)}")
            return False

    def _fetch_historical_monthly_prices(self, etf_id: int, ticker: str, force_update: bool = False) -> bool:
        """
        Pobiera historyczne ceny miesięczne (tylko przy pierwszym uruchomieniu) - używa cache
        
        Args:
            etf_id: ID ETF w bazie danych
            ticker: Ticker ETF
            force_update: Jeśli True, ignoruje cache i pobiera nowe dane
        """
        try:
            if force_update:
                logger.info(f"Force update requested for {ticker}, ignoring cache and fetching fresh data")
            else:
                logger.info(f"Fetching historical monthly prices for {ticker} (first time)")
            
            # Próba użycia danych z cache (jeśli były pobrane przez get_etf_data)
            historical_prices = []
            
            if not force_update and self.api_service.cache.get(f"etf_data_{ticker}"):
                cached_data = self.api_service.cache.get(f"etf_data_{ticker}")
                if 'fmp_prices' in cached_data['data']:
                    # Użyj danych z cache
                    logger.info(f"Using cached price data for {ticker} in _fetch_historical_monthly_prices")
                    raw_prices = cached_data['data']['fmp_prices']
                    historical_prices = self._convert_fmp_prices_to_monthly(raw_prices, years=15)
            
            # Jeśli nie ma danych z cache lub force_update, pobierz z API
            if not historical_prices:
                logger.info(f"{'Force update' if force_update else 'No cached price data'} for {ticker}, fetching from API")
                historical_prices = self.api_service.get_historical_prices(ticker, years=15, normalize_splits=True)
            
            if not historical_prices:
                logger.warning(f"No historical prices returned from API for {ticker}")
                return False
            
            # Data structure validation
            if historical_prices:
                sample_price = historical_prices[0]
                logger.info(f"Sample price data structure for {ticker}: {list(sample_price.keys())}")
                logger.info(f"Sample price data: {sample_price}")
            
            # Upewniam się, że wszystkie ceny mają wymagane klucze
            processed_prices = []
            for price_data in historical_prices:
                # Sprawdzanie czy dane mają wymagane klucze
                if 'original_close' not in price_data:
                    # Jeśli nie ma original_close, używam close jako original_close
                    price_data['original_close'] = price_data.get('close', 0)
                
                if 'normalized_close' not in price_data:
                    # Jeśli nie ma normalized_close, używam original_close (brak splitów)
                    price_data['normalized_close'] = price_data['original_close']
                
                if 'split_ratio_applied' not in price_data:
                    # Jeśli nie ma split_ratio_applied, ustawiam 1.0 (brak splitów)
                    price_data['split_ratio_applied'] = 1.0
                
                processed_prices.append(price_data)
            
            # Dodawanie cen miesięcznych
            added_count = 0
            for price_data in processed_prices:
                try:
                    # Sprawdzanie czy cena już istnieje
                    existing_price = ETFPrice.query.filter_by(
                        etf_id=etf_id, 
                        date=price_data['date']
                    ).first()
                    
                    if not existing_price:
                        # Tworzenie nowej ceny
                        new_price = ETFPrice(
                            etf_id=etf_id,
                            date=price_data['date'],
                            close_price=price_data['original_close'],
                            normalized_close_price=price_data['normalized_close'],
                            split_ratio_applied=price_data['split_ratio_applied']
                        )
                        db.session.add(new_price)
                        added_count += 1
                        logger.info(f"Added price for {ticker} on {price_data['date']}: {price_data['original_close']}")
                    else:
                        logger.info(f"Price for {ticker} on {price_data['date']} already exists")
                        
                except Exception as e:
                    logger.error(f"Error adding price for {ticker} on {price_data['date']}: {str(e)}")
                    continue
            
            logger.info(f"Added {added_count} historical monthly prices for ETF {ticker}")
            return added_count > 0
            
        except Exception as e:
            logger.error(f"Error fetching historical prices for ETF {ticker}: {str(e)}")
            return False

    def _manage_splits(self, etf_id: int, ticker: str) -> bool:
        """
        Zarządza splitami ETF - OSZCZĘDZA TOKENY API - cache w bazie
        """
        try:
            # Sprawdzanie czy mamy już splity w bazie
            existing_splits = ETFSplit.query.filter_by(etf_id=etf_id).all()
            
            if existing_splits:
                # Mamy splity w bazie - sprawdzaj tylko raz na tydzień
                last_split_check = max(split.created_at for split in existing_splits)
                days_since_check = (datetime.now(timezone.utc) - last_split_check).days
                
                if days_since_check < 7:
                    logger.info(f"Splits for {ticker} checked recently ({days_since_check} days ago), using cache")
                    return False
            
            logger.info(f"Checking for new splits for {ticker}")
            
            # Pobieranie splitów z API (tylko gdy potrzebne)
            splits_data = self.api_service.get_stock_splits(ticker)
            if not splits_data:
                logger.info(f"No splits found for {ticker}")
                return False
            
            # Sprawdzanie nowych splitów
            existing_split_dates = {split.split_date for split in existing_splits}
            new_splits = []
            
            for split_data in splits_data:
                split_date = datetime.strptime(split_data['date'], '%Y-%m-%d').date()
                if split_date not in existing_split_dates:
                    new_splits.append(split_data)
            
            if not new_splits:
                logger.info(f"No new splits for {ticker}")
                return False
            
            # Dodawanie nowych splitów
            for split_data in new_splits:
                split = ETFSplit(
                    etf_id=etf_id,
                    split_date=datetime.strptime(split_data['date'], '%Y-%m-%d').date(),
                    split_ratio=float(split_data['ratio']),
                    description=split_data.get('description', f"{split_data['ratio']}:1 Stock Split")
                )
                db.session.add(split)
                logger.info(f"Added new split for {ticker}: {split_data['ratio']}:1 on {split_data['date']}")
            
            # Po dodaniu nowego splitu, musimy ponownie znormalizować wszystkie historyczne dane
            if new_splits:
                logger.info(f"Re-normalizing all historical data for {ticker} due to new splits")
                self._renormalize_all_data(etf_id, ticker)
            
            return True
            
        except Exception as e:
            logger.error(f"Error managing splits for ETF {ticker}: {str(e)}")
            return False

    def _renormalize_all_data(self, etf_id: int, ticker: str) -> None:
        """
        Ponownie normalizuje wszystkie historyczne dane po wykryciu nowego splitu
        """
        try:
            # Pobieranie wszystkich splitów (posortowanych chronologicznie)
            all_splits = ETFSplit.query.filter_by(etf_id=etf_id).order_by(ETFSplit.split_date).all()
            
            if not all_splits:
                return
            
            # Aktualizacja dywidend
            dividends = ETFDividend.query.filter_by(etf_id=etf_id).all()
            for dividend in dividends:
                split_ratio = self._calculate_cumulative_split_ratio(all_splits, dividend.payment_date)
                dividend.normalized_amount = dividend.amount / split_ratio
                dividend.split_ratio_applied = split_ratio
            
            # Aktualizacja cen ETF
            prices = ETFPrice.query.filter_by(etf_id=etf_id).all()
            for price in prices:
                split_ratio = self._calculate_cumulative_split_ratio(all_splits, price.date)
                price.normalized_close_price = price.close_price / split_ratio
                price.split_ratio_applied = split_ratio
            
            logger.info(f"Re-normalized {len(dividends)} dividends and {len(prices)} prices for {ticker}")
            
        except Exception as e:
            logger.error(f"Error re-normalizing data for ETF {ticker}: {str(e)}")

    def _calculate_cumulative_split_ratio(self, splits: List[ETFSplit], target_date: date) -> float:
        """
        Oblicza kumulacyjny współczynnik splitu dla danej daty
        """
        cumulative_ratio = 1.0
        
        for split in splits:
            if target_date < split.split_date:
                cumulative_ratio *= split.split_ratio
        
        return cumulative_ratio
    
    def _log_action(self, action: str, details: str, level: str = 'INFO') -> None:
        """
        Loguje akcje systemu
        """
        try:
            log_entry = SystemLog(
                action=action,
                details=details,
                level=level
            )
            db.session.add(log_entry)
            db.session.flush()
        except Exception as e:
            logger.error(f"Error logging action: {str(e)}")
    
    def cleanup_old_data(self, days: int = 30) -> None:
        """
        Usuwa stare logi systemu
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            deleted = SystemLog.query.filter(SystemLog.timestamp < cutoff_date).delete()
            db.session.commit()
            
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old system logs")
                self._log_action('CLEANUP', f"Removed {deleted} old system logs")
                
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
            db.session.rollback()

    def cleanup_old_daily_prices(self, days: int = 365) -> None:
        """
        Usuwa ceny dzienne starsze niż X dni (rolling window)
        """
        try:
            cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=days)
            deleted = ETFDailyPrice.query.filter(ETFDailyPrice.date < cutoff_date).delete()
            db.session.commit()
            
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old daily prices (older than {days} days)")
                self._log_action('CLEANUP', f"Removed {deleted} old daily prices")
                
        except Exception as e:
            logger.error(f"Error during daily prices cleanup: {str(e)}")
            db.session.rollback()

    def _check_api_health_before_update(self, ticker: str) -> Dict:
        """
        Sprawdza zdrowie API przed aktualizacją ETF
        """
        try:
            from services.api_service import APIService
            api_service = APIService()
            return api_service.check_api_health()
        except Exception as e:
            logger.error(f"Error checking API health for {ticker}: {str(e)}")
            return {
                'can_continue': False,
                'recommendations': [f"Error checking API health: {str(e)}"],
                'critical_apis': ['unknown']
            }

    def _update_from_cache_only(self, ticker: str) -> bool:
        """
        Aktualizuje ETF tylko z cache (gdy API niedostępne)
        """
        try:
            logger.info(f"Updating {ticker} from cache only (API unavailable)")
            
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return False
            
            # Sprawdzanie czy mamy wystarczająco danych w cache
            recent_dividends = ETFDividend.query.filter_by(etf_id=etf.id).order_by(ETFDividend.payment_date.desc()).limit(5).all()
            recent_prices = ETFPrice.query.filter_by(etf_id=etf.id).order_by(ETFPrice.date.desc()).limit(5).all()
            
            if not recent_dividends or not recent_prices:
                logger.warning(f"Insufficient cache data for {ticker}, cannot update")
                return False
            
            # Aktualizacja timestamp (tylko jeśli mamy dane)
            etf.last_updated = datetime.now(timezone.utc)
            db.session.commit()
            logger.info(f"ETF {ticker} cache-only update completed")
            return True
            
        except Exception as e:
            logger.error(f"Error in cache-only update for {ticker}: {str(e)}")
            return False

    def calculate_recent_dividend_sum(self, etf_id: int, frequency: str = None) -> float:
        """
        Oblicza sumę ostatnich dywidend w zależności od częstotliwości
        
        Args:
            etf_id: ID ETF
            frequency: Częstotliwość wypłat ('monthly', 'quarterly', 'annual')
        
        Returns:
            Suma ostatnich dywidend lub 0.0 jeśli brak danych
        """
        try:
            # Pobieranie dywidend posortowanych od najnowszej
            dividends = ETFDividend.query.filter_by(etf_id=etf_id).order_by(ETFDividend.payment_date.desc()).all()
            
            if not dividends:
                return 0.0
            
            # Określenie liczby ostatnich dywidend do zsumowania
            if frequency == 'monthly':
                num_dividends = 12  # 12 ostatnich miesięcznych
            elif frequency == 'quarterly':
                num_dividends = 4   # 4 ostatnie kwartalne
            elif frequency == 'annual':
                num_dividends = 1   # 1 ostatnia roczna
            else:
                # Jeśli nie określono częstotliwości, spróbuj odgadnąć na podstawie danych
                if len(dividends) >= 12:
                    # Sprawdzanie czy to miesięczne (12 dywidend w roku)
                    recent_12 = dividends[:12]
                    dates = [div.payment_date for div in recent_12]
                    if self._is_monthly_frequency(dates):
                        num_dividends = 12
                    else:
                        num_dividends = 4  # Domyślnie kwartalne
                else:
                    num_dividends = min(4, len(dividends))  # Maksymalnie 4 lub wszystkie dostępne
            
            # Pobranie ostatnich N dywidend
            recent_dividends = dividends[:num_dividends]
            
            # Sumowanie znormalizowanych kwot
            total_sum = sum(div.normalized_amount for div in recent_dividends)
            
            return round(total_sum, 5)  # 5 miejsc po przecinku
            
        except Exception as e:
            logger.error(f"Error calculating dividend sum for ETF {etf_id}: {str(e)}")
            return 0.0

    def calculate_dividend_growth_forecast(self, etf_id: int, frequency: str = None) -> float:
        """
        Oblicza prognozowany wzrost dywidendy porównując sumę ostatnich dywidend z roczną dywidendą z poprzedniego roku
        
        Args:
            etf_id: ID ETF
            frequency: Częstotliwość wypłat ('monthly', 'quarterly', 'annual')
        
        Returns:
            Prognozowany wzrost w procentach lub 0.0 jeśli brak danych
        """
        try:
            # Pobieranie dywidend posortowanych od najnowszej
            dividends = ETFDividend.query.filter_by(etf_id=etf_id).order_by(ETFDividend.payment_date.desc()).all()
            
            if not dividends:
                return 0.0
            
            # Obliczenie sumy ostatnich dywidend
            recent_sum = self.calculate_recent_dividend_sum(etf_id, frequency)
            if recent_sum == 0.0:
                return 0.0
            
            # Znalezienie ostatniego zakończonego roku kalendarzowego
            current_year = datetime.now().year
            last_completed_year = current_year - 1
            
            # Pobieranie dywidend z ostatniego zakończonego roku
            yearly_dividends = [div for div in dividends if div.payment_date.year == last_completed_year]
            
            if not yearly_dividends:
                # Jeśli brak danych z poprzedniego roku, spróbuj z roku bieżącego
                yearly_dividends = [div for div in dividends if div.payment_date.year == current_year]
                if not yearly_dividends:
                    return 0.0
            
            # Sumowanie dywidend z roku
            yearly_total = sum(div.normalized_amount for div in yearly_dividends)
            
            if yearly_total == 0.0:
                return 0.0
            
            # Obliczenie wzrostu w procentach
            growth_percentage = ((recent_sum - yearly_total) / yearly_total) * 100
            
            return round(growth_percentage, 2)  # 2 miejsca po przecinku
            
        except Exception as e:
            logger.error(f"Error calculating dividend growth forecast for ETF {etf_id}: {str(e)}")
            return 0.0

    def _is_monthly_frequency(self, dates: List[date]) -> bool:
        """
        Sprawdza czy daty sugerują miesięczną częstotliwość
        """
        try:
            if len(dates) < 2:
                return False
            
            # Sprawdzanie czy daty są w odstępach około miesięcznych
            for i in range(1, len(dates)):
                days_diff = (dates[i-1] - dates[i]).days
                # Miesięczne: 25-35 dni, kwartalne: 80-100 dni
                if 25 <= days_diff <= 35:
                    continue
                elif 80 <= days_diff <= 100:
                    return False
                else:
                    # Jeśli nie jest ani miesięczne ani kwartalne, domyślnie kwartalne
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking monthly frequency: {str(e)}")
            return False

    def _convert_fmp_dividends_to_standard(self, fmp_dividends: List[Dict]) -> List[Dict]:
        """
        Konwertuje dywidendy z formatu FMP na standardowy format
        """
        standard_dividends = []
        
        for fmp_div in fmp_dividends:
            try:
                # FMP zwraca 'dividend' a nie 'amount'
                dividend_amount = fmp_div.get('dividend') or fmp_div.get('amount', 0)
                if dividend_amount:
                    standard_div = {
                        'payment_date': datetime.strptime(fmp_div['date'], '%Y-%m-%d').date(),
                        'ex_date': None,  # FMP nie ma ex-date
                        'amount': float(dividend_amount),
                        'original_amount': float(dividend_amount),
                        'normalized_amount': float(dividend_amount),
                        'split_ratio_applied': 1.0
                    }
                    standard_dividends.append(standard_div)
            except (KeyError, ValueError) as e:
                logger.warning(f"Error converting FMP dividend: {str(e)}")
                continue
        
        return standard_dividends

    def _convert_fmp_prices_to_monthly(self, fmp_prices: List[Dict], years: int = 15) -> List[Dict]:
        """
        Konwertuje ceny z formatu FMP na miesięczne
        """
        monthly_data = []
        cutoff_date = datetime.now() - timedelta(days=years*365)
        
        logger.info(f"Converting {len(fmp_prices)} FMP prices to monthly for {years} years")
        logger.info(f"Cutoff date: {cutoff_date.date()}")
        
        for price in fmp_prices:
            try:
                price_date = datetime.strptime(price['date'], '%Y-%m-%d')
                if price_date >= cutoff_date:
                    monthly_price = {
                        'date': price_date.date(),
                        'close': float(price['close']),
                        'open': float(price['open']),
                        'high': float(price['high']),
                        'low': float(price['low']),
                        'volume': int(price['volume'])
                    }
                    monthly_data.append(monthly_price)
            except (KeyError, ValueError) as e:
                logger.warning(f"Error converting FMP price: {str(e)}")
                continue
        
        logger.info(f"Converted {len(monthly_data)} monthly prices")
        return monthly_data

    def _convert_eodhd_dividends_to_standard(self, eodhd_dividends: List[Dict]) -> List[Dict]:
        """
        Konwertuje dywidendy z formatu EODHD na standardowy format
        """
        standard_dividends = []
        
        for eodhd_div in eodhd_dividends:
            try:
                # EODHD może mieć różne formaty - sprawdzamy dostępne pola
                dividend_amount = eodhd_div.get('value') or eodhd_div.get('amount') or eodhd_div.get('dividend', 0)
                dividend_date = eodhd_div.get('date') or eodhd_div.get('paymentDate')
                
                if dividend_amount and dividend_date:
                    # Konwersja daty
                    if isinstance(dividend_date, str):
                        try:
                            # Próba różnych formatów daty
                            for date_format in ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S']:
                                try:
                                    parsed_date = datetime.strptime(dividend_date, date_format)
                                    break
                                except ValueError:
                                    continue
                            else:
                                logger.warning(f"Could not parse EODHD dividend date: {dividend_date}")
                                continue
                        except:
                            logger.warning(f"Error parsing EODHD dividend date: {dividend_date}")
                            continue
                    else:
                        parsed_date = dividend_date
                    
                    standard_div = {
                        'payment_date': parsed_date.date() if hasattr(parsed_date, 'date') else parsed_date,
                        'ex_date': None,  # EODHD może nie mieć ex-date
                        'amount': float(dividend_amount),
                        'original_amount': float(dividend_amount),
                        'normalized_amount': float(dividend_amount),
                        'split_ratio_applied': 1.0
                    }
                    standard_dividends.append(standard_div)
            except (KeyError, ValueError) as e:
                logger.warning(f"Error converting EODHD dividend: {str(e)}")
                continue
        
        return standard_dividends

    def get_etf_splits(self, etf_id: int) -> List[ETFSplit]:
        """Pobiera wszystkie splity dla danego ETF"""
        return ETFSplit.query.filter_by(etf_id=etf_id).order_by(ETFSplit.split_date.desc()).all()

    def get_dividend_tax_rate(self) -> float:
        """Pobiera aktualną stawkę podatku od dywidend"""
        try:
            tax_rate = DividendTaxRate.query.filter_by(is_active=True).first()
            return tax_rate.tax_rate if tax_rate else 0.0
        except Exception as e:
            logger.error(f"Error getting dividend tax rate: {str(e)}")
            return 0.0

    def update_dividend_tax_rate(self, new_tax_rate: float) -> bool:
        """Aktualizuje stawkę podatku od dywidend"""
        try:
            # Dezaktywuj poprzednie stawki
            DividendTaxRate.query.update({'is_active': False})
            
            # Dodaj nową stawkę
            new_tax = DividendTaxRate(tax_rate=new_tax_rate, is_active=True)
            db.session.add(new_tax)
            db.session.commit()
            
            logger.info(f"Dividend tax rate updated to {new_tax_rate}%")
            return True
        except Exception as e:
            logger.error(f"Error updating dividend tax rate: {str(e)}")
            db.session.rollback()
            return False

    def calculate_after_tax_amount(self, original_amount: float, tax_rate: float = None) -> float:
        """Oblicza kwotę po podatku od dywidend"""
        if tax_rate is None:
            tax_rate = self.get_dividend_tax_rate()
        
        if tax_rate <= 0:
            return original_amount
        
        return original_amount * (1 - tax_rate / 100)

    def calculate_after_tax_yield(self, original_yield: float, tax_rate: float = None) -> float:
        """Oblicza yield po podatku od dywidend"""
        if tax_rate is None:
            tax_rate = self.get_dividend_tax_rate()
        
        if tax_rate <= 0:
            return original_yield
        
        return original_yield * (1 - tax_rate / 100)

    def verify_data_completeness(self, etf_id: int, ticker: str) -> Dict:
        """
        Sprawdza kompletność danych historycznych ETF względem rzeczywistego wieku ETF
        
        Args:
            etf_id: ID ETF w bazie danych
            ticker: Ticker ETF
            
        Returns:
            Dict z informacjami o kompletności:
            {
                'prices_complete': bool,
                'dividends_complete': bool,
                'weekly_prices_complete': bool,
                'missing_price_months': List[date],
                'missing_dividend_years': List[int],
                'missing_weekly_weeks': List[date],
                'oldest_price_date': date,
                'oldest_dividend_date': date,
                'oldest_weekly_date': date,
                'years_of_price_data': int,
                'years_of_dividend_data': int,
                'years_of_weekly_data': int,
                'etf_inception_date': date,
                'etf_age_years': float,
                'expected_years': int
            }
        """
        try:
            from datetime import date, timedelta
            
            today = date.today()
            
            # Pobierz ETF aby sprawdzić datę inception
            etf = ETF.query.filter_by(id=etf_id).first()
            etf_inception_date = etf.inception_date if etf and etf.inception_date else None
            
            # Określ oczekiwaną liczbę lat historii
            from config import Config
            config = Config()
            max_history_years = config.MAX_HISTORY_YEARS
            
            if etf_inception_date:
                etf_age_years = (today - etf_inception_date).days / 365.25
                expected_years = min(max_history_years, int(etf_age_years))  # Maksymalnie z konfiguracji lub wiek ETF
                target_start_date = etf_inception_date
                logger.info(f"ETF {ticker} has inception date {etf_inception_date}, age: {etf_age_years:.1f} years, expecting {expected_years} years of history")
            else:
                # Fallback - z konfiguracji
                etf_age_years = float(max_history_years)
                expected_years = max_history_years
                target_start_date = today - timedelta(days=max_history_years*365)
                logger.info(f"ETF {ticker} has no inception date, using {max_history_years}-year fallback")
            
            # Sprawdzanie kompletności cen
            prices = ETFPrice.query.filter_by(etf_id=etf_id).order_by(ETFPrice.date).all()
            
            if not prices:
                return {
                    'prices_complete': False,
                    'dividends_complete': False,
                    'missing_price_months': [],
                    'missing_dividend_years': [],
                    'oldest_price_date': None,
                    'oldest_dividend_date': None,
                    'years_of_price_data': 0,
                    'years_of_dividend_data': 0,
                    'etf_inception_date': etf_inception_date,
                    'etf_age_years': etf_age_years,
                    'expected_years': expected_years
                }
            
            oldest_price_date = prices[0].date
            newest_price_date = prices[-1].date
            years_of_price_data = (newest_price_date - oldest_price_date).days / 365.25
            
            # Sprawdzanie brakujących miesięcy
            missing_price_months = []
            current_date = oldest_price_date.replace(day=1)  # Pierwszy dzień miesiąca
            
            while current_date <= newest_price_date:
                month_start = current_date.replace(day=1)
                month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                
                # Sprawdź czy mamy cenę w tym miesiącu
                month_price = ETFPrice.query.filter(
                    ETFPrice.etf_id == etf_id,
                    ETFPrice.date >= month_start,
                    ETFPrice.date <= month_end
                ).first()
                
                if not month_price:
                    missing_price_months.append(month_start)
                
                current_date = month_end + timedelta(days=1)
            
            # Sprawdzanie kompletności dywidend
            dividends = ETFDividend.query.filter_by(etf_id=etf_id).order_by(ETFDividend.payment_date).all()
            
            if not dividends:
                return {
                    'prices_complete': len(missing_price_months) == 0 and oldest_price_date <= target_start_date,
                    'dividends_complete': False,
                    'missing_price_months': missing_price_months,
                    'missing_dividend_years': [],
                    'oldest_price_date': oldest_price_date,
                    'oldest_dividend_date': None,
                    'years_of_price_data': years_of_price_data,
                    'years_of_dividend_data': 0,
                    'etf_inception_date': etf_inception_date,
                    'etf_age_years': etf_age_years,
                    'expected_years': expected_years
                }
            
            oldest_dividend_date = dividends[0].payment_date
            newest_dividend_date = dividends[-1].payment_date
            years_of_dividend_data = (newest_dividend_date - oldest_dividend_date).days / 365.25
            
            # Sprawdzanie brakujących lat dywidend
            missing_dividend_years = []
            current_year = oldest_dividend_date.year
            
            while current_year <= newest_dividend_date.year:
                year_start = date(current_year, 1, 1)
                year_end = date(current_year, 12, 31)
                
                # Sprawdź czy mamy dywidendę w tym roku
                year_dividend = ETFDividend.query.filter(
                    ETFDividend.etf_id == etf_id,
                    ETFDividend.payment_date >= year_start,
                    ETFDividend.payment_date <= year_end
                ).first()
                
                if not year_dividend:
                    missing_dividend_years.append(current_year)
                
                current_year += 1
            
            # Określanie kompletności względem rzeczywistego wieku ETF
            prices_complete = len(missing_price_months) == 0 and oldest_price_date <= target_start_date
            dividends_complete = len(missing_dividend_years) == 0 and oldest_dividend_date <= target_start_date
            
            # Jeśli ETF jest młodszy niż 15 lat i mamy dane od inception, to jest kompletny
            if etf_inception_date and years_of_price_data >= (etf_age_years * 0.9):  # 90% pokrycia
                prices_complete = True
            if etf_inception_date and years_of_dividend_data >= (etf_age_years * 0.9):  # 90% pokrycia
                dividends_complete = True
            
            logger.info(f"Data completeness check for {ticker}: "
                       f"ETF age: {etf_age_years:.1f} years, expected: {expected_years} years; "
                       f"Prices: {years_of_price_data:.1f} years, complete: {prices_complete}, "
                       f"missing months: {len(missing_price_months)}; "
                       f"Dividends: {years_of_dividend_data:.1f} years, complete: {dividends_complete}, "
                       f"missing years: {len(missing_dividend_years)}")
            
            # Sprawdzanie kompletności cen tygodniowych
            weekly_prices = ETFWeeklyPrice.query.filter_by(etf_id=etf_id).order_by(ETFWeeklyPrice.date).all()
            
            if not weekly_prices:
                return {
                    'prices_complete': prices_complete,
                    'dividends_complete': dividends_complete,
                    'weekly_prices_complete': False,
                    'missing_price_months': missing_price_months,
                    'missing_dividend_years': missing_dividend_years,
                    'missing_weekly_weeks': [],
                    'oldest_price_date': oldest_price_date,
                    'oldest_dividend_date': oldest_dividend_date,
                    'oldest_weekly_date': None,
                    'years_of_price_data': years_of_price_data,
                    'years_of_dividend_data': years_of_dividend_data,
                    'years_of_weekly_data': 0,
                    'etf_inception_date': etf_inception_date,
                    'etf_age_years': etf_age_years,
                    'expected_years': expected_years
                }
            
            oldest_weekly_date = weekly_prices[0].date
            newest_weekly_date = weekly_prices[-1].date
            years_of_weekly_data = (newest_weekly_date - oldest_weekly_date).days / 365.25
            
            # Sprawdzanie brakujących tygodni
            missing_weekly_weeks = []
            current_date = oldest_weekly_date
            
            while current_date <= newest_weekly_date:
                week_start = current_date - timedelta(days=current_date.weekday())  # Poniedziałek tego tygodnia
                week_end = week_start + timedelta(days=6)  # Niedziela tego tygodnia
                
                # Sprawdź czy mamy cenę w tym tygodniu
                week_price = ETFWeeklyPrice.query.filter(
                    ETFWeeklyPrice.etf_id == etf_id,
                    ETFWeeklyPrice.date >= week_start,
                    ETFWeeklyPrice.date <= week_end
                ).first()
                
                if not week_price:
                    missing_weekly_weeks.append(week_start)
                
                current_date = week_end + timedelta(days=1)
            
            # Określanie kompletności cen tygodniowych
            weekly_prices_complete = len(missing_weekly_weeks) == 0 and oldest_weekly_date <= target_start_date
            
            # Jeśli ETF jest młodszy niż 15 lat i mamy dane od inception, to jest kompletny
            if etf_inception_date and years_of_weekly_data >= (etf_age_years * 0.9):  # 90% pokrycia
                weekly_prices_complete = True
            
            logger.info(f"Data completeness check for {ticker}: "
                       f"ETF age: {etf_age_years:.1f} years, expected: {expected_years} years; "
                       f"Prices: {years_of_price_data:.1f} years, complete: {prices_complete}, "
                       f"missing months: {len(missing_price_months)}; "
                       f"Weekly prices: {years_of_weekly_data:.1f} years, complete: {weekly_prices_complete}, "
                       f"missing weeks: {len(missing_weekly_weeks)}; "
                       f"Dividends: {years_of_dividend_data:.1f} years, complete: {dividends_complete}, "
                       f"missing years: {len(missing_dividend_years)}")
            
            return {
                'prices_complete': prices_complete,
                'dividends_complete': dividends_complete,
                'weekly_prices_complete': weekly_prices_complete,
                'missing_price_months': missing_price_months,
                'missing_dividend_years': missing_dividend_years,
                'missing_weekly_weeks': missing_weekly_weeks,
                'oldest_price_date': oldest_price_date,
                'oldest_dividend_date': oldest_dividend_date,
                'oldest_weekly_date': oldest_weekly_date,
                'years_of_price_data': years_of_price_data,
                'years_of_dividend_data': years_of_dividend_data,
                'years_of_weekly_data': years_of_weekly_data,
                'etf_inception_date': etf_inception_date,
                'etf_age_years': etf_age_years,
                'expected_years': expected_years
            }
            
        except Exception as e:
            logger.error(f"Error verifying data completeness for ETF {ticker}: {str(e)}")
            return {
                'prices_complete': False,
                'dividends_complete': False,
                'weekly_prices_complete': False,
                'missing_price_months': [],
                'missing_dividend_years': [],
                'missing_weekly_weeks': [],
                'oldest_price_date': None,
                'oldest_dividend_date': None,
                'oldest_weekly_date': None,
                'years_of_price_data': 0,
                'years_of_dividend_data': 0,
                'years_of_weekly_data': 0,
                'etf_inception_date': None,
                'etf_age_years': 0,
                'expected_years': 0
            }

    def verify_daily_completeness(self, etf_id: int, ticker: str) -> Dict:
        """
        Sprawdza kompletność danych dziennych ETF (365±5 dni)
        
        Args:
            etf_id: ID ETF w bazie danych
            ticker: Ticker ETF
            
        Returns:
            Dict z informacjami o kompletności danych dziennych:
            {
                'daily_prices_complete': bool,
                'missing_daily_days': List[date],
                'oldest_daily_date': date,
                'newest_daily_date': date,
                'days_of_daily_data': int,
                'expected_days': int
            }
        """
        try:
            from datetime import date, timedelta
            from config import Config
            
            today = date.today()
            config = Config()
            expected_days = config.DAILY_PRICES_WINDOW_DAYS
            tolerance_days = 5
            
            # Sprawdzanie kompletności cen dziennych
            daily_prices = ETFDailyPrice.query.filter_by(etf_id=etf_id).order_by(ETFDailyPrice.date).all()
            
            if not daily_prices:
                return {
                    'daily_prices_complete': False,
                    'missing_daily_days': [],
                    'oldest_daily_date': None,
                    'newest_daily_date': None,
                    'days_of_daily_data': 0,
                    'expected_days': expected_days
                }
            
            oldest_daily_date = daily_prices[0].date
            newest_daily_date = daily_prices[-1].date
            days_of_daily_data = (newest_daily_date - oldest_daily_date).days + 1
            
            # Sprawdzanie czy mamy dzisiejszą cenę
            has_today_price = ETFDailyPrice.query.filter_by(
                etf_id=etf_id,
                date=today
            ).first() is not None
            
            # Sprawdzanie brakujących dni
            missing_daily_days = []
            current_date = oldest_daily_date
            
            while current_date <= newest_daily_date:
                # Sprawdź czy mamy cenę w tym dniu
                daily_price = ETFDailyPrice.query.filter(
                    ETFDailyPrice.etf_id == etf_id,
                    ETFDailyPrice.date == current_date
                ).first()
                
                if not daily_price:
                    missing_daily_days.append(current_date)
                
                current_date += timedelta(days=1)
            
            # Określanie kompletności (365±5 dni)
            min_expected_days = expected_days - tolerance_days  # 360 dni
            max_expected_days = expected_days + tolerance_days  # 370 dni
            
            daily_prices_complete = (
                days_of_daily_data >= min_expected_days and 
                days_of_daily_data <= max_expected_days and
                has_today_price and
                len(missing_daily_days) == 0
            )
            
            logger.info(f"Daily prices completeness check for {ticker}: "
                       f"Days of data: {days_of_daily_data}, expected: {expected_days}±{tolerance_days}; "
                       f"Complete: {daily_prices_complete}, missing days: {len(missing_daily_days)}; "
                       f"Has today: {has_today_price}")
            
            return {
                'daily_prices_complete': daily_prices_complete,
                'missing_daily_days': missing_daily_days,
                'oldest_daily_date': oldest_daily_date,
                'newest_daily_date': newest_daily_date,
                'days_of_daily_data': days_of_daily_data,
                'expected_days': expected_days
            }
            
        except Exception as e:
            logger.error(f"Error verifying daily completeness for ETF {ticker}: {str(e)}")
            return {
                'daily_prices_complete': False,
                'missing_daily_days': [],
                'oldest_daily_date': None,
                'newest_daily_date': None,
                'days_of_daily_data': 0,
                'expected_days': 365
            }

    def smart_history_completion(self, etf_id: int, ticker: str) -> Dict:
        """
        Inteligentnie uzupełnia brakujące dane historyczne ETF
        
        Args:
            etf_id: ID ETF w bazie danych
            ticker: Ticker ETF
            
        Returns:
            Dict z informacjami o uzupełnieniu:
            {
                'prices_filled': int,
                'dividends_filled': int,
                'weekly_prices_filled': int,
                'daily_prices_filled': int,
                'prices_complete': bool,
                'dividends_complete': bool,
                'weekly_prices_complete': bool,
                'daily_prices_complete': bool,
                'api_calls_used': int
            }
        """
        try:
            # Sprawdź kompletność danych
            completeness = self.verify_data_completeness(etf_id, ticker)
            daily_completeness = self.verify_daily_completeness(etf_id, ticker)
            
            from config import Config
            config = Config()
            max_history_years = config.MAX_HISTORY_YEARS
            daily_window_days = config.DAILY_PRICES_WINDOW_DAYS
            
            if (completeness['prices_complete'] and 
                completeness['dividends_complete'] and 
                completeness['weekly_prices_complete'] and
                daily_completeness['daily_prices_complete']):
                logger.info(f"ETF {ticker} already has complete {max_history_years}-year history and {daily_window_days}-day daily data")
                return {
                    'prices_filled': 0,
                    'dividends_filled': 0,
                    'weekly_prices_filled': 0,
                    'daily_prices_filled': 0,
                    'prices_complete': True,
                    'dividends_complete': True,
                    'weekly_prices_complete': True,
                    'daily_prices_complete': True,
                    'api_calls_used': 0
                }
            
            api_calls_used = 0
            prices_filled = 0
            dividends_filled = 0
            weekly_prices_filled = 0
            daily_prices_filled = 0
            
            # Uzupełnianie brakujących cen miesięcznych
            if not completeness['prices_complete']:
                if completeness['missing_price_months']:
                    logger.info(f"ETF {ticker} missing {len(completeness['missing_price_months'])} price months, attempting to fill")
                else:
                    logger.warning(f"ETF {ticker} has NO price data at all - fetching full 15-year history!")
                
                # Pobierz brakujące ceny z API
                if completeness['missing_price_months']:
                    missing_months = completeness['missing_price_months']
                    oldest_missing = min(missing_months)
                    logger.info(f"Fetching prices from {oldest_missing} for {ticker}")
                else:
                    # Brak cen w bazie - pobierz pełną historię
                    missing_months = []
                    oldest_missing = None
                    logger.info(f"ETF {ticker} has no price data - fetching full {max_history_years}-year history")
                
                # Pobierz ceny z API
                historical_prices = self.api_service.get_historical_prices(
                    ticker, 
                    years=max_history_years, 
                    normalize_splits=True
                )
                
                if historical_prices:
                    api_calls_used += 1
                    
                    # Dodaj ceny do bazy
                    if missing_months:
                        # Dodaj tylko brakujące ceny
                        for price_data in historical_prices:
                            price_date = price_data['date']
                            
                            # Sprawdź czy to brakujący miesiąc
                            if price_date in missing_months:
                                # Sprawdź czy już nie mamy tej ceny
                                existing_price = ETFPrice.query.filter_by(
                                    etf_id=etf_id,
                                    date=price_date
                                ).first()
                                
                                if not existing_price:
                                    price = ETFPrice(
                                        etf_id=etf_id,
                                        date=price_date,
                                        close_price=price_data['close'],
                                        normalized_close_price=price_data.get('normalized_close', price_data['close']),
                                        split_ratio_applied=price_data.get('split_ratio_applied', 1.0)
                                    )
                                    db.session.add(price)
                                    prices_filled += 1
                        
                        logger.info(f"Filled {prices_filled} missing price months for {ticker}")
                    else:
                        # Brak cen w bazie - dodaj wszystkie pobrane ceny
                        for price_data in historical_prices:
                            # Sprawdź czy już nie mamy tej ceny (zabezpieczenie przed duplikatami)
                            existing_price = ETFPrice.query.filter_by(
                                etf_id=etf_id,
                                date=price_data['date']
                            ).first()
                            
                            if not existing_price:
                                price = ETFPrice(
                                    etf_id=etf_id,
                                    date=price_data['date'],
                                    close_price=price_data['close'],
                                    normalized_close_price=price_data.get('normalized_close', price_data['close']),
                                    split_ratio_applied=price_data.get('split_ratio_applied', 1.0)
                                )
                                db.session.add(price)
                                prices_filled += 1
                        
                        logger.info(f"Added {prices_filled} historical prices for {ticker} (no existing data)")
                    
                    # Zatwierdź zmiany w bazie
                    if prices_filled > 0:
                        db.session.commit()
                        logger.info(f"Successfully committed {prices_filled} new prices to database for {ticker}")
            
            # Uzupełnianie brakujących dywidend
            if not completeness['dividends_complete'] and completeness['missing_dividend_years']:
                logger.info(f"ETF {ticker} missing {len(completeness['missing_dividend_years'])} dividend years, attempting to fill")
                
                # Pobierz brakujące dywidendy z API
                missing_years = completeness['missing_dividend_years']
                oldest_missing_year = min(missing_years)
                
                # Pobierz dywidendy od najstarszego brakującego roku
                since_date = date(oldest_missing_year, 1, 1)
                historical_dividends = self.api_service.get_dividend_history(
                    ticker,
                    years=15,
                    normalize_splits=True,
                    since_date=since_date
                )
                
                if historical_dividends:
                    api_calls_used += 1
                    
                    # Dodaj tylko brakujące dywidendy
                    for dividend_data in historical_dividends:
                        dividend_date = dividend_data['payment_date']
                        dividend_year = dividend_date.year
                        
                        # Sprawdź czy to brakujący rok
                        if dividend_year in missing_years:
                            # Sprawdź czy już nie mamy tej dywidendy
                            existing_dividend = ETFDividend.query.filter_by(
                                etf_id=etf_id,
                                payment_date=dividend_date
                            ).first()
                            
                            if not existing_dividend:
                                dividend = ETFDividend(
                                    etf_id=etf_id,
                                    payment_date=dividend_date,
                                    ex_date=dividend_data.get('ex_date'),
                                    amount=dividend_data.get('original_amount', dividend_data['amount']),
                                    normalized_amount=dividend_data.get('normalized_amount', dividend_data['amount']),
                                    split_ratio_applied=dividend_data.get('split_ratio_applied', 1.0)
                                )
                                db.session.add(dividend)
                                dividends_filled += 1
                    
                    logger.info(f"Filled {dividends_filled} missing dividends for {ticker}")
            
            # Uzupełnianie brakujących cen tygodniowych
            if not completeness['weekly_prices_complete']:
                if completeness['missing_weekly_weeks']:
                    logger.info(f"ETF {ticker} missing {len(completeness['missing_weekly_weeks'])} weekly price weeks, attempting to fill")
                else:
                    logger.warning(f"ETF {ticker} has NO weekly price data at all - fetching full 15-year history!")
                
                # Pobierz brakujące ceny tygodniowe z API
                if completeness['missing_weekly_weeks']:
                    missing_weeks = completeness['missing_weekly_weeks']
                    oldest_missing = min(missing_weeks)
                    logger.info(f"Fetching weekly prices from {oldest_missing} for {ticker}")
                else:
                    # Brak cen tygodniowych w bazie - pobierz pełną historię
                    missing_weeks = []
                    oldest_missing = None
                    logger.info(f"ETF {ticker} has no weekly price data - fetching full 15-year history")
                
                # Pobierz ceny tygodniowe z API
                historical_weekly_prices = self.api_service.get_historical_weekly_prices(
                    ticker, 
                    years=15, 
                    normalize_splits=True
                )
                
                if historical_weekly_prices:
                    api_calls_used += 1
                    
                    # Dodaj ceny tygodniowe do bazy
                    if missing_weeks:
                        # Dodaj tylko brakujące ceny tygodniowe
                        for price_data in historical_weekly_prices:
                            price_date = price_data['date']
                            
                            # Sprawdź czy to brakujący tydzień
                            if price_date in missing_weeks:
                                # Sprawdź czy już nie mamy tej ceny tygodniowej
                                existing_price = ETFWeeklyPrice.query.filter_by(
                                    etf_id=etf_id,
                                    date=price_date
                                ).first()
                                
                                if not existing_price:
                                    price = ETFWeeklyPrice(
                                        etf_id=etf_id,
                                        date=price_date,
                                        close_price=price_data['close'],
                                        normalized_close_price=price_data.get('normalized_close', price_data['close']),
                                        split_ratio_applied=price_data.get('split_ratio_applied', 1.0),
                                        year=price_date.year,
                                        week_of_year=price_date.isocalendar()[1]
                                    )
                                    db.session.add(price)
                                    weekly_prices_filled += 1
                        
                        logger.info(f"Filled {weekly_prices_filled} missing weekly price weeks for {ticker}")
                    else:
                        # Brak cen tygodniowych w bazie - dodaj wszystkie pobrane ceny
                        for price_data in historical_weekly_prices:
                            # Sprawdź czy już nie mamy tej ceny (zabezpieczenie przed duplikatami)
                            existing_price = ETFWeeklyPrice.query.filter_by(
                                etf_id=etf_id,
                                date=price_data['date']
                            ).first()
                            
                            if not existing_price:
                                price = ETFWeeklyPrice(
                                    etf_id=etf_id,
                                    date=price_data['date'],
                                    close_price=price_data['close'],
                                    normalized_close_price=price_data.get('normalized_close', price_data['close']),
                                    split_ratio_applied=price_data.get('split_ratio_applied', 1.0),
                                    year=price_data['date'].year,
                                    week_of_year=price_data['date'].isocalendar()[1]
                                )
                                db.session.add(price)
                                weekly_prices_filled += 1
                        
                        logger.info(f"Added {weekly_prices_filled} historical weekly prices for {ticker} (no existing data)")
                    
                    # Zatwierdź zmiany w bazie
                    if weekly_prices_filled > 0:
                        db.session.commit()
                        logger.info(f"Successfully committed {weekly_prices_filled} new weekly prices to database for {ticker}")
            
            # Uzupełnianie brakujących cen dziennych
            if not daily_completeness['daily_prices_complete']:
                if daily_completeness['missing_daily_days']:
                    logger.info(f"ETF {ticker} missing {len(daily_completeness['missing_daily_days'])} daily price days, attempting to fill")
                else:
                    logger.warning(f"ETF {ticker} has NO daily price data at all - fetching full 365-day daily data!")
                
                # Pobierz brakujące ceny dzienne z API
                if daily_completeness['missing_daily_days']:
                    missing_days = daily_completeness['missing_daily_days']
                    oldest_missing = min(missing_days)
                    logger.info(f"Fetching daily prices from {oldest_missing} for {ticker}")
                else:
                    # Brak cen dziennych w bazie - pobierz pełną historię
                    missing_days = []
                    oldest_missing = None
                    logger.info(f"ETF {ticker} has no daily price data - fetching full 365-day daily data")
                
                # Pobierz ceny dzienne z API
                historical_daily_prices = self.api_service.get_historical_daily_prices(
                    ticker, 
                    days=365,  # 365 dni wstecz
                    normalize_splits=True
                )
                
                if historical_daily_prices:
                    api_calls_used += 1
                    
                    # Dodaj ceny do bazy
                    if missing_days:
                        # Dodaj tylko brakujące ceny
                        for price_data in historical_daily_prices:
                            price_date = price_data['date']
                            
                            # Sprawdź czy to brakujący dzień
                            if price_date in missing_days:
                                # Sprawdź czy już nie mamy tej ceny
                                existing_price = ETFDailyPrice.query.filter_by(
                                    etf_id=etf_id,
                                    date=price_date
                                ).first()
                                
                                if not existing_price:
                                    price = ETFDailyPrice(
                                        etf_id=etf_id,
                                        date=price_date,
                                        close_price=price_data['close'],
                                        normalized_close_price=price_data.get('normalized_close', price_data['close']),
                                        split_ratio_applied=price_data.get('split_ratio_applied', 1.0),
                                        year=price_date.year,
                                        month=price_date.month,
                                        day=price_date.day
                                    )
                                    db.session.add(price)
                                    daily_prices_filled += 1
                        
                        logger.info(f"Filled {daily_prices_filled} missing daily prices for {ticker}")
                    else:
                        # Brak cen dziennych w bazie - dodaj wszystkie pobrane ceny
                        for price_data in historical_daily_prices:
                            # Sprawdź czy już nie mamy tej ceny (zabezpieczenie przed duplikatami)
                            existing_price = ETFDailyPrice.query.filter_by(
                                etf_id=etf_id,
                                date=price_data['date']
                            ).first()
                            
                            if not existing_price:
                                # Wyciąganie roku, miesiąca i dnia z daty
                                price_date = price_data['date']
                                if isinstance(price_date, str):
                                    from datetime import datetime
                                    price_date = datetime.strptime(price_date, '%Y-%m-%d').date()
                                
                                price = ETFDailyPrice(
                                    etf_id=etf_id,
                                    date=price_date,
                                    close_price=price_data['close'],
                                    normalized_close_price=price_data.get('normalized_close', price_data['close']),
                                    split_ratio_applied=price_data.get('split_ratio_applied', 1.0),
                                    year=price_date.year,
                                    month=price_date.month,
                                    day=price_date.day
                                )
                                db.session.add(price)
                                daily_prices_filled += 1
                        
                        logger.info(f"Added {daily_prices_filled} historical daily prices for {ticker} (no existing data)")
                    
                    # Zatwierdź zmiany w bazie
                    if daily_prices_filled > 0:
                        db.session.commit()
                        logger.info(f"Successfully committed {daily_prices_filled} new daily prices to database for {ticker}")
            
            # Commit zmian
            if prices_filled > 0 or dividends_filled > 0 or weekly_prices_filled > 0 or daily_prices_filled > 0:
                db.session.commit()
                logger.info(f"Successfully filled {prices_filled} prices, {dividends_filled} dividends, {weekly_prices_filled} weekly prices, and {daily_prices_filled} daily prices for {ticker}")
            
            # Sprawdź kompletność po uzupełnieniu
            updated_completeness = self.verify_data_completeness(etf_id, ticker)
            
            return {
                'prices_filled': prices_filled,
                'dividends_filled': dividends_filled,
                'weekly_prices_filled': weekly_prices_filled,
                'daily_prices_filled': daily_prices_filled,
                'prices_complete': updated_completeness['prices_complete'],
                'dividends_complete': updated_completeness['dividends_complete'],
                'weekly_prices_complete': updated_completeness['weekly_prices_complete'],
                'daily_prices_complete': daily_completeness['daily_prices_complete'],
                'api_calls_used': api_calls_used
            }
            
        except Exception as e:
            logger.error(f"Error in smart history completion for ETF {ticker}: {str(e)}")
            db.session.rollback()
            return {
                'prices_filled': 0,
                'dividends_filled': 0,
                'weekly_prices_filled': 0,
                'daily_prices_filled': 0,
                'prices_complete': False,
                'dividends_complete': False,
                'weekly_prices_complete': False,
                'daily_prices_complete': False,
                'api_calls_used': 0
            }
    
    def update_etf_price(self, etf_id: int, new_price: float) -> bool:
        """Aktualizuje aktualną cenę ETF w tabeli ETF"""
        try:
            etf = ETF.query.get(etf_id)
            if not etf:
                logger.error(f"ETF with ID {etf_id} not found")
                return False
            
            etf.current_price = new_price
            etf.last_updated = datetime.now(timezone.utc)
            
            db.session.commit()
            logger.info(f"Updated price for ETF ID {etf_id} to ${new_price}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating price for ETF ID {etf_id}: {str(e)}")
            db.session.rollback()
            return False
    
    def add_price_history_record(self, etf_id: int, price: float) -> bool:
        """Dodaje rekord do historii cen ETF"""
        try:
            # Sprawdź czy już mamy cenę na dzisiaj
            today = date.today()
            existing_record = ETFPrice.query.filter_by(
                etf_id=etf_id,
                date=today
                ).first()
            
            if existing_record:
                # Aktualizuj istniejący rekord
                existing_record.close_price = price
                existing_record.normalized_close_price = price
                existing_record.last_updated = datetime.now(timezone.utc)
                logger.info(f"Updated existing price record for ETF ID {etf_id} on {today}")
            else:
                # Dodaj nowy rekord
                new_record = ETFPrice(
                    etf_id=etf_id,
                    date=today,
                    close_price=price,
                    normalized_close_price=price,
                    split_ratio_applied=1.0
                )
                db.session.add(new_record)
                logger.info(f"Added new price record for ETF ID {etf_id} on {today}: ${price}")
            
            db.session.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error adding price history record for ETF ID {etf_id}: {str(e)}")
            db.session.rollback()
            return False
    
    def add_daily_price_record(self, etf_id: int, price: float) -> bool:
        """Dodaje rekord do historii cen dziennych ETF (ETFDailyPrice)"""
        try:
            # Sprawdź czy już mamy cenę na dzisiaj
            today = date.today()
            existing_record = ETFDailyPrice.query.filter_by(
                etf_id=etf_id,
                date=today
            ).first()
            
            if existing_record:
                # Aktualizuj istniejący rekord
                existing_record.close_price = price
                existing_record.normalized_close_price = price
                existing_record.last_updated = datetime.now(timezone.utc)
                logger.info(f"Updated existing daily price record for ETF ID {etf_id} on {today}")
            else:
                # Dodaj nowy rekord
                new_record = ETFDailyPrice(
                    etf_id=etf_id,
                    date=today,
                    close_price=price,
                    normalized_close_price=price,
                    split_ratio_applied=1.0,
                    year=today.year,
                    month=today.month,
                    day=today.day
                )
                db.session.add(new_record)
                logger.info(f"Added new daily price record for ETF ID {etf_id} on {today}: ${price}")
            
            db.session.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error adding daily price record for ETF ID {etf_id}: {str(e)}")
            db.session.rollback()
            return False
    
    def cleanup_old_price_history(self) -> int:
        """
        UWAGA: Ta funkcja została wyłączona ze schedulera!
        Czyści TYLKO codzienne ceny aktualne (retencja 2 tygodnie)
        NIE dotyka historycznych cen miesięcznych z zadania "Aktualizacja wszystkich ETF"
        """
        try:
            cutoff_date = date.today() - timedelta(days=14)
            
            # UWAGA: NIE usuwamy historycznych cen miesięcznych!
            # Usuwamy TYLKO codzienne ceny aktualne starsze niż 2 tygodnie
            
            # Sprawdzamy czy są jakieś historyczne ceny miesięczne
            monthly_prices = ETFPrice.query.filter(
                ETFPrice.date < cutoff_date
            ).all()
            
            if monthly_prices:
                logger.warning(f"FOUND {len(monthly_prices)} historical prices older than {cutoff_date}")
                logger.warning("ABORTING cleanup to prevent data loss - historical monthly prices should be preserved!")
                return 0
            
            # Jeśli nie ma historycznych cen, możemy bezpiecznie czyścić codzienne
            deleted_count = ETFPrice.query.filter(
                ETFPrice.date < cutoff_date
            ).delete()
            
            db.session.commit()
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} daily price records (older than {cutdown_date})")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up old price history: {str(e)}")
            db.session.rollback()
            return 0
    
    def cleanup_old_system_logs(self, retention_days: int = 90) -> int:
        """
        Czyści stare logi systemowe zgodnie z polityką retencji
        Domyślnie zachowuje logi z ostatnich 90 dni
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
            
            # Usuń stare logi systemowe
            deleted_count = SystemLog.query.filter(
                SystemLog.timestamp < cutoff_date
            ).delete()
            
            db.session.commit()
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} system logs older than {retention_days} days")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error in cleanup_old_system_logs: {str(e)}")
            db.session.rollback()
            return 0
    
    def cleanup_old_job_logs(self, retention_days: int = 30) -> int:
        """
        Czyści stare logi zadań schedulera zgodnie z polityką retencji
        Domyślnie zachowuje logi zadań z ostatnich 30 dni
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
            
            # Usuń stare logi zadań
            deleted_count = SystemLog.query.filter(
                SystemLog.job_name.isnot(None),
                SystemLog.timestamp < cutoff_date
            ).delete()
            
            db.session.commit()
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} job logs older than {retention_days} days")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error in cleanup_old_job_logs: {str(e)}")
            return 0
