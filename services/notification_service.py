import logging
import requests
import json
from datetime import datetime, timedelta, timezone
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

    def check_alerts(self):
        """Sprawdza wszystkie aktywne alerty i wysyła powiadomienia"""
        try:
            # Pobieranie wszystkich aktywnych konfiguracji alertów
            alert_configs = AlertConfig.query.filter_by(enabled=True).all()
            
            for alert_config in alert_configs:
                try:
                    self._check_single_alert(alert_config)
                except Exception as e:
                    logger.error(f"Błąd sprawdzania alertu {alert_config.id}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Błąd sprawdzania alertów: {str(e)}")

    def _check_single_alert(self, alert_config: AlertConfig):
        """Sprawdza pojedynczy alert"""
        alert_type = alert_config.alert_type
        
        if alert_type == 'price_change':
            self._check_price_change_alert(alert_config)
        elif alert_type == 'dividend_change':
            self._check_dividend_change_alert(alert_config)
        elif alert_type == 'technical_indicator':
            self._check_technical_indicator_alert(alert_config)
        elif alert_type == 'scheduler_status':
            self._check_scheduler_status_alert(alert_config)
        elif alert_type == 'log_errors':
            self._check_log_errors_alert(alert_config)
        else:
            logger.warning(f"Nieznany typ alertu: {alert_type}")

    def _check_price_change_alert(self, alert_config: AlertConfig):
        """Sprawdza alerty zmian cen"""
        try:
            conditions = alert_config.conditions
            threshold = conditions.get('threshold', 5.0)  # 5% domyślnie
            timeframe = conditions.get('timeframe', '1d')  # 1 dzień domyślnie
            
            # TODO: Implementacja sprawdzania zmiany procentowej
            # Na razie symulujemy sprawdzenie
            current_time = datetime.now(timezone.utc)
            current_hour = current_time.hour
            
            # Sprawdzanie czy jest odpowiednia pora na powiadomienia
            if 9 <= current_hour <= 21:  # 9:00-21:00 CET
                # Wysyłanie natychmiast
                message = f"Alert cenowy: Zmiana {threshold}% w {timeframe}"
                self._create_price_alert(alert_config, None, message, 'warning')
            else:
                # Oczekiwanie do rana
                message = f"Alert cenowy (oczekuje): Zmiana {threshold}% w {timeframe}"
                self._create_technical_alert(alert_config, None, message, 'warning')
                
        except Exception as e:
            logger.error(f"Błąd sprawdzania alertu cenowego: {str(e)}")

    def _check_dividend_change_alert(self, alert_config: AlertConfig):
        """Sprawdza alerty zmian dywidend"""
        try:
            conditions = alert_config.conditions
            threshold = conditions.get('threshold', 10.0)  # 10% domyślnie
            
            # TODO: Implementacja sprawdzania zmian dywidend
            message = f"Alert dywidendowy: Zmiana {threshold}%"
            self._create_technical_alert(alert_config, None, message, 'info')
            
        except Exception as e:
            logger.error(f"Błąd sprawdzania alertu dywidendowego: {str(e)}")

    def _check_technical_indicator_alert(self, alert_config: AlertConfig):
        """Sprawdza alerty wskaźników technicznych"""
        try:
            conditions = alert_config.conditions
            indicator = conditions.get('indicator', 'stochastic')
            timeframe = conditions.get('timeframe', '1w')
            
            # TODO: Implementacja sprawdzania MACD, Stochastic, RSI
            message = f"Alert wskaźnika {indicator}: Sygnał na {timeframe}"
            self._create_technical_alert(alert_config, None, message, 'info')
            
        except Exception as e:
            logger.error(f"Błąd sprawdzania alertu wskaźnika: {str(e)}")

    def _check_scheduler_status_alert(self, alert_config: AlertConfig):
        """Sprawdza status schedulera"""
        try:
            # TODO: Implementacja sprawdzania ostatniego wykonania zadania
            message = "Alert schedulera: Zadanie nie wykonało się w czasie"
            self._create_immediate_alert(alert_config, None, message, 'error')
            
        except Exception as e:
            logger.error(f"Błąd sprawdzania alertu schedulera: {str(e)}")

    def _check_log_errors_alert(self, alert_config: AlertConfig):
        """Sprawdza błędy w logach"""
        try:
            # TODO: Implementacja sprawdzania logów pod kątem błędów
            message = "Alert logów: Wykryto błędy w systemie"
            self._create_immediate_alert(alert_config, None, message, 'error')
            
        except Exception as e:
            logger.error(f"Błąd sprawdzania alertu logów: {str(e)}")

    def _create_technical_alert(self, alert_config: AlertConfig, ticker: Optional[str], message: str, severity: str):
        """Tworzy alert techniczny (oczekuje na powiadomienie o 10:00 CET)"""
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
                existing_alert.triggered_at = datetime.now(timezone.utc)
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
                existing_alert.triggered_at = datetime.now(timezone.utc)
                existing_alert.status = 'notified'
                existing_alert.notified_at = datetime.now(timezone.utc)
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
                new_alert.notified_at = datetime.now(timezone.utc)
            
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
                existing_alert.triggered_at = datetime.now(timezone.utc)
                existing_alert.status = 'notified'
                existing_alert.notified_at = datetime.now(timezone.utc)
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
                new_alert.notified_at = datetime.now(timezone.utc)
            
            db.session.commit()
            logger.info(f"Alert natychmiastowy utworzony i powiadomienie wysłane: {message}")
            
        except Exception as e:
            logger.error(f"Błąd tworzenia alertu natychmiastowego: {str(e)}")
            db.session.rollback()

    def send_technical_notifications(self):
        """Wysyła wszystkie oczekujące powiadomienia techniczne o 10:00 CET"""
        try:
            # Pobieranie wszystkich aktywnych alertów oczekujących na powiadomienie
            pending_alerts = AlertHistory.query.filter_by(
                status='active'
            ).all()
            
            for alert in pending_alerts:
                try:
                    # Wysyłanie powiadomienia
                    self.send_slack_notification(alert.id, alert.message, alert.severity)
                    
                    # Aktualizacja statusu
                    alert.status = 'notified'
                    alert.notified_at = datetime.now(timezone.utc)
                    
                except Exception as e:
                    logger.error(f"Błąd wysyłania powiadomienia dla alertu {alert.id}: {str(e)}")
            
            db.session.commit()
            logger.info(f"Wysłano {len(pending_alerts)} powiadomień technicznych")
            
        except Exception as e:
            logger.error(f"Błąd wysyłania powiadomień technicznych: {str(e)}")
            db.session.rollback()

    def resolve_alert(self, alert_id: int):
        """Oznacza alert jako rozwiązany"""
        try:
            alert = AlertHistory.query.get(alert_id)
            if alert:
                alert.status = 'resolved'
                alert.resolved_at = datetime.now(timezone.utc)
                db.session.commit()
                logger.info(f"Alert {alert_id} oznaczony jako rozwiązany")
            else:
                logger.warning(f"Alert {alert_id} nie znaleziony")
                
        except Exception as e:
            logger.error(f"Błąd rozwiązywania alertu {alert_id}: {str(e)}")
            db.session.rollback()

    def dismiss_alert(self, alert_id: int):
        """Oznacza alert jako odrzucony"""
        try:
            alert = AlertHistory.query.get(alert_id)
            if alert:
                alert.status = 'dismissed'
                db.session.commit()
                logger.info(f"Alert {alert_id} oznaczony jako odrzucony")
            else:
                logger.warning(f"Alert {alert_id} nie znaleziony")
                
        except Exception as e:
            logger.error(f"Błąd odrzucania alertu {alert_id}: {str(e)}")
            db.session.rollback()

    def get_alert_history(self, limit: int = 50) -> List[Dict]:
        """Pobiera historię alertów"""
        try:
            alerts = AlertHistory.query.order_by(
                AlertHistory.triggered_at.desc()
            ).limit(limit).all()
            
            return [
                {
                    'id': alert.id,
                    'alert_config_id': alert.alert_config_id,
                    'etf_ticker': alert.etf_ticker,
                    'message': alert.message,
                    'severity': alert.severity,
                    'status': alert.status,
                    'triggered_at': alert.triggered_at.isoformat() if alert.triggered_at else None,
                    'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
                    'notified_at': alert.notified_at.isoformat() if alert.notified_at else None
                }
                for alert in alerts
            ]
            
        except Exception as e:
            logger.error(f"Błąd pobierania historii alertów: {str(e)}")
            return []

    def get_notification_history(self, limit: int = 50) -> List[Dict]:
        """Pobiera historię powiadomień"""
        try:
            notifications = Notification.query.order_by(
                Notification.sent_at.desc()
            ).limit(limit).all()
            
            return [
                {
                    'id': notification.id,
                    'alert_id': notification.alert_id,
                    'channel': notification.channel,
                    'status': notification.status,
                    'sent_at': notification.sent_at.isoformat() if notification.sent_at else None,
                    'error_message': notification.error_message
                }
                for notification in notifications
            ]
            
        except Exception as e:
            logger.error(f"Błąd pobierania historii powiadomień: {str(e)}")
            return []

    def cleanup_old_alerts(self, days: int = 30):
        """Usuwa stare alerty"""
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Usuwanie starych alertów
            old_alerts = AlertHistory.query.filter(
                AlertHistory.triggered_at < cutoff_date
            ).all()
            
            for alert in old_alerts:
                db.session.delete(alert)
            
            # Usuwanie starych powiadomień
            old_notifications = Notification.query.filter(
                Notification.sent_at < cutoff_date
            ).all()
            
            for notification in old_notifications:
                db.session.delete(notification)
            
            db.session.commit()
            logger.info(f"Usunięto {len(old_alerts)} starych alertów i {len(old_notifications)} powiadomień")
            
        except Exception as e:
            logger.error(f"Błąd czyszczenia starych alertów: {str(e)}")
            db.session.rollback()
