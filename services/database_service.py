from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from sqlalchemy.exc import IntegrityError
import logging
from models import db, ETF, ETFPrice, ETFDividend, SystemLog
from services.api_service import APIService

logger = logging.getLogger(__name__)

class DatabaseService:
    def __init__(self):
        self.api_service = APIService()
    
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
    
    def update_etf_data(self, ticker: str) -> bool:
        """
        Aktualizuje dane istniejącego ETF
        """
        try:
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
            
            db.session.commit()
            
            if new_dividends or new_prices:
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
    
    def _add_historical_prices(self, etf_id: int, ticker: str) -> None:
        """
        Dodaje historyczne ceny ETF
        """
        try:
            prices_data = self.api_service.get_historical_prices(ticker)
            
            for price_data in prices_data:
                price = ETFPrice(
                    etf_id=etf_id,
                    date=price_data['date'],
                    close_price=price_data['close_price'],
                    open_price=price_data['open_price'],
                    high_price=price_data['high_price'],
                    low_price=price_data['low_price'],
                    volume=price_data['volume']
                )
                db.session.add(price)
            
            logger.info(f"Added {len(prices_data)} historical prices for ETF {ticker}")
            
        except Exception as e:
            logger.error(f"Error adding historical prices for ETF {ticker}: {str(e)}")
    
    def _add_historical_dividends(self, etf_id: int, ticker: str) -> None:
        """
        Dodaje historyczne dywidendy ETF
        """
        try:
            dividends_data = self.api_service.get_dividend_history(ticker)
            
            for dividend_data in dividends_data:
                dividend = ETFDividend(
                    etf_id=etf_id,
                    payment_date=dividend_data['payment_date'],
                    ex_date=dividend_data['ex_date'],
                    amount=dividend_data['amount']
                )
                db.session.add(dividend)
            
            logger.info(f"Added {len(dividends_data)} historical dividends for ETF {ticker}")
            
        except Exception as e:
            logger.error(f"Error adding historical dividends for ETF {ticker}: {str(e)}")
    
    def _check_new_dividends(self, etf_id: int, ticker: str) -> bool:
        """
        Sprawdza czy są nowe dywidendy do dodania
        """
        try:
            # Pobieranie wszystkich dostępnych dywidend z FMP API (15 lat)
            current_dividends = self.api_service.get_dividend_history(ticker, years=15)
            
            if not current_dividends:
                logger.warning(f"No dividends returned from API for {ticker}")
                return False
            
            # Pobieranie istniejących dywidend z bazy
            existing_dividends = ETFDividend.query.filter_by(etf_id=etf_id).all()
            existing_dates = {div.payment_date for div in existing_dividends}
            
            logger.info(f"ETF {ticker}: {len(current_dividends)} from API, {len(existing_dividends)} in database")
            
            # Sprawdzanie nowych dywidend
            new_dividends = []
            for dividend_data in current_dividends:
                if dividend_data['payment_date'] not in existing_dates:
                    new_dividends.append(dividend_data)
            
            # Dodawanie nowych dywidend
            for dividend_data in new_dividends:
                dividend = ETFDividend(
                    etf_id=etf_id,
                    payment_date=dividend_data['payment_date'],
                    ex_date=dividend_data['ex_date'],
                    amount=dividend_data['amount']
                )
                db.session.add(dividend)
            
            if new_dividends:
                logger.info(f"Added {len(new_dividends)} new dividends for ETF {ticker}")
                return True
            else:
                logger.info(f"No new dividends for ETF {ticker}")
                return False
            
        except Exception as e:
            logger.error(f"Error checking new dividends for ETF {ticker}: {str(e)}")
            return False
    
    def _check_new_prices(self, etf_id: int, ticker: str) -> bool:
        """
        Sprawdza czy są nowe ceny do dodania
        """
        try:
            # Pobieranie ostatniej ceny z bazy
            last_db_price = ETFPrice.query.filter_by(etf_id=etf_id).order_by(ETFPrice.date.desc()).first()
            
            if not last_db_price:
                return False
            
            # Sprawdzanie czy ostatnia cena jest z dzisiejszego dnia
            today = date.today()
            if last_db_price.date >= today:
                return False
            
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
                open_price=current_price,  # Uproszczenie
                high_price=current_price,
                low_price=current_price,
                volume=0  # Brak danych o wolumenie
            )
            db.session.add(new_price)
            
            logger.info(f"Added new price for ETF {ticker}: {current_price}")
            return True
            
        except Exception as e:
            logger.error(f"Error checking new prices for ETF {ticker}: {str(e)}")
            return False
    
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
