import logging
import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from models import db, AlertConfig, AlertHistory, Notification, ETF
from services.api_service import APIService
from services.database_service import DatabaseService

logger = logging.getLogger(__name__)

class NotificationService:
    """Serwis do zarządzania powiadomieniami i alertami"""
    
    def __init__(self, config):
        self.config = config
        self.api_service = APIService()
        self.db_service = DatabaseService()
        
    def send_slack_notification(self, alert_id: int, message: str, severity: str):
        """Wysyła powiadomienie na Slack"""
        try:
            if not self.config.SLACK_WEBHOOK_URL:
                logger.warning("Brak konfiguracji Slack webhook")
                return
            
            # Kolor wiadomości na podstawie severity
            color_map = {
                'info': '#36a64f',      # Zielony
                'warning': '#ff8c00',   # Pomarańczowy
                'error': '#ff0000',     # Czerwony
                'critical': '#8b0000'   # Ciemny czerwony
            }
            color = color_map.get(severity, '#36a64f')
            
            # Przygotowanie wiadomości Slack
            slack_message = {
                "channel": self.config.SLACK_CHANNEL,
                "username": self.config.SLACK_USERNAME,
                "attachments": [
                    {
                        "color": color,
                        "title": f"ETF Analyzer Alert - {severity.upper()}",
                        "text": message,
                        "fields": [
                            {
                                "title": "Severity",
                                "value": severity.upper(),
                                "short": True
                            },
                            {
                                "title": "Time",
                                "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "short": True
                            }
                        ],
                        "footer": "ETF Analyzer v1.9.20",
                        "ts": int(datetime.now().timestamp())
                    }
                ]
            }
            
            # Wysyłanie na Slack
            response = requests.post(
                self.config.SLACK_WEBHOOK_URL,
                json=slack_message,
                timeout=10
            )
            
            if response.status_code == 200:
                # Zapisanie powiadomienia
                notification = Notification(
                    alert_id=alert_id,
                    channel='slack',
                    status='sent'
                )
                db.session.add(notification)
                db.session.commit()
                
                logger.info(f"Powiadomienie Slack wysłane: {message}")
            else:
                logger.error(f"Błąd wysyłania na Slack: {response.status_code} - {response.text}")
                
                # Zapisanie błędu
                notification = Notification(
                    alert_id=alert_id,
                    channel='slack',
                    status='failed',
                    error_message=f"HTTP {response.status_code}: {response.text}"
                )
                db.session.add(notification)
                db.session.commit()
                
        except Exception as e:
            logger.error(f"Błąd wysyłania powiadomienia Slack: {str(e)}")
            
            # Zapisanie błędu
            try:
                notification = Notification(
                    alert_id=alert_id,
                    channel='slack',
                    status='failed',
                    error_message=str(e)
                )
                db.session.add(notification)
                db.session.commit()
            except:
                pass
        
    def check_all_alerts(self):
        """Sprawdza wszystkie typy alertów"""
        try:
            logger.info("Rozpoczynam sprawdzanie wszystkich alertów...")
            
            # Sprawdzanie alertów cenowych (co 10 minut)
            self.check_price_alerts()
            
            # Sprawdzanie alertów wskaźników (raz dziennie o 10:30 CET)
            current_time = datetime.now()
            if current_time.hour == 10 and current_time.minute >= 30 and current_time.minute < 40:
                self.check_technical_alerts()
            
            # Sprawdzanie alertów schedulera (co 10 minut)
            self.check_scheduler_alerts()
            
            # Sprawdzanie alertów logów (co 10 minut)
            self.check_log_alerts()
            
            logger.info("Sprawdzanie alertów zakończone")
            
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów: {str(e)}")
    
    def check_price_alerts(self):
        """Sprawdza alerty cenowe (wysyła natychmiast w godzinach 9:00-21:00 CET)"""
        try:
            # Sprawdź czy jest w godzinach 9:00-21:00 CET
            current_time = datetime.now()
            current_hour = current_time.hour
            
            # 9:00-21:00 CET = 8:00-20:00 UTC (zimą) lub 7:00-19:00 UTC (latem)
            # Używamy UTC wewnętrznie, więc sprawdzamy 8:00-20:00 UTC
            if not (8 <= current_hour <= 20):
                logger.info("Poza godzinami alertów cenowych (9:00-21:00 CET), pomijam sprawdzanie")
                return
            
            price_alerts = AlertConfig.query.filter_by(type='price', enabled=True).all()
            
            for alert in price_alerts:
                conditions = alert.conditions
                etfs = ETF.query.all()
                
                for etf in etfs:
                    try:
                        # Pobieranie aktualnej ceny
                        current_price = self.api_service.get_current_price(etf.ticker)
                        if not current_price:
                            continue
                        
                        # Sprawdzanie warunków
                        if self._check_price_conditions(current_price, conditions):
                            message = f"🚨 Alert cenowy dla {etf.ticker}: ${current_price:.2f}"
                            # Dla alertów cenowych wysyłamy natychmiast
                            self._create_price_alert(alert, etf.ticker, message, 'warning')
                            
                    except Exception as e:
                        logger.error(f"Błąd sprawdzania alertu cenowego dla {etf.ticker}: {str(e)}")
                        
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów cenowych: {str(e)}")
    
    def check_technical_alerts(self):
        """Sprawdza alerty wskaźników technicznych"""
        try:
            logger.info("Sprawdzam alerty wskaźników technicznych...")
            
            # Pobierz wszystkie aktywne alerty techniczne
            technical_alerts = AlertConfig.query.filter_by(
                type='technical_indicator', 
                enabled=True
            ).all()
            
            for alert in technical_alerts:
                if alert.indicator == 'stochastic':
                    self._check_stochastic_alerts(alert)
                elif alert.indicator == 'macd':
                    self._check_macd_alerts(alert)
            
            logger.info(f"Sprawdzono {len(technical_alerts)} alertów technicznych")
            
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów technicznych: {str(e)}")
    
    def check_scheduler_alerts(self):
        """Sprawdza alerty schedulera (wysyła natychmiast w godzinach 9:00-21:00 CET)"""
        try:
            # Sprawdź czy jest w godzinach 9:00-21:00 CET
            current_time = datetime.now()
            current_hour = current_time.hour
            
            # 9:00-21:00 CET = 8:00-20:00 UTC (zimą) lub 7:00-19:00 UTC (latem)
            # Używamy UTC wewnętrznie, więc sprawdzamy 8:00-20:00 UTC
            if not (8 <= current_hour <= 20):
                logger.info("Poza godzinami alertów schedulera (9:00-21:00 CET), pomijam sprawdzanie")
                return
            
            scheduler_alerts = AlertConfig.query.filter_by(type='scheduler', enabled=True).all()
            
            for alert in scheduler_alerts:
                conditions = alert.conditions
                
                try:
                    if self._check_scheduler_conditions(conditions):
                        message = f"⏰ Alert schedulera: {conditions.get('description', 'Problem z zadaniem')}"
                        # Dla alertów schedulera wysyłamy natychmiast
                        self._create_immediate_alert(alert, None, message, 'error')
                        
                except Exception as e:
                    logger.error(f"Błąd sprawdzania alertu schedulera: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów schedulera: {str(e)}")
    
    def check_log_alerts(self):
        """Sprawdza alerty logów (wysyła natychmiast w godzinach 9:00-21:00 CET)"""
        try:
            # Sprawdź czy jest w godzinach 9:00-21:00 CET
            current_time = datetime.now()
            current_hour = current_time.hour
            
            # 9:00-21:00 CET = 8:00-20:00 UTC (zimą) lub 7:00-19:00 UTC (latem)
            # Używamy UTC wewnętrznie, więc sprawdzamy 8:00-20:00 UTC
            if not (8 <= current_hour <= 20):
                logger.info("Poza godzinami alertów logów (9:00-21:00 CET), pomijam sprawdzanie")
                return
            
            log_alerts = AlertConfig.query.filter_by(type='log', enabled=True).all()
            
            for alert in log_alerts:
                conditions = alert.conditions
                
                try:
                    if self._check_log_conditions(conditions):
                        message = f"📝 Alert logów: {conditions.get('description', 'Problem w logach')}"
                        # Dla alertów logów wysyłamy natychmiast
                        self._create_immediate_alert(alert, None, message, 'critical')
                        
                except Exception as e:
                    logger.error(f"Błąd sprawdzania alertu logów: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów logów: {str(e)}")
    
    def _check_price_conditions(self, price: float, conditions: Dict) -> bool:
        """Sprawdza warunki cenowe"""
        try:
            min_price = conditions.get('min_price')
            max_price = conditions.get('max_price')
            change_percent = conditions.get('change_percent')
            
            # Sprawdzanie zakresu cen
            if min_price and price < min_price:
                return True
            if max_price and price > max_price:
                return True
            
            # Sprawdzanie zmiany procentowej (do implementacji)
            if change_percent:
                # TODO: Implementacja sprawdzania zmiany procentowej
                pass
                
            return False
            
        except Exception as e:
            logger.error(f"Błąd sprawdzania warunków cenowych: {str(e)}")
            return False
    
    def _check_stochastic_alerts(self, alert):
        """Sprawdza alerty dla wskaźnika Stochastic"""
        try:
            etf = ETF.query.filter_by(ticker=alert.etf_ticker).first()
            if not etf:
                logger.warning(f"ETF {alert.etf_ticker} nie znaleziony")
                return
            
            # Pobierz dane cenowe dla obliczenia wskaźnika
            timeframe = alert.conditions.get('timeframe', '1D')
            prices = self._get_prices_for_timeframe(etf, timeframe)
            
            if not prices or len(prices) < 50:  # Minimum dla obliczenia wskaźnika
                logger.warning(f"Za mało danych dla {etf.ticker} {timeframe}")
                return
            
            # Oblicz wskaźnik Stochastic
            k_values, d_values = self._calculate_stochastic(prices, 
                alert.conditions.get('parameters', {}))
            
            if not k_values or not d_values:
                return
            
            # Sprawdź warunki alertu
            if alert.alert_type == 'level_below':
                threshold = alert.conditions.get('threshold', 20.0)
                if k_values[-1] < threshold:
                    message = f"Stochastic {etf.ticker} {timeframe}: K={k_values[-1]:.2f} < {threshold}"
                    self._create_alert(alert, etf.ticker, message, 'warning')
            
            elif alert.alert_type == 'level_above':
                threshold = alert.conditions.get('threshold', 80.0)
                if k_values[-1] > threshold:
                    message = f"Stochastic {etf.ticker} {timeframe}: K={k_values[-1]:.2f} > {threshold}"
                    self._create_alert(alert, etf.ticker, message, 'warning')
            
            elif alert.alert_type == 'crossover_in_oversold':
                if k_values[-1] < 20 and k_values[-1] > d_values[-1] and k_values[-2] <= d_values[-2]:
                    message = f"Stochastic {etf.ticker} {timeframe}: Przecięcie bullish w oversold (K={k_values[-1]:.2f}, D={d_values[-1]:.2f})"
                    self._create_alert(alert, etf.ticker, message, 'info')
            
            elif alert.alert_type == 'crossover_in_overbought':
                if k_values[-1] > 80 and k_values[-1] < d_values[-1] and k_values[-2] >= d_values[-2]:
                    message = f"Stochastic {etf.ticker} {timeframe}: Przecięcie bearish w overbought (K={k_values[-1]:.2f}, D={d_values[-1]:.2f})"
                    self._create_alert(alert, etf.ticker, message, 'info')
            
            elif alert.alert_type == 'crossover_general':
                if (k_values[-1] > d_values[-1] and k_values[-2] <= d_values[-2]) or \
                   (k_values[-1] < d_values[-1] and k_values[-2] >= d_values[-2]):
                    direction = "bullish" if k_values[-1] > d_values[-1] else "bearish"
                    message = f"Stochastic {etf.ticker} {timeframe}: Przecięcie {direction} (K={k_values[-1]:.2f}, D={d_values[-1]:.2f})"
                    self._create_alert(alert, etf.ticker, message, 'info')
        
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów Stochastic: {str(e)}")
    
    def _check_macd_alerts(self, alert):
        """Sprawdza alerty dla wskaźnika MACD"""
        try:
            etf = ETF.query.filter_by(ticker=alert.etf_ticker).first()
            if not etf:
                logger.warning(f"ETF {alert.etf_ticker} nie znaleziony")
                return
            
            # Pobierz dane cenowe dla obliczenia wskaźnika
            timeframe = alert.conditions.get('timeframe', '1D')
            prices = self._get_prices_for_timeframe(etf, timeframe)
            
            if not prices or len(prices) < 50:
                logger.warning(f"Za mało danych dla {etf.ticker} {timeframe}")
                return
            
            # Oblicz wskaźnik MACD
            macd_line, signal_line = self._calculate_macd(prices, 
                alert.conditions.get('parameters', {}))
            
            if not macd_line or not signal_line:
                return
            
            # Sprawdź warunki alertu
            if alert.alert_type == 'crossover_bullish':
                if macd_line[-1] > signal_line[-1] and macd_line[-2] <= signal_line[-2]:
                    message = f"MACD {etf.ticker} {timeframe}: Przecięcie bullish (MACD={macd_line[-1]:.4f}, Signal={signal_line[-1]:.4f})"
                    self._create_alert(alert, etf.ticker, message, 'info')
            
            elif alert.alert_type == 'crossover_bearish':
                if macd_line[-1] < signal_line[-1] and macd_line[-2] >= signal_line[-2]:
                    message = f"MACD {etf.ticker} {timeframe}: Przecięcie bearish (MACD={macD_line[-1]:.4f}, Signal={signal_line[-1]:.4f})"
                    self._create_alert(alert, etf.ticker, message, 'info')
        
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów MACD: {str(e)}")
    
    def _calculate_stochastic(self, prices, parameters):
        """Oblicza wskaźnik Stochastic"""
        try:
            k_period = parameters.get('k', 14)
            d_period = parameters.get('d', 3)
            smooth = parameters.get('smooth', 3)
            
            # Implementacja obliczania Stochastic
            # To jest uproszczona wersja - w rzeczywistości potrzebujemy pełnej implementacji
            close_prices = [p['close'] for p in prices]
            high_prices = [p['high'] for p in prices]
            low_prices = [p['low'] for p in prices]
            
            # Oblicz %K
            k_values = []
            for i in range(k_period - 1, len(close_prices)):
                highest_high = max(high_prices[i-k_period+1:i+1])
                lowest_low = min(low_prices[i-k_period+1:i+1])
                if highest_high != lowest_low:
                    k = ((close_prices[i] - lowest_low) / (highest_high - lowest_low)) * 100
                else:
                    k = 50
                k_values.append(k)
            
            # Oblicz %D (SMA z %K)
            d_values = []
            for i in range(d_period - 1, len(k_values)):
                d = sum(k_values[i-d_period+1:i+1]) / d_period
                d_values.append(d)
            
            return k_values, d_values
        
        except Exception as e:
            logger.error(f"Błąd obliczania Stochastic: {str(e)}")
            return None, None
    
    def _calculate_macd(self, prices, parameters):
        """Oblicza wskaźnik MACD"""
        try:
            fast_period = parameters.get('fast', 12)
            slow_period = parameters.get('slow', 26)
            signal_period = parameters.get('signal', 9)
            
            # Implementacja obliczania MACD
            # To jest uproszczona wersja - w rzeczywistości potrzebujemy pełnej implementacji
            close_prices = [p['close'] for p in prices]
            
            # Oblicz EMA
            def ema(data, period):
                ema_values = []
                multiplier = 2 / (period + 1)
                ema_values.append(data[0])
                for i in range(1, len(data)):
                    ema = (data[i] * multiplier) + (ema_values[-1] * (1 - multiplier))
                    ema_values.append(ema)
                for i in range(1, len(data)):
                    ema = (data[i] * multiplier) + (ema_values[-1] * (1 - multiplier))
                    ema_values.append(ema)
                return ema_values
            
            fast_ema = ema(close_prices, fast_period)
            slow_ema = ema(ema_values, slow_period)
            
            # Oblicz MACD line
            macd_line = [fast_ema[i] - slow_ema[i] for i in range(len(fast_ema))]
            
            # Oblicz Signal line (EMA z MACD)
            signal_line = ema(macd_line, signal_period)
            
            return macd_line, signal_line
        
        except Exception as e:
            logger.error(f"Błąd obliczania MACD: {str(e)}")
            return None, None
    
    def _get_prices_for_timeframe(self, etf, timeframe):
        """Pobiera ceny dla określonej ramy czasowej"""
        try:
            if timeframe == '1D':
                return self.db_service.get_daily_prices(etf.id, limit=100)
            elif timeframe == '1W':
                return self.db_service.get_weekly_prices(etf.id, limit=100)
            elif timeframe == '1M':
                return self.db_service.get_monthly_prices(etf.id, limit=100)
            else:
                return self.db_service.get_daily_prices(etf.id, limit=100)
        
        except Exception as e:
            logger.error(f"Błąd pobierania cen dla {timeframe}: {str(e)}")
            return None
    
    def _check_technical_conditions(self, etf: ETF, conditions: Dict) -> bool:
        """Sprawdza warunki wskaźników technicznych"""
        try:
            indicator = conditions.get('indicator')
            timeframe = conditions.get('timeframe', '1M')
            threshold = conditions.get('threshold')
            operator = conditions.get('operator', '>')
            
            if not indicator or not threshold:
                return False
            
            # Pobieranie danych wskaźników (do implementacji)
            # TODO: Implementacja sprawdzania MACD, Stochastic, RSI
            
            return False
            
        except Exception as e:
            logger.error(f"Błąd sprawdzania warunków technicznych: {str(e)}")
            return False
    
    def _check_scheduler_conditions(self, conditions: Dict) -> bool:
        """Sprawdza warunki schedulera"""
        try:
            job_name = conditions.get('job_name')
            max_delay_minutes = conditions.get('max_delay_minutes', 30)
            
            if not job_name:
                return False
            
            # Sprawdzanie czy zadanie zostało wykonane w określonym czasie
            # TODO: Implementacja sprawdzania ostatniego wykonania zadania
            
            return False
            
        except Exception as e:
            logger.error(f"Błąd sprawdzania warunków schedulera: {str(e)}")
            return False
    
    def _check_log_conditions(self, conditions: Dict) -> bool:
        """Sprawdza warunki logów"""
        try:
            error_pattern = conditions.get('error_pattern')
            severity = conditions.get('severity', 'ERROR')
            
            if not error_pattern:
                return False
            
            # Sprawdzanie logów (do implementacji)
            # TODO: Implementacja sprawdzania logów pod kątem błędów
            
            return False
            
        except Exception as e:
            logger.error(f"Błąd sprawdzania warunków logów: {str(e)}")
            return False
    
    def _create_alert(self, alert_config: AlertConfig, ticker: Optional[str], message: str, severity: str):
        """Tworzy nowy alert (bez wysyłania powiadomienia - czeka na 10:00 CET)"""
        try:
            # Sprawdzanie czy alert już istnieje
            existing_alert = AlertHistory.query.filter_by(
                alert_config_id=alert_config.id,
                etf_ticker=ticker,
                status='active'
            ).first()
            
            if existing_alert:
                # Aktualizacja istniejącego alertu
                existing_alert.message = message
                existing_alert.severity = severity
                existing_alert.triggered_at = datetime.utcnow()
            else:
                # Tworzenie nowego alertu (bez wysyłania powiadomienia)
                new_alert = AlertHistory(
                    alert_config_id=alert_config.id,
                    etf_ticker=ticker,
                    message=message,
                    severity=severity,
                    priority=1,
                    status='active'
                )
                db.session.add(new_alert)
                # NIE WYSYŁAMY powiadomienia - czeka na 10:00 CET
            
            db.session.commit()
            logger.info(f"Alert utworzony (oczekuje na powiadomienie): {message}")
            
        except Exception as e:
            logger.error(f"Błąd tworzenia alertu: {str(e)}")
            db.session.rollback()

    def _create_price_alert(self, alert_config: AlertConfig, ticker: Optional[str], message: str, severity: str):
        """Tworzy alert cenowy i wysyła powiadomienie natychmiast"""
        try:
            # Sprawdzanie czy alert już istnieje
            existing_alert = AlertHistory.query.filter_by(
                alert_config_id=alert_config.id,
                etf_ticker=ticker,
                status='active'
            ).first()
            
            if existing_alert:
                # Aktualizacja istniejącego alertu
                existing_alert.message = message
                existing_alert.severity = severity
                existing_alert.triggered_at = datetime.utcnow()
                existing_alert.status = 'notified'
                existing_alert.notified_at = datetime.utcnow()
            else:
                # Tworzenie nowego alertu
                new_alert = AlertHistory(
                    alert_config_id=alert_config.id,
                    etf_ticker=ticker,
                    message=message,
                    severity=severity,
                    priority=1,
                    status='notified'
                )
                db.session.add(new_alert)
                db.session.flush()  # Aby uzyskać ID
                
                # Wysyłanie powiadomienia natychmiast
                self.send_slack_notification(new_alert.id, message, severity)
                
                # Oznaczenie jako wysłane
                new_alert.notified_at = datetime.utcnow()
            
            db.session.commit()
            logger.info(f"Alert cenowy utworzony i powiadomienie wysłane: {message}")
            
        except Exception as e:
            logger.error(f"Błąd tworzenia alertu cenowego: {str(e)}")
            db.session.rollback()

    def _create_immediate_alert(self, alert_config: AlertConfig, ticker: Optional[str], message: str, severity: str):
        """Tworzy alert i wysyła powiadomienie natychmiast (dla logów i schedulera)"""
        try:
            # Sprawdzanie czy alert już istnieje
            existing_alert = AlertHistory.query.filter_by(
                alert_config_id=alert_config.id,
                etf_ticker=ticker,
                status='active'
            ).first()
            
            if existing_alert:
                # Aktualizacja istniejącego alertu
                existing_alert.message = message
                existing_alert.severity = severity
                existing_alert.triggered_at = datetime.utcnow()
                existing_alert.status = 'notified'
                existing_alert.notified_at = datetime.utcnow()
            else:
                # Tworzenie nowego alertu
                new_alert = AlertHistory(
                    alert_config_id=alert_config.id,
                    etf_ticker=ticker,
                    message=message,
                    severity=severity,
                    priority=1,
                    status='notified'
                )
                db.session.add(new_alert)
                db.session.flush()  # Aby uzyskać ID
                
                # Wysyłanie powiadomienia natychmiast
                self.send_slack_notification(new_alert.id, message, severity)
                
                # Oznaczenie jako wysłane
                new_alert.notified_at = datetime.utcnow()
            
            db.session.commit()
            logger.info(f"Alert utworzony i powiadomienie wysłane: {message}")
            
        except Exception as e:
            logger.error(f"Błąd tworzenia alertu: {str(e)}")
            db.session.rollback()
    
    
    def get_active_alerts(self, limit: int = 50) -> List[Dict]:
        """Pobiera aktywne alerty"""
        try:
            alerts = AlertHistory.query.filter_by(status='active').order_by(
                AlertHistory.triggered_at.desc()
            ).limit(limit).all()
            
            return [
                {
                    'id': alert.id,
                    'name': alert.alert_config.name,
                    'type': alert.alert_config.type,
                    'ticker': alert.etf_ticker,
                    'message': alert.message,
                    'severity': alert.severity,
                    'priority': alert.priority,
                    'triggered_at': alert.triggered_at.isoformat(),
                    'status': alert.status
                }
                for alert in alerts
            ]
            
        except Exception as e:
            logger.error(f"Błąd pobierania aktywnych alertów: {str(e)}")
            return []
    
    def resolve_alert(self, alert_id: int):
        """Oznacza alert jako rozwiązany"""
        try:
            alert = AlertHistory.query.get(alert_id)
            if alert:
                alert.status = 'resolved'
                alert.resolved_at = datetime.utcnow()
                db.session.commit()
                logger.info(f"Alert {alert_id} oznaczony jako rozwiązany")
                
        except Exception as e:
            logger.error(f"Błąd rozwiązywania alertu {alert_id}: {str(e)}")
            db.session.rollback()

    def send_pending_technical_notifications(self):
        """Wysyła oczekujące powiadomienia wskaźników technicznych o 10:00 CET"""
        try:
            logger.info("Wysyłam oczekujące powiadomienia wskaźników technicznych...")
            
            # Pobieranie wszystkich aktywnych alertów wskaźników technicznych
            technical_alerts = AlertHistory.query.join(AlertConfig).filter(
                AlertHistory.status == 'active',
                AlertConfig.type == 'technical_indicator'
            ).all()
            
            if not technical_alerts:
                logger.info("Brak oczekujących powiadomień wskaźników technicznych")
                return
            
            # Grupowanie alertów według typu wskaźnika i ETF
            alerts_by_etf = {}
            for alert in technical_alerts:
                ticker = alert.etf_ticker or 'Unknown'
                if ticker not in alerts_by_etf:
                    alerts_by_etf[ticker] = []
                alerts_by_etf[ticker].append(alert)
            
            # Wysyłanie powiadomień grupowych
            for ticker, alerts in alerts_by_etf.items():
                if len(alerts) == 1:
                    # Pojedynczy alert - wysyłanie bezpośrednio
                    alert = alerts[0]
                    self.send_slack_notification(alert.id, alert.message, alert.severity)
                else:
                    # Wiele alertów - wysyłanie zbiorcze
                    message = f"📊 **{ticker}** - Wykryto {len(alerts)} alertów wskaźników technicznych:\n\n"
                    for alert in alerts:
                        message += f"• {alert.message}\n"
                    
                    # Wysyłanie zbiorczego powiadomienia
                    self.send_slack_notification(alerts[0].id, message, 'info')
                    
                    # Oznaczenie wszystkich jako wysłane
                    for alert in alerts:
                        alert.status = 'notified'
                        alert.notified_at = datetime.utcnow()
                    
                    db.session.commit()
            
            logger.info(f"Wysłano powiadomienia dla {len(technical_alerts)} alertów wskaźników technicznych")
            
        except Exception as e:
            logger.error(f"Błąd podczas wysyłania powiadomień wskaźników: {str(e)}")
            db.session.rollback()
