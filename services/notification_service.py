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
        """Sprawdza alerty cenowe"""
        try:
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
                            self._create_alert(alert, etf.ticker, message, 'warning')
                            
                    except Exception as e:
                        logger.error(f"Błąd sprawdzania alertu cenowego dla {etf.ticker}: {str(e)}")
                        
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów cenowych: {str(e)}")
    
    def check_technical_alerts(self):
        """Sprawdza alerty wskaźników technicznych"""
        try:
            technical_alerts = AlertConfig.query.filter_by(type='technical', enabled=True).all()
            
            for alert in technical_alerts:
                conditions = alert.conditions
                etfs = ETF.query.all()
                
                for etf in etfs:
                    try:
                        # Sprawdzanie wskaźników dla różnych ram czasowych
                        if self._check_technical_conditions(etf, conditions):
                            message = f"📊 Alert techniczny dla {etf.ticker}: {conditions.get('description', 'Warunek spełniony')}"
                            self._create_alert(alert, etf.ticker, message, 'info')
                            
                    except Exception as e:
                        logger.error(f"Błąd sprawdzania alertu technicznego dla {etf.ticker}: {str(e)}")
                        
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów technicznych: {str(e)}")
    
    def check_scheduler_alerts(self):
        """Sprawdza alerty schedulera"""
        try:
            scheduler_alerts = AlertConfig.query.filter_by(type='scheduler', enabled=True).all()
            
            for alert in scheduler_alerts:
                conditions = alert.conditions
                
                try:
                    if self._check_scheduler_conditions(conditions):
                        message = f"⏰ Alert schedulera: {conditions.get('description', 'Problem z zadaniem')}"
                        self._create_alert(alert, None, message, 'error')
                        
                except Exception as e:
                    logger.error(f"Błąd sprawdzania alertu schedulera: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania alertów schedulera: {str(e)}")
    
    def check_log_alerts(self):
        """Sprawdza alerty logów"""
        try:
            log_alerts = AlertConfig.query.filter_by(type='log', enabled=True).all()
            
            for alert in log_alerts:
                conditions = alert.conditions
                
                try:
                    if self._check_log_conditions(conditions):
                        message = f"📝 Alert logów: {conditions.get('description', 'Problem w logach')}"
                        self._create_alert(alert, None, message, 'critical')
                        
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
        """Tworzy nowy alert"""
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
                # Tworzenie nowego alertu
                new_alert = AlertHistory(
                    alert_config_id=alert_config.id,
                    etf_ticker=ticker,
                    message=message,
                    severity=severity,
                    priority=1,
                    status='active'
                )
                db.session.add(new_alert)
                db.session.flush()  # Aby uzyskać ID
                
                # Wysyłanie powiadomienia
                self.send_slack_notification(new_alert.id, message, severity)
            
            db.session.commit()
            logger.info(f"Alert utworzony: {message}")
            
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
