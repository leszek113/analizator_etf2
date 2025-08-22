from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from sqlalchemy.exc import IntegrityError
import logging
from models import db, ETF, ETFPrice, ETFDividend, ETFSplit, SystemLog, DividendTaxRate
from services.api_service import APIService

logger = logging.getLogger(__name__)

class DatabaseService:
    def __init__(self, api_service: APIService = None):
        self.api_service = api_service or APIService()
    
    def add_etf(self, ticker: str) -> Optional[ETF]:
        """
        Dodaje nowy ETF do bazy danych wraz z historią
        """
        try:
            # Sprawdzenie czy ETF już istnieje
            existing_etf = ETF.query.filter_by(ticker=ticker.upper()).first()
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
            
            # Tworzenie nowego ETF
            new_etf = ETF(
                ticker=ticker.upper(),
                name=name,
                current_price=current_price,
                current_yield=current_yield,
                frequency=frequency,
                last_updated=datetime.utcnow()
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
            
            # Pobieranie aktualnych danych (FMP jako główne źródło)
            etf_data = self.api_service.get_etf_data(ticker)
            if not etf_data:
                logger.error(f"Could not fetch updated data for ETF {ticker}")
                return False
            
            # Sprawdzenie czy mamy cenę do aktualizacji
            current_price = etf_data.get('current_price')
            if not current_price:
                current_price = etf_data.get('eodhd_current_price')
                if not current_price:
                    current_price = etf_data.get('tiingo_current_price')
                
            if not current_price:
                logger.error(f"No price data available for ETF {ticker} update")
                return False
            
            # Aktualizacja danych
            etf.name = etf_data.get('name', etf.name)
            etf.current_price = current_price
            etf.current_yield = etf_data.get('current_yield', etf.current_yield)
            etf.frequency = etf_data.get('frequency', etf.frequency)
            etf.last_updated = datetime.utcnow()
            
            # Sprawdzanie nowych dywidend
            new_dividends = self._check_new_dividends(etf.id, ticker)
            
            # Sprawdzanie nowych cen
            new_prices = self._check_new_prices(etf.id, ticker)
            
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
        """Pobiera ceny miesięczne ETF z bazy danych - jedna cena na miesiąc"""
        try:
            # Pobieranie cen miesięcznych, grupowane po roku i miesiącu
            # Używamy raw SQL dla lepszej kontroli nad grupowaniem
            from sqlalchemy import text
            from datetime import datetime
            
            query = text("""
                SELECT 
                    id, etf_id, date, close_price, normalized_close_price, split_ratio_applied
                FROM etf_prices 
                WHERE etf_id = :etf_id 
                AND date IN (
                    SELECT MAX(date) 
                    FROM etf_prices 
                    WHERE etf_id = :etf_id 
                    GROUP BY strftime('%Y-%m', date)
                )
                ORDER BY date ASC
            """)
            
            result = db.session.execute(query, {'etf_id': etf_id})
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
            
            logger.info(f"Retrieved {len(prices)} monthly prices (one per month) for ETF ID {etf_id}")
            return prices
            
        except Exception as e:
            logger.error(f"Error getting monthly prices for ETF ID {etf_id}: {str(e)}")
            return []

    def _add_historical_prices(self, etf_id: int, ticker: str) -> None:
        """
        Dodaje historyczne ceny ETF - używa danych z cache jeśli dostępne
        """
        try:
            # Próba użycia danych z cache (jeśli były pobrane przez get_etf_data)
            cached_data = self.api_service.cache.get(f"etf_data_{ticker}")
            prices_data = []
            
            # Debug logging
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
            
        except Exception as e:
            logger.error(f"Error adding historical prices for ETF {ticker}: {str(e)}")
    
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
            
            # Debug logging - sprawdzenie struktury danych
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
                        logger.debug(f"Added dividend for {ticker} on {dividend_data['payment_date']}: {dividend_data['original_amount']}")
                    else:
                        logger.debug(f"Dividend for {ticker} on {dividend_data['payment_date']} already exists")
                        
                except Exception as e:
                    logger.error(f"Error adding dividend for {ticker} on {dividend_data['payment_date']}: {str(e)}")
                    continue
            
            logger.info(f"Added {added_count} historical dividends for ETF {ticker}")
            return added_count > 0
            
        except Exception as e:
            logger.error(f"Error fetching historical dividends for ETF {ticker}: {str(e)}")
            return False
    
    def _check_new_prices(self, etf_id: int, ticker: str) -> bool:
        """
        Sprawdza czy są nowe ceny do dodania - OSZCZĘDZA TOKENY API
        """
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
            days_since_last = (today - last_db_price.date).days
            if days_since_last < 7:
                logger.info(f"Last price for {ticker} is recent ({days_since_last} days ago), no need to check API")
                return False
            
            logger.info(f"Checking for new price for {ticker} (last price: {last_db_price.date})")
            
            # Pobieranie aktualnej ceny (FMP jako główne źródło)
            current_price_data = self.api_service.get_etf_data(ticker)
            if not current_price_data:
                return False
                
            # Sprawdzenie czy mamy cenę
            current_price = current_price_data.get('current_price')
            if not current_price:
                current_price = current_price_data.get('eodhd_current_price')
                if not current_price:
                    current_price = current_price_data.get('tiingo_current_price')
                
            if not current_price:
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
            
            # Debug logging - sprawdzenie struktury danych
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
                        logger.debug(f"Added price for {ticker} on {price_data['date']}: {price_data['original_close']}")
                    else:
                        logger.debug(f"Price for {ticker} on {price_data['date']} already exists")
                        
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
                days_since_check = (datetime.utcnow() - last_split_check).days
                
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
            
            # Aktualizacja cen
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
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            deleted = SystemLog.query.filter(SystemLog.timestamp < cutoff_date).delete()
            db.session.commit()
            
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old system logs")
                self._log_action('CLEANUP', f"Removed {deleted} old system logs")
                
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
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
            etf.last_updated = datetime.utcnow()
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
