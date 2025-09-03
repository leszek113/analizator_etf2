from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta, timezone, date
import logging
import os
import time

# Wersja systemu - import z config.py
from config import __version__, VERSION_INFO

from config import Config
import pytz

# Import funkcji utc_to_cet z wspólnego modułu
from utils import utc_to_cet
from models import db, SystemLog
from services.database_service import DatabaseService
from services.api_service import APIService

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Walidacja środowiska
    env = os.environ.get('FLASK_ENV', 'development')
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    if env == 'production' and debug_mode:
        logger.warning("⚠️  UWAGA: Debug mode włączony w produkcji! Automatyczne wyłączenie...")
        os.environ['FLASK_DEBUG'] = 'False'
        debug_mode = False
    
    logger.info(f"🌍 Środowisko: {env.upper()}, Debug: {'WŁĄCZONY' if debug_mode else 'WYŁĄCZONY'}")
    
    # Pobieranie portu i hosta z konfiguracji
    port = app.config.get('PORT', 5005)
    host = app.config.get('HOST', '127.0.0.1')
    
    # Inicjalizacja rozszerzeń
    db.init_app(app)
    CORS(app)
    
    # Dodanie własnego filtra Jinja2 do formatowania liczb z przecinkiem
    @app.template_filter('comma_format')
    def comma_format_filter(value, decimals=2):
        """Filtr do formatowania liczb z przecinkiem (polski format)"""
        if value is None:
            return 'N/A'
        try:
            formatted = f"{float(value):.{decimals}f}"
            return formatted.replace('.', ',')
        except (ValueError, TypeError):
            return 'N/A'
    
    # Dodanie filtra Jinja2 do formatowania liczb z kropką (dla JavaScript)
    @app.template_filter('dot_format')
    def dot_format_filter(value, decimals=2):
        """Filtr do formatowania liczb z kropką (dla JavaScript)"""
        if value is None:
            return 'N/A'
        try:
            return f"{float(value):.{decimals}f}"
        except (ValueError, TypeError):
            return 'N/A'
    
    # Inicjalizacja serwisu API
    api_service = APIService()
    
    # Inicjalizacja serwisu bazy danych (używa współdzielonego APIService)
    db_service = DatabaseService(api_service=api_service)
    
    # Inicjalizacja bazy danych
    with app.app_context():
        db.create_all()
        logger.info("Database initialized")
    
    # Scheduler dla zadań cyklicznych
    scheduler = BackgroundScheduler()
    scheduler.start()
    
    # Konfiguracja dla zadań schedulera
    scheduler_config = Config()
    
    # Dodawanie zadań do schedulera
    def update_all_timeframes():
        """Zadanie schedulera do codziennej aktualizacji wszystkich ETF (1M, 1W, 1D) - Aktualizacja wszystkich ram czasowych"""
        start_time = time.time()
        with app.app_context():
            try:
                etfs = db_service.get_all_etfs()
                updated_count = 0
                history_completion_stats = {
                    'total_etfs': len(etfs),
                    'etfs_with_complete_history': 0,
                    'prices_filled_total': 0,
                    'dividends_filled_total': 0,
                    'weekly_prices_filled_total': 0,
                    'daily_prices_filled_total': 0,
                    'api_calls_used_total': 0
                }
                
                for etf in etfs:
                    logger.info(f"Processing ETF {etf.ticker} for daily update (all timeframes)")
                    
                    # Standardowa aktualizacja (nowe ceny, dywidendy)
                    if db_service.update_etf_data(etf.ticker):
                        updated_count += 1
                    
                    # Inteligentne uzupełnianie historii (raz dziennie) - 1M, 1W, 1D
                    logger.info(f"Checking history completion for ETF {etf.ticker} (1M, 1W, 1D)")
                    completion_result = db_service.smart_history_completion(etf.id, etf.ticker)
                    
                    # Aktualizacja statystyk
                    if (completion_result['prices_complete'] and 
                        completion_result['dividends_complete'] and
                        completion_result['weekly_prices_complete'] and
                        completion_result['daily_prices_complete']):
                        history_completion_stats['etfs_with_complete_history'] += 1
                    
                    history_completion_stats['prices_filled_total'] += completion_result['prices_filled']
                    history_completion_stats['dividends_filled_total'] += completion_result['dividends_filled']
                    history_completion_stats['weekly_prices_filled_total'] += completion_result['weekly_prices_filled']
                    history_completion_stats['daily_prices_filled_total'] += completion_result['daily_prices_filled']
                    history_completion_stats['api_calls_used_total'] += completion_result['api_calls_used']
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                total_records = (history_completion_stats['prices_filled_total'] + 
                               history_completion_stats['dividends_filled_total'] +
                               history_completion_stats['weekly_prices_filled_total'] +
                               history_completion_stats['daily_prices_filled_total'])
                
                # Logowanie sukcesu zadania
                job_log = SystemLog.create_job_log(
                    job_name="update_all_timeframes",
                    success=True,
                    execution_time_ms=execution_time_ms,
                    records_processed=total_records,
                    details=f"Zaktualizowano {updated_count}/{len(etfs)} ETF, uzupełniono {history_completion_stats['prices_filled_total']} cen 1M, {history_completion_stats['weekly_prices_filled_total']} cen 1W, {history_completion_stats['daily_prices_filled_total']} cen 1D, {history_completion_stats['dividends_filled_total']} dywidend, użyto {history_completion_stats['api_calls_used_total']} wywołań API",
                    metadata={
                        'etfs_updated': updated_count,
                        'total_etfs': len(etfs),
                        'prices_filled': history_completion_stats['prices_filled_total'],
                        'dividends_filled': history_completion_stats['dividends_filled_total'],
                        'weekly_prices_filled': history_completion_stats['weekly_prices_filled_total'],
                        'daily_prices_filled': history_completion_stats['daily_prices_filled_total'],
                        'api_calls_used': history_completion_stats['api_calls_used_total'],
                        'etfs_with_complete_history': history_completion_stats['etfs_with_complete_history']
                    }
                )
                db.session.add(job_log)
                db.session.commit()
                
                logger.info(f"Daily update completed: {updated_count} out of {len(etfs)} ETFs updated")
                logger.info(f"History completion: {history_completion_stats['etfs_with_complete_history']}/{history_completion_stats['total_etfs']} ETFs have complete history")
                logger.info(f"Data filled: {history_completion_stats['prices_filled_total']} prices 1M, {history_completion_stats['weekly_prices_filled_total']} prices 1W, {history_completion_stats['daily_prices_filled_total']} prices 1D, {history_completion_stats['dividends_filled_total']} dividends")
                logger.info(f"API calls used for history completion: {history_completion_stats['api_calls_used_total']}")
                
                # Czyszczenie starych logów i cen dziennych
                db_service.cleanup_old_data()
                # Rolling window z konfiguracji
                from config import Config
                config = Config()
                db_service.cleanup_old_daily_prices(config.DAILY_PRICES_WINDOW_DAYS)
                
            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)
                error_msg = f"Error in scheduled update: {str(e)}"
                logger.error(error_msg)
                
                # Logowanie błędu zadania
                job_log = SystemLog.create_job_log(
                    job_name="update_all_timeframes",
                    success=False,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Błąd podczas aktualizacji wszystkich ram czasowych ETF",
                    error_message=error_msg
                )
                db.session.add(job_log)
                db.session.commit()
    
    def update_etf_prices():
        """Zadanie schedulera do aktualizacji cen ETF co 15 minut w dni robocze (Aktualizacja cen ETF)"""
        start_time = time.time()
        with app.app_context():
            try:
                etfs = db_service.get_all_etfs()
                logger.info(f"Starting scheduled ETF price update for {len(etfs)} ETFs...")
                
                updated_count = 0
                error_count = 0
                for etf in etfs:
                    try:
                        logger.info(f"Updating price for ETF {etf.ticker}...")
                        
                        # Sprawdzenie czy nie przekroczyliśmy czasu (maksymalnie 10 minut)
                        elapsed_time = time.time() - start_time
                        if elapsed_time > 600:  # 10 minut
                            logger.warning(f"Price update taking too long ({elapsed_time:.1f}s), stopping early")
                            break
                        
                        # Pobieranie aktualnej ceny
                        current_price = api_service.get_current_price(etf.ticker)
                        
                        if current_price:
                            # Aktualizacja ceny w tabeli ETF
                            db_service.update_etf_price(etf.id, current_price)
                            
                            # Dodanie rekordu do historii cen
                            db_service.add_price_history_record(etf.id, current_price)
                            
                            updated_count += 1
                            logger.info(f"Successfully updated price for {etf.ticker}: ${current_price}")
                        else:
                            logger.warning(f"Failed to get current price for {etf.ticker}")
                            error_count += 1
                            
                    except Exception as e:
                        logger.error(f"Error updating price for ETF {etf.ticker}: {str(e)}")
                        error_count += 1
                        continue
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # Logowanie sukcesu zadania
                job_log = SystemLog.create_job_log(
                    job_name="update_etf_prices",
                    success=True if error_count == 0 else False,
                    execution_time_ms=execution_time_ms,
                    records_processed=updated_count,
                    details=f"Zaktualizowano ceny {updated_count}/{len(etfs)} ETF, błędy: {error_count}",
                    error_message=f"Błędy API dla {error_count} ETF: problemy z pobieraniem cen z zewnętrznych źródeł" if error_count > 0 else None,
                    metadata={
                        'etfs_updated': updated_count,
                        'total_etfs': len(etfs),
                        'errors': error_count
                    }
                )
                db.session.add(job_log)
                db.session.commit()
                
                logger.info(f"Price update completed: {updated_count} out of {len(etfs)} ETFs updated")
                
                # UWAGA: cleanup_old_price_history() został usunięty - niszczył historyczne ceny miesięczne!
                # Retencja cen historycznych: NIEKONIECZNA - dane historyczne są zachowywane na zawsze
                
            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)
                error_msg = f"Error in scheduled price update: {str(e)}"
                logger.error(error_msg)
                
                # Logowanie błędu zadania
                job_log = SystemLog.create_job_log(
                    job_name="update_etf_prices",
                    success=False,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Błąd podczas aktualizacji cen ETF",
                    error_message=error_msg
                )
                db.session.add(job_log)
                db.session.commit()
    
    def scheduled_daily_price_update():
        """Inteligentna aktualizacja cen dziennych ETF - sprawdza braki i uzupełnia dane"""
        start_time = time.time()
        with app.app_context():
            try:
                etfs = db_service.get_all_etfs()
                logger.info(f"Starting intelligent daily price update for {len(etfs)} ETFs...")
                
                total_updated = 0
                total_added = 0
                total_cleaned = 0
                total_completeness_improved = 0
                error_count = 0
                
                for etf in etfs:
                    try:
                        logger.info(f"Processing ETF {etf.ticker}...")
                        
                        # Sprawdzenie czy nie przekroczyliśmy czasu (maksymalnie 15 minut)
                        elapsed_time = time.time() - start_time
                        if elapsed_time > 900:  # 15 minut
                            logger.warning(f"Daily price update taking too long ({elapsed_time:.1f}s), stopping early")
                            break
                        
                        # Sprawdź kompletność danych przed aktualizacją
                        completeness_before = db_service.check_historical_completeness(etf.id, days_back=365)
                        if completeness_before:
                            logger.info(f"Kompletność {etf.ticker} przed aktualizacją: {completeness_before['completeness_percentage']:.1f}% ({completeness_before['actual_business_days']}/{completeness_before['expected_business_days']})")
                        
                        # 1. Sprawdź jakie ceny dzienne mamy w bazie (rozszerzone do 365 dni)
                        missing_dates = db_service.get_missing_daily_prices(etf.id, days_back=365)
                        
                        if missing_dates:
                            logger.info(f"Found {len(missing_dates)} missing dates for {etf.ticker}")
                            
                            # 2. Pobierz brakujące ceny historyczne inteligentnie (rozszerzone do 365 dni)
                            try:
                                logger.info(f"Pobieram brakujące ceny historyczne dla {etf.ticker} (365 dni)...")
                                historical_data = db_service.get_historical_daily_prices_intelligent(etf.ticker, days=365)
                                
                                if historical_data:
                                    logger.info(f"Pobrano {len(historical_data)} cen historycznych dla {etf.ticker}")
                                    
                                    # Dodaj brakujące ceny
                                    for missing_date in missing_dates:
                                        price_for_date = None
                                        for price_data in historical_data:
                                            if price_data['date'] == missing_date:
                                                price_for_date = price_data['close']
                                                break
                                        
                                        if price_for_date:
                                            db_service.add_daily_price_record(etf.id, price_for_date)
                                            total_added += 1
                                            logger.info(f"Added missing price for {etf.ticker} {missing_date}: ${price_for_date}")
                                        else:
                                            logger.warning(f"Price not found in API for {etf.ticker} {missing_date}")
                                else:
                                    logger.warning(f"Failed to get historical data for {etf.ticker} from all API sources")
                                    
                            except Exception as e:
                                logger.error(f"Error fetching historical prices for {etf.ticker}: {str(e)}")
                                continue
                        else:
                            logger.info(f"All daily prices are up to date for {etf.ticker}")
                        
                        # Sprawdź kompletność danych po aktualizacji
                        completeness_after = db_service.check_historical_completeness(etf.id, days_back=365)
                        if completeness_after and completeness_before:
                            improvement = completeness_after['completeness_percentage'] - completeness_before['completeness_percentage']
                            if improvement > 0:
                                total_completeness_improved += 1
                                logger.info(f"✅ Kompletność {etf.ticker} poprawiona o {improvement:.1f}%: {completeness_after['completeness_percentage']:.1f}%")
                        
                        # 3. Pobierz aktualną cenę i zaktualizuj
                        current_price = api_service.get_current_price(etf.ticker)
                        if current_price:
                            db_service.update_etf_price(etf.id, current_price)
                            db_service.add_daily_price_record(etf.id, current_price)
                            total_updated += 1
                            logger.info(f"Updated current price for {etf.ticker}: ${current_price}")
                        else:
                            logger.warning(f"Failed to get current price for {etf.ticker}")
                            error_count += 1
                            
                    except Exception as e:
                        logger.error(f"Error processing ETF {etf.ticker}: {str(e)}")
                        error_count += 1
                        continue
                
                # 4. Wyczyść stare ceny dzienne (starsze niż 250 dni roboczych)
                logger.info("Cleaning up old daily prices...")
                for etf in etfs:
                    try:
                        cleaned_count = db_service.cleanup_old_daily_prices(days_back=250)
                        total_cleaned += cleaned_count
                        if cleaned_count > 0:
                            logger.info(f"Cleaned {cleaned_count} old prices for {etf.ticker}")
                    except Exception as e:
                        logger.error(f"Error cleaning up prices for {etf.ticker}: {str(e)}")
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # Logowanie sukcesu zadania
                job_log = SystemLog.create_job_log(
                    job_name="scheduled_daily_price_update",
                    success=True if error_count == 0 else False,
                    execution_time_ms=execution_time_ms,
                    records_processed=total_updated + total_added,
                    details=f"Intelligent daily price update: {total_updated} updated, {total_added} added, {total_cleaned} cleaned, {total_completeness_improved} ETFs improved, {error_count} errors",
                    error_message=f"API errors for {error_count} ETFs" if error_count > 0 else None,
                    metadata={
                        'etfs_updated': total_updated,
                        'prices_added': total_added,
                        'prices_cleaned': total_cleaned,
                        'completeness_improved': total_completeness_improved,
                        'total_etfs': len(etfs),
                        'errors': error_count,
                        'update_type': 'intelligent_daily_sync_with_backfill'
                    }
                )
                db.session.add(job_log)
                db.session.commit()
                
                logger.info(f"Intelligent daily price update completed: {total_updated} updated, {total_added} added, {total_cleaned} cleaned, {total_completeness_improved} ETFs improved")
                
            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)
                error_msg = f"Error in intelligent daily price update: {str(e)}"
                logger.error(error_msg)
                
                # Logowanie błędu zadania
                job_log = SystemLog.create_job_log(
                    job_name="scheduled_daily_price_update",
                    success=False,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Error during intelligent daily price update",
                    error_message=error_msg
                )
                db.session.add(job_log)
                db.session.commit()
    
    def scheduled_log_cleanup():
        """Zadanie schedulera do cotygodniowego czyszczenia starych logów"""
        start_time = time.time()
        with app.app_context():
            try:
                logger.info("Starting scheduled log cleanup...")
                
                # Czyszczenie starych logów systemowych (retencja 90 dni)
                system_logs_deleted = db_service.cleanup_old_system_logs(retention_days=90)
                
                # Czyszczenie starych logów zadań (retencja 30 dni)
                job_logs_deleted = db_service.cleanup_old_job_logs(retention_days=30)
                
                total_deleted = system_logs_deleted + job_logs_deleted
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # Logowanie sukcesu zadania
                job_log = SystemLog.create_job_log(
                    job_name="scheduled_log_cleanup",
                    success=True,
                    execution_time_ms=execution_time_ms,
                    records_processed=total_deleted,
                    details=f"Wyczyściliśmy {total_deleted} starych logów (system: {system_logs_deleted}, zadania: {job_logs_deleted})",
                    metadata={
                        'system_logs_deleted': system_logs_deleted,
                        'job_logs_deleted': job_logs_deleted,
                        'total_deleted': total_deleted,
                        'retention_policy': {
                            'system_logs': '90 dni',
                            'job_logs': '30 dni'
                        }
                    }
                )
                db.session.add(job_log)
                db.session.commit()
                
                logger.info(f"Log cleanup completed: {total_deleted} logs deleted")
                
            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)
                error_msg = f"Error in scheduled log cleanup: {str(e)}"
                logger.error(error_msg)
                
                # Logowanie błędu zadania
                job_log = SystemLog.create_job_log(
                    job_name="scheduled_log_cleanup",
                    success=False,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Błąd podczas czyszczenia logów",
                    error_message=error_msg
                )
                db.session.add(job_log)
                db.session.commit()
    
    def check_alerts():
        """Zadanie schedulera do sprawdzania alertów wskaźników technicznych raz dziennie"""
        start_time = time.time()
        with app.app_context():
            try:
                from services.notification_service import NotificationService
                notification_service = NotificationService(scheduler_config)
                notification_service.check_technical_alerts()
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                logger.info(f"Daily technical alerts check completed in {execution_time_ms}ms")
                
                # Logowanie sukcesu zadania
                job_log = SystemLog.create_job_log(
                    job_name="check_alerts",
                    success=True,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Sprawdzanie alertów wskaźników technicznych zakończone pomyślnie"
                )
                db.session.add(job_log)
                db.session.commit()
                
            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)
                error_msg = f"Error in daily alerts check: {str(e)}"
                logger.error(error_msg)
                
                # Logowanie błędu zadania
                job_log = SystemLog.create_job_log(
                    job_name="check_alerts",
                    success=False,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Błąd podczas sprawdzania alertów wskaźników technicznych",
                    error_message=error_msg
                )
                db.session.add(job_log)
                db.session.commit()

    def send_technical_notifications():
        """Zadanie schedulera do wysyłania powiadomień wskaźników technicznych o 10:00 CET"""
        start_time = time.time()
        with app.app_context():
            try:
                from services.notification_service import NotificationService
                notification_service = NotificationService(scheduler_config)
                notification_service.send_pending_technical_notifications()
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                logger.info(f"Technical notifications sent in {execution_time_ms}ms")
                
                # Logowanie sukcesu zadania
                job_log = SystemLog.create_job_log(
                    job_name="send_technical_notifications",
                    success=True,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Wysyłanie powiadomień wskaźników technicznych zakończone pomyślnie"
                )
                db.session.add(job_log)
                db.session.commit()
                
            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)
                error_msg = f"Error in sending technical notifications: {str(e)}"
                logger.error(error_msg)
                
                # Logowanie błędu zadania
                job_log = SystemLog.create_job_log(
                    job_name="send_technical_notifications",
                    success=False,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Błąd podczas wysyłania powiadomień wskaźników technicznych",
                    error_message=error_msg
                )
                db.session.add(job_log)
                db.session.commit()
    
    def check_alerts_frequent():
        """Zadanie schedulera do sprawdzania alertów co 10 minut (ceny, logi, zadania)"""
        start_time = time.time()
        with app.app_context():
            try:
                from services.notification_service import NotificationService
                notification_service = NotificationService(scheduler_config)
                notification_service.check_price_alerts()
                notification_service.check_scheduler_alerts()
                notification_service.check_log_alerts()
                
                execution_time_ms = int((time.time() - start_time) * 1000)
                logger.info(f"Frequent alerts check completed in {execution_time_ms}ms")
                
                # Logowanie sukcesu zadania
                job_log = SystemLog.create_job_log(
                    job_name="check_alerts_frequent",
                    success=True,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Sprawdzanie alertów co 10 minut zakończone pomyślnie"
                )
                db.session.add(job_log)
                db.session.commit()
                
            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)
                error_msg = f"Error in frequent alerts check: {str(e)}"
                logger.error(error_msg)
                
                # Logowanie błędu zadania
                job_log = SystemLog.create_job_log(
                    job_name="check_alerts_frequent",
                    success=False,
                    execution_time_ms=execution_time_ms,
                    records_processed=0,
                    details="Błąd podczas sprawdzania alertów co 10 minut",
                    error_message=error_msg
                )
                db.session.add(job_log)
                db.session.commit()
    
    # Uruchamianie aktualizacji wszystkich ram czasowych raz dziennie o 22:45 CET (poniedziałek-piątek)
    # Używamy UTC wewnętrznie: 22:45 CET = 21:45 UTC (zimą) lub 20:45 UTC (latem)
    scheduler.add_job(
        func=update_all_timeframes,
        trigger="cron",
        day_of_week="mon-fri",
        hour=21,  # UTC - odpowiada 22:45 CET
        minute=45,
        timezone="UTC",  # Używamy UTC wewnętrznie
        id="daily_timeframes_update",
        max_instances=1,
        misfire_grace_time=3600  # 1 godzina tolerancji na opóźnienia
    )
    
    # Uruchamianie aktualizacji cen co 15 minut w dni robocze (pon-piątek 15:35-22:05 CET)
    # Używamy UTC wewnętrznie: 15:35-22:05 CET = 14:35-21:05 UTC (zimą) lub 13:35-20:05 UTC (latem)
    scheduler.add_job(
        func=update_etf_prices,
        trigger="cron",
        day_of_week="mon-fri",
        hour="14-21",  # UTC - odpowiada 15:35-22:05 CET
        minute="*/15",  # co 15 minut
        timezone="UTC",  # Używamy UTC wewnętrznie
        id="price_update_15min",
        max_instances=1,
        misfire_grace_time=900  # 15 minut tolerancji na opóźnienia
    )
    
    # Uruchamianie sprawdzania alertów wskaźników technicznych raz dziennie o 23:00 CET (poniedziałek-piątek)
    # Używamy UTC wewnętrznie: 23:00 CET = 22:00 UTC (zimą) lub 21:00 UTC (latem)
    scheduler.add_job(
        func=check_alerts,
        trigger="cron",
        day_of_week="mon-fri",
        hour=22,  # UTC - odpowiada 23:00 CET
        minute=0,
        timezone="UTC",
        id="daily_alerts_check",
        max_instances=1,
        misfire_grace_time=3600  # 1 godzina tolerancji na opóźnienia
    )
    
    # Sprawdzanie alertów co 10 minut (ceny, logi, zadania)
    scheduler.add_job(
        func=check_alerts_frequent,
        trigger="interval",
        minutes=10,
        id="frequent_alerts_check",
        max_instances=1,  # Tylko jedna instancja na raz
        coalesce=True,    # Grupuj opóźnione uruchomienia
        misfire_grace_time=300  # 5 minut tolerancji na opóźnienia
    )

    # Wysyłanie powiadomień wskaźników technicznych o 10:00 CET (następny dzień)
    # Używamy UTC wewnętrznie: 10:00 CET = 09:00 UTC (zimą) lub 08:00 UTC (latem)
    scheduler.add_job(
        func=send_technical_notifications,
        trigger="cron",
        hour=9,  # UTC - odpowiada 10:00 CET
        minute=0,
        timezone="UTC",
        id="technical_notifications_send",
        max_instances=1,
        misfire_grace_time=3600  # 1 godzina tolerancji na opóźnienia
    )

    # Codzienna aktualizacja cen ETF na koniec dnia o 22:00 CET (po zamknięciu rynków amerykańskich)
    # Używamy UTC wewnętrznie: 22:00 CET = 21:00 UTC (zimą) lub 20:00 UTC (latem)
    scheduler.add_job(
        func=scheduled_daily_price_update,
        trigger="cron",
        day_of_week="mon-fri",  # Tylko w dni robocze
        hour=21,  # UTC - odpowiada 22:00 CET
        minute=0,
        timezone="UTC",  # Używamy UTC wewnętrznie
        id="daily_price_update",
        max_instances=1,
        misfire_grace_time=3600  # 1 godzina tolerancji na opóźnienia
    )

    # Cotygodniowe czyszczenie starych logów (niedziela 02:00 CET)
    # Używamy UTC wewnętrznie: 02:00 CET = 01:00 UTC (zimą) lub 00:00 UTC (latem)
    scheduler.add_job(
        func=scheduled_log_cleanup,
        trigger="cron",
        day_of_week="sun",  # Niedziela
        hour=1,  # UTC - odpowiada 02:00 CET
        minute=0,
        timezone="UTC",  # Używamy UTC wewnętrznie
        id="weekly_log_cleanup",
        max_instances=1,
        misfire_grace_time=7200  # 2 godziny tolerancji na opóźnienia
    )

    
    # Dodanie schedulera do app context
    app.scheduler = scheduler
    
    # Endpointy API
    @app.route('/')
    def dashboard():
        """Główny dashboard z tabelą ETF"""
        try:
            etfs = db_service.get_all_etfs()
            return render_template('dashboard.html', etfs=etfs)
        except Exception as e:
            logger.error(f"Error loading dashboard: {str(e)}")
            return render_template('error.html', error=str(e))
    
    @app.route('/etf/<ticker>')
    def etf_details(ticker):
        """Szczegółowy widok ETF z historią dywidend"""
        try:
            etf = db_service.get_etf_by_ticker(ticker)
            if not etf:
                return render_template('error.html', error=f'ETF {ticker} not found')
            
            # Pobieranie historii dywidend
            dividends = db_service.get_etf_dividends(etf.id)
            
            # Obliczanie sumy ostatnich dywidend w zależności od częstotliwości
            last_dividends_sum = db_service.calculate_recent_dividend_sum(etf.id, etf.frequency)
            
            # Obliczanie prognozowanego wzrostu dywidendy
            dividend_growth_forecast = db_service.calculate_dividend_growth_forecast(etf.id, etf.frequency)
            
            return render_template('etf_details.html', 
                                 etf=etf, 
                                 dividends=dividends,
                                 last_dividends_sum=last_dividends_sum,
                                 dividend_growth_forecast=dividend_growth_forecast)
        except Exception as e:
            logger.error(f"Error loading ETF details for {ticker}: {str(e)}")
            return render_template('error.html', error=str(e))
    
    @app.route('/api/etfs', methods=['GET'])
    def get_etfs():
        """API endpoint do pobierania wszystkich ETF"""
        try:
            etfs = db_service.get_all_etfs()
            
            # Konwertujemy ETF na dict bez wywoływania DSG
            etfs_with_dsg = []
            for etf in etfs:
                etf_data = etf.to_dict()
                # DSG będzie obliczane na żądanie, nie przy każdym ładowaniu dashboard
                etf_data['dsg'] = None  # Placeholder - DSG będzie pobierane osobno
                etfs_with_dsg.append(etf_data)
            
            return jsonify({
                'success': True,
                'data': etfs_with_dsg,
                'count': len(etfs_with_dsg)
            })
        except Exception as e:
            logger.error(f"Error fetching ETFs: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/etfs/<ticker>', methods=['GET'])
    def get_etf(ticker):
        """API endpoint do pobierania konkretnego ETF"""
        try:
            etf = db_service.get_etf_by_ticker(ticker)
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} not found'
                }), 404
            
            return jsonify({
                'success': True,
                'data': etf.to_dict()
            })
        except Exception as e:
            logger.error(f"Error fetching ETF {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/etfs', methods=['POST'])
    def add_etf():
        """API endpoint do dodawania nowego ETF"""
        try:
            data = request.get_json()
            if not data or 'ticker' not in data:
                return jsonify({
                    'success': False,
                    'error': 'Ticker is required'
                }), 400
            
            ticker = data['ticker'].upper().strip()
            if not ticker:
                return jsonify({
                    'success': False,
                    'error': 'Invalid ticker'
                }), 400
            
            # Dodawanie ETF
            etf = db_service.add_etf(ticker)
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'Failed to add ETF {ticker}'
                }), 500
            
            return jsonify({
                'success': True,
                'data': etf.to_dict(),
                'message': f'ETF {ticker} added successfully'
            })
            
        except Exception as e:
            logger.error(f"Error adding ETF: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/etfs/<ticker>/update', methods=['POST'])
    def update_etf(ticker):
        """API endpoint do aktualizacji danych ETF"""
        try:
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = db_service.get_etf_by_ticker(ticker)
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Sprawdzanie parametru force_update (z body JSON lub query string)
            data = request.get_json() or {}
            
            # Konwersja string "true"/"false" na boolean
            force_from_json = data.get('force', False)
            if isinstance(force_from_json, str):
                force_from_json = force_from_json.lower() == 'true'
            
            force_update = force_from_json or request.args.get('force', 'false').lower() == 'true'
            
            logger.info(f"Force update for {ticker}: {force_update} (data: {data}, args: {dict(request.args)})")
            logger.info(f"Type of force_update: {type(force_update)}, Value: {force_update}")
            logger.info(f"JSON data type: {type(data)}, force key type: {type(data.get('force'))}")
            logger.info(f"Force from JSON: {force_from_json}, Final force_update: {force_update}")
            
            # Aktualizacja danych ETF
            success = db_service.update_etf_data(ticker, force_update=force_update)
            if not success:
                return jsonify({
                    'success': False,
                    'error': f'Failed to update ETF {ticker}'
                }), 500
            
            return jsonify({
                'success': True,
                'message': f'ETF {ticker} updated successfully'
            })
            
        except Exception as e:
            logger.error(f"Error updating ETF {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/etfs/<ticker>/check-splits', methods=['POST'])
    def check_etf_splits(ticker):
        """API endpoint do ręcznego sprawdzania splitów ETF"""
        try:
            # Sprawdzanie czy ETF istnieje
            etf = db_service.get_etf_by_ticker(ticker)
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Wymuszenie sprawdzenia splitów
            success = db_service.force_split_detection(ticker)
            if not success:
                return jsonify({
                    'success': False,
                    'error': f'Failed to check splits for ETF {ticker}'
                }), 500
            
            return jsonify({
                'success': True,
                'message': f'Splits checked and normalized for ETF {ticker}'
            })
            
        except Exception as e:
            logger.error(f"Error checking splits for ETF {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>', methods=['DELETE'])
    def delete_etf(ticker):
        """API endpoint do usuwania ETF wraz z wszystkimi danymi"""
        try:
            success = db_service.delete_etf(ticker)
            if not success:
                return jsonify({
                    'success': False,
                    'error': f'Failed to delete ETF {ticker}'
                }), 500
            
            return jsonify({
                'success': True,
                'message': f'ETF {ticker} deleted successfully along with all related data'
            })
            
        except Exception as e:
            logger.error(f"Error deleting ETF {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/etfs/<ticker>/prices', methods=['GET'])
    def get_etf_prices(ticker):
        """API endpoint do pobierania cen miesięcznych ETF"""
        try:
            from models import ETF, ETFPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen z bazy danych
            db_service = DatabaseService(api_service=api_service)
            prices = db_service.get_monthly_prices(etf.id)
            
            if not prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cenowych dla {ticker}'
                }), 404
            
            # Formatowanie danych dla Chart.js
            price_data = []
            for price in prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m'),
                    'close_price': price.normalized_close_price,
                    'original_price': price.close_price,
                    'split_ratio': price.split_ratio_applied
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'prices': price_data,
                    'count': len(price_data),
                    'date_range': {
                        'start': price_data[0]['date'] if price_data else None,
                        'end': price_data[-1]['date'] if price_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF prices for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/etfs/<ticker>/weekly-prices', methods=['GET'])
    def get_etf_weekly_prices(ticker):
        """API endpoint do pobierania cen tygodniowych ETF"""
        try:
            from models import ETF, ETFWeeklyPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen tygodniowych z bazy danych
            db_service = DatabaseService(api_service=api_service)
            weekly_prices = db_service.get_weekly_prices(etf.id)
            
            if not weekly_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen tygodniowych dla {ticker}'
                }), 404
            
            # Formatowanie danych dla frontend
            formatted_prices = []
            for price in weekly_prices:
                formatted_prices.append({
                    'date': price.date.strftime('%Y-%m-%d'),
                    'close_price': price.close_price,
                    'volume': price.volume if hasattr(price, 'volume') else None
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'prices': formatted_prices,
                    'count': len(formatted_prices),
                    'date_range': {
                        'start': formatted_prices[0]['date'] if formatted_prices else None,
                        'end': formatted_prices[-1]['date'] if formatted_prices else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF weekly prices for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/monthly-prices', methods=['GET'])
    def get_etf_monthly_prices(ticker):
        """API endpoint do pobierania cen miesięcznych ETF"""
        try:
            from models import ETF, ETFPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen miesięcznych z bazy danych
            db_service = DatabaseService(api_service=api_service)
            monthly_prices = db_service.get_monthly_prices(etf.id)
            
            if not monthly_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen miesięcznych dla {ticker}'
                }), 404
            
            # Formatowanie danych dla frontend
            formatted_prices = []
            for price in monthly_prices:
                formatted_prices.append({
                    'date': price.date.strftime('%Y-%m-%d'),
                    'close_price': price.close_price,
                    'volume': price.volume if hasattr(price, 'volume') else None
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'prices': formatted_prices,
                    'count': len(formatted_prices),
                    'date_range': {
                        'start': formatted_prices[0]['date'] if formatted_prices else None,
                        'end': formatted_prices[-1]['date'] if formatted_prices else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF monthly prices for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/weekly-macd', methods=['GET'])
    def get_etf_weekly_macd(ticker):
        """API endpoint do pobierania MACD dla cen tygodniowych ETF (8-17-9)"""
        try:
            from models import ETF, ETFWeeklyPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen tygodniowych z bazy danych
            db_service = DatabaseService(api_service=api_service)
            weekly_prices = db_service.get_weekly_prices(etf.id)
            
            if not weekly_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen tygodniowych dla {ticker}'
                }), 404
            
            # Przygotowanie danych dla obliczeń
            price_data = []
            for price in weekly_prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),  # Konwertuj date na string
                    'close': price.normalized_close_price
                })
            
            logger.info(f"Przygotowano {len(price_data)} cen dla MACD (8-17-9)")
            
            # Obliczanie MACD
            macd_data = api_service.calculate_macd(
                price_data, 
                fast_period=8, 
                slow_period=17, 
                signal_period=9
            )
            
            logger.info(f"MACD (8-17-9) zwrócił: {len(macd_data) if macd_data else 0} punktów")
            
            if not macd_data:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się obliczyć MACD (8-17-9) dla {ticker}'
                }), 500
            
            # Formatowanie danych dla frontend
            formatted_data = []
            for data in macd_data:
                formatted_data.append({
                    'date': data['date'],  # data jest już stringiem
                    'macd_line': round(data['macd_line'], 4),
                    'signal_line': round(data['signal_line'], 4),
                    'histogram': round(data['histogram'], 4),
                    'current_price': round(data['current_price'], 2)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'macd': formatted_data,
                    'count': len(formatted_data),
                    'parameters': {
                        'fast_period': 8,
                        'slow_period': 17,
                        'signal_period': 9
                    },
                    'date_range': {
                        'start': formatted_data[0]['date'] if formatted_data else None,
                        'end': formatted_data[-1]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF weekly MACD for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/weekly-stochastic', methods=['GET'])
    def get_etf_weekly_stochastic(ticker):
        """API endpoint do pobierania Stochastic Oscillator dla cen tygodniowych ETF"""
        try:
            from models import ETF, ETFWeeklyPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen tygodniowych z bazy danych
            db_service = DatabaseService(api_service=api_service)
            weekly_prices = db_service.get_weekly_prices(etf.id)
            
            if not weekly_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen tygodniowych dla {ticker}'
                }), 404
            
            # Przygotowanie danych dla obliczeń
            price_data = []
            for price in weekly_prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),  # Konwertuj date na string
                    'close': price.normalized_close_price
                })
            
            logger.info(f"Przygotowano {len(price_data)} cen dla Stochastic Oscillator")
            logger.info(f"Przykładowe dane: {price_data[0] if price_data else 'Brak danych'}")
            
            # Obliczanie Stochastic Oscillator
            stochastic_data = api_service.calculate_stochastic_oscillator(
                price_data, 
                lookback_period=36, 
                smoothing_factor=12, 
                sma_period=12
            )
            
            logger.info(f"Funkcja calculate_stochastic_oscillator zwróciła: {len(stochastic_data) if stochastic_data else 0} punktów")
            if stochastic_data:
                logger.info(f"Przykładowy punkt: {stochastic_data[0]}")
            
            if not stochastic_data:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się obliczyć Stochastic Oscillator dla {ticker}'
                }), 500
            
            # Formatowanie danych dla frontend
            formatted_data = []
            for data in stochastic_data:
                formatted_data.append({
                    'date': data['date'],  # data jest już stringiem
                    'k_percent': round(data['k_percent_smoothed'], 2),
                    'd_percent': round(data['d_percent'], 2),
                    'current_price': round(data['current_price'], 2),
                    'highest_high': round(data['highest_high'], 2),
                    'lowest_low': round(data['lowest_low'], 2)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'stochastic': formatted_data,
                    'count': len(formatted_data),
                    'parameters': {
                        'lookback_period': 36,
                        'smoothing_factor': 12,
                        'sma_period': 12
                    },
                    'date_range': {
                        'start': formatted_data[0]['date'] if formatted_data else None,
                        'end': formatted_data[-1]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF weekly stochastic for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/weekly-stochastic-short', methods=['GET'])
    def get_etf_weekly_stochastic_short(ticker):
        """API endpoint do pobierania krótkiego Stochastic Oscillator dla cen tygodniowych ETF (9-3-3)"""
        try:
            from models import ETF, ETFWeeklyPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen tygodniowych z bazy danych
            db_service = DatabaseService(api_service=api_service)
            weekly_prices = db_service.get_weekly_prices(etf.id)
            
            if not weekly_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen tygodniowych dla {ticker}'
                }), 404
            
            # Przygotowanie danych dla obliczeń
            price_data = []
            for price in weekly_prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),  # Konwertuj date na string
                    'close': price.normalized_close_price
                })
            
            logger.info(f"Przygotowano {len(price_data)} cen dla krótkiego Stochastic Oscillator (9-3-3)")
            
            # Obliczanie krótkiego Stochastic Oscillator
            stochastic_data = api_service.calculate_stochastic_oscillator(
                price_data, 
                lookback_period=9, 
                smoothing_factor=3, 
                sma_period=3
            )
            
            logger.info(f"Krótki Stochastic Oscillator (9-3-3) zwrócił: {len(stochastic_data) if stochastic_data else 0} punktów")
            
            if not stochastic_data:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się obliczyć krótkiego Stochastic Oscillator (9-3-3) dla {ticker}'
                }), 500
            
            # Formatowanie danych dla frontend
            formatted_data = []
            for data in stochastic_data:
                formatted_data.append({
                    'date': data['date'],  # data jest już stringiem
                    'k_percent': round(data['k_percent_smoothed'], 2),
                    'd_percent': round(data['d_percent'], 2),
                    'current_price': round(data['current_price'], 2),
                    'highest_high': round(data['highest_high'], 2),
                    'lowest_low': round(data['lowest_low'], 2)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'stochastic': formatted_data,
                    'count': len(formatted_data),
                    'parameters': {
                        'lookback_period': 9,
                        'smoothing_factor': 3,
                        'sma_period': 3
                    },
                    'date_range': {
                        'start': formatted_data[0]['date'] if formatted_data else None,
                        'end': formatted_data[-1]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF weekly stochastic short for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/dividends', methods=['GET'])
    def get_etf_dividends(ticker):
        """API endpoint do pobierania historii dywidend ETF"""
        try:
            etf = db_service.get_etf_by_ticker(ticker)
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} not found'
                }), 404
            
            limit = request.args.get('limit', type=int)
            dividends = db_service.get_etf_dividends(etf.id, limit)
            
            return jsonify({
                'success': True,
                'data': [dividend.to_dict() for dividend in dividends],
                'count': len(dividends)
            })
            
        except Exception as e:
            logger.error(f"Error fetching dividends for ETF {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/etfs/<ticker>/dsg', methods=['GET'])
    def get_etf_dsg(ticker):
        """API endpoint do pobierania DSG dla konkretnego ETF"""
        try:
            # Sprawdzanie czy ETF istnieje
            etf = db_service.get_etf_by_ticker(ticker)
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie dywidend z bazy danych
            dividends = db_service.get_etf_dividends(etf.id)
            
            # Konwersja dywidend z bazy na format oczekiwany przez DSG
            dividends_for_dsg = []
            for dividend in dividends:
                dividends_for_dsg.append({
                    'payment_date': dividend.payment_date,
                    'amount': dividend.normalized_amount or dividend.amount
                })
            
            # Obliczanie DSG używając danych z bazy
            dsg_data = api_service.calculate_dividend_streak_growth(ticker, dividends_from_db=dividends_for_dsg)
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'dsg': dsg_data
                }
            })
            
        except Exception as e:
            logger.error(f"Error calculating DSG for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/break-even-dividends', methods=['GET'])
    def get_etf_break_even_dividends(ticker):
        """API endpoint do obliczania break-even time dla dywidend ETF"""
        try:
            # Sprawdzanie czy ETF istnieje
            etf = db_service.get_etf_by_ticker(ticker)
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie dywidend i cen z bazy danych
            dividends = db_service.get_etf_dividends(etf.id)
            prices = db_service.get_monthly_prices(etf.id)
            
            # Pobieranie parametru target_percentage z query string
            target_percentage = request.args.get('target_percentage', 5.0, type=float)
            
            # Obliczanie break-even time dla każdego miesiąca
            break_even_data = api_service.calculate_break_even_dividends(
                ticker, 
                dividends_from_db=dividends,
                prices_from_db=prices,
                target_percentage=target_percentage
            )
            
            return jsonify({
                'success': True,
                'data': break_even_data
            })
            
        except Exception as e:
            logger.error(f"Error calculating break-even dividends for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/system/logs', methods=['GET'])
    def get_system_logs():
        """API endpoint do pobierania logów systemu"""
        try:
            from models import SystemLog
            limit = request.args.get('limit', 100, type=int)
            level = request.args.get('level', 'INFO')
            
            query = SystemLog.query
            if level != 'ALL':
                query = query.filter_by(level=level)
            
            logs = query.order_by(SystemLog.timestamp.desc()).limit(limit).all()
            
            return jsonify({
                'success': True,
                'data': [log.to_dict() for log in logs],
                'count': len(logs)
            })
            
        except Exception as e:
            logger.error(f"Error fetching system logs: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/system/status', methods=['GET'])
    def get_system_status():
        """API endpoint do sprawdzania statusu systemu"""
        try:
            from models import ETF, ETFPrice, ETFWeeklyPrice, ETFDividend, SystemLog
            
            etf_count = ETF.query.count()
            price_count = ETFPrice.query.count()
            weekly_price_count = ETFWeeklyPrice.query.count()
            dividend_count = ETFDividend.query.count()
            log_count = SystemLog.query.count()
            
            # Sprawdzanie ostatniej aktualizacji
            latest_update = ETF.query.order_by(ETF.last_updated.desc()).first()
            last_update = latest_update.last_updated if latest_update else None
            
            # Sprawdzanie statusu tokenów API
            api_health = {}
            try:
                from services.api_service import APIService
                api_service = APIService()
                api_health = api_service.check_api_health()
            except Exception as e:
                api_health = {'error': str(e)}
            
            return jsonify({
                'success': True,
                'data': {
                    'etf_count': etf_count,
                    'price_count': price_count,
                    'weekly_price_count': weekly_price_count,
                    'dividend_count': dividend_count,
                    'log_count': log_count,
                    'last_update': last_update.isoformat() if last_update else None,
                    'scheduler_running': scheduler.running,
                    'uptime': str(datetime.now(timezone.utc) - app.start_time) if hasattr(app, 'start_time') else 'Unknown',
                    'api_health': api_health
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting system status: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/system/api-status', methods=['GET'])
    def get_api_token_status():
        """API endpoint do sprawdzania statusu tokenów API"""
        try:
            from services.api_service import APIService
            api_service = APIService()
            status = api_service.get_api_status()
            health = api_service.check_api_health()
            
            return jsonify({
                'success': True,
                'data': {
                    'api_status': status,
                    'health_check': health,
                    'timestamp': utc_to_cet(datetime.now(timezone.utc)).isoformat()
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting API token status: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/system/scheduler/jobs', methods=['GET'])
    def get_scheduler_jobs():
        """API endpoint do pobierania listy wszystkich zadań schedulera"""
        try:
            if not hasattr(app, 'scheduler') or not app.scheduler:
                return jsonify({
                    'success': False,
                    'error': 'Scheduler not available'
                }), 500
            
            jobs = app.scheduler.get_jobs()
            jobs_list = []
            
            for job in jobs:
                # Mapowanie funkcji na czytelne nazwy
                job_name_map = {
                    'update_all_timeframes': 'Aktualizacja wszystkich ramów czasowych',
                    'update_etf_prices': 'Aktualizacja cen ETF co 15 minut',
                    'check_alerts': 'Sprawdzanie alertów wskaźników technicznych',
                    'check_alerts_frequent': 'Częste sprawdzanie alertów',
                    'send_technical_notifications': 'Wysyłanie powiadomień technicznych',
                    'scheduled_daily_price_update': 'Codzienna aktualizacja cen ETF',
                    'scheduled_log_cleanup': 'Cotygodniowe czyszczenie logów'
                }
                
                # Uproszczone mapowanie trigger na czytelny opis
                trigger_description = "Nieznany"
                try:
                    trigger_str = str(job.trigger)
                    
                    # Mapowanie dla znanych zadań
                    if job.id == "frequent_alerts_check":
                        trigger_description = "Co 10 minut (codziennie)"
                    elif job.id == "price_update_15min":
                        trigger_description = "Co 15 min (poniedziałek-piątek 15:35-22:05 CET)"
                    elif job.id == "daily_price_update":
                        trigger_description = "22:00 CET (poniedziałek-piątek)"
                    elif job.id == "daily_timeframes_update":
                        trigger_description = "22:45 CET (poniedziałek-piątek)"
                    elif job.id == "daily_alerts_check":
                        trigger_description = "23:00 CET (poniedziałek-piątek)"
                    elif job.id == "technical_notifications_send":
                        trigger_description = "10:00 CET (codziennie)"
                    elif job.id == "weekly_log_cleanup":
                        trigger_description = "02:00 CET (niedziela)"
                    else:
                        # Fallback dla nieznanych zadań
                        if 'interval' in trigger_str:
                            trigger_description = f"Co {job.trigger.interval} {job.trigger.interval_length}"
                        elif 'cron' in trigger_str:
                            trigger_description = f"Cron ({trigger_str})"
                        else:
                            trigger_description = trigger_str
                            
                except Exception as e:
                    logger.warning(f"Error parsing trigger for job {job.id}: {str(e)}")
                    trigger_description = str(job.trigger)
                
                # Mapowanie funkcji na czytelne nazwy
                readable_name = job_name_map.get(job.func.__name__, job.func.__name__)
                
                jobs_list.append({
                    'id': job.id,
                    'name': readable_name,
                    'trigger': trigger_description,
                    'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                    'func_name': job.func.__name__
                })
            
            return jsonify({
                'success': True,
                'jobs': jobs_list,
                'total_jobs': len(jobs_list),
                'scheduler_running': app.scheduler.running
            })
            
        except Exception as e:
            logger.error(f"Error getting scheduler jobs: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/system/scheduler/update-job', methods=['POST'])
    def update_scheduler_job():
        """API endpoint do aktualizacji zadania w schedulerze"""
        try:
            if not hasattr(app, 'scheduler') or not app.scheduler:
                return jsonify({
                    'success': False,
                    'error': 'Scheduler not available'
                }), 500
            
            data = request.get_json()
            job_id = data.get('job_id')
            hour = data.get('hour')
            minute = data.get('minute')
            
            if not all([job_id, hour is not None, minute is not None]):
                return jsonify({
                    'success': False,
                    'error': 'Missing required parameters: job_id, hour, minute'
                }), 400
            
            # Usuń stare zadanie
            app.scheduler.remove_job(job_id)
            
            # Dodaj nowe zadanie z nowym czasem
            app.scheduler.add_job(
                func=update_all_timeframes,
                trigger="cron",
                hour=int(hour),
                minute=int(minute),
                id=job_id
            )
            
            logger.info(f"Updated scheduler job {job_id} to run at {hour:02d}:{minute:02d}")
            
            return jsonify({
                'success': True,
                'message': f'Job {job_id} updated to run at {hour:02d}:{minute:02d}',
                'next_run': app.scheduler.get_job(job_id).next_run_time.isoformat() if app.scheduler.get_job(job_id) else None
            })
            
        except Exception as e:
            logger.error(f"Error updating scheduler job: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    


    @app.route('/api/system/dividend-tax-rate', methods=['GET'])
    def get_dividend_tax_rate():
        """Pobiera aktualną stawkę podatku od dywidend"""
        try:
            tax_rate = db_service.get_dividend_tax_rate()
            return jsonify({
                'success': True,
                'data': {
                    'tax_rate': tax_rate
                }
            })
        except Exception as e:
            logger.error(f"Error getting dividend tax rate: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/system/dividend-tax-rate', methods=['POST'])
    def update_dividend_tax_rate():
        """Aktualizuje stawkę podatku od dywidend"""
        try:
            data = request.get_json()
            new_tax_rate = data.get('tax_rate')
            
            if new_tax_rate is None:
                return jsonify({'success': False, 'error': 'Brak stawki podatku'}), 400
            
            if not isinstance(new_tax_rate, (int, float)) or new_tax_rate < 0 or new_tax_rate > 100:
                return jsonify({'success': False, 'error': 'Nieprawidłowa stawka podatku (0-100%)'}), 400
            
            success = db_service.update_dividend_tax_rate(float(new_tax_rate))
            
            if success:
                return jsonify({
                    'success': True,
                    'message': f'Stawka podatku od dywidend zaktualizowana na {new_tax_rate}%'
                })
            else:
                return jsonify({'success': False, 'error': 'Błąd podczas aktualizacji stawki podatku'}), 500
                
        except Exception as e:
            logger.error(f"Error updating dividend tax rate: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/system/job-logs')
    def get_job_logs():
        """Pobiera logi zadań schedulera z filtrowaniem"""
        try:
            # Parametry filtrowania
            job_name = request.args.get('job_name', 'all')
            status = request.args.get('status', 'all')
            time_range = request.args.get('time_range', 'all')
            limit = int(request.args.get('limit', 20))
            
            # Budowanie zapytania
            query = SystemLog.query.filter(SystemLog.job_name.isnot(None))
            
            if job_name != 'all':
                query = query.filter(SystemLog.job_name == job_name)
            
            if status != 'all':
                query = query.filter(SystemLog.success == (status == 'success'))
            
            # Filtrowanie po czasie
            if time_range == '24h':
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                query = query.filter(SystemLog.timestamp >= cutoff)
            elif time_range == '7d':
                cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                query = query.filter(SystemLog.timestamp >= cutoff)
            elif time_range == '30d':
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                query = query.filter(SystemLog.timestamp >= cutoff)
            elif time_range == '3m':
                cutoff = datetime.now(timezone.utc) - timedelta(days=90)
                query = query.filter(SystemLog.timestamp >= cutoff)
            
            # Sortowanie i limit
            logs = query.order_by(SystemLog.timestamp.desc()).limit(limit).all()
            
            return jsonify({
                'success': True,
                'logs': [log.to_dict() for log in logs],
                'total': len(logs)
            })
            
        except Exception as e:
            logger.error(f"Error getting job logs: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/system/job-logs/<job_name>')
    def get_job_logs_by_name(job_name):
        """Pobiera logi dla konkretnego zadania z różnymi okresami historii"""
        try:
            # Okresy historii dla różnych zadań
            if job_name == 'update_all_etfs':
                # 3 miesiące dla aktualizacji wszystkich ETF
                cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            elif job_name == 'update_etf_prices':
                # 2 tygodnie dla aktualizacji cen
                cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            else:
                # Domyślnie 30 dni
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            
            # Pobieranie logów
            logs = SystemLog.query.filter(
                SystemLog.job_name == job_name,
                SystemLog.timestamp >= cutoff
            ).order_by(SystemLog.timestamp.desc()).limit(20).all()
            
            return jsonify({
                'success': True,
                'logs': [log.to_dict() for log in logs],
                'total': len(logs),
                'history_period_days': (datetime.now(timezone.utc) - cutoff).days
            })
            
        except Exception as e:
            logger.error(f"Error getting job logs for {job_name}: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/system/trigger-job/<job_name>', methods=['POST'])
    def trigger_job(job_name):
        """Ręcznie uruchamia zadanie scheduler'a"""
        try:
            if not hasattr(app, 'scheduler') or not app.scheduler:
                return jsonify({'success': False, 'error': 'Scheduler not available'}), 500
            
            # Sprawdzanie czy zadanie istnieje
            jobs = app.scheduler.get_jobs()
            job_found = False
            for job in jobs:
                if job_name in str(job.func):
                    job_found = True
                    break
            
            if not job_found:
                return jsonify({'success': False, 'error': f'Job {job_name} not found'}), 404
            
            # Uruchamianie zadania
            if job_name == 'update_all_etfs':
                # Uruchomienie w tle
                app.scheduler.add_job(
                    func=update_all_timeframes,
                    trigger='date',
                    run_date=datetime.now(timezone.utc),
                    id=f'manual_{job_name}_{int(time.time())}',
                    replace_existing=True
                )
                message = "Zadanie 'Aktualizacja wszystkich ETF' zostało uruchomione"
            elif job_name == 'update_etf_prices':
                # Uruchomienie w tle
                app.scheduler.add_job(
                    func=update_etf_prices,
                    trigger='date',
                    run_date=datetime.now(timezone.utc),
                    id=f'manual_{job_name}_{int(time.time())}',
                    replace_existing=True
                )
                message = "Zadanie 'Aktualizacja cen ETF' zostało uruchomione"
            else:
                return jsonify({'success': False, 'error': f'Unknown job: {job_name}'}), 400
            
            logger.info(f"Manually triggered job: {job_name}")
            return jsonify({
                'success': True,
                'message': message,
                'job_name': job_name,
                'timestamp': utc_to_cet(datetime.now(timezone.utc)).isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error triggering job {job_name}: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/system/update-all-etfs', methods=['POST'])
    def manual_update_all_etfs():
        """API endpoint do ręcznego uruchamiania aktualizacji wszystkich ETF"""
        try:
            # Uruchomienie zadania w tle
            update_all_timeframes()
            
            return jsonify({
                'success': True,
                'message': 'Aktualizacja wszystkich ETF została uruchomiona',
                'timestamp': utc_to_cet(datetime.now(timezone.utc)).isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error in manual update_all_etfs: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/monthly-macd', methods=['GET'])
    def get_etf_monthly_macd(ticker):
        """API endpoint do pobierania MACD dla cen miesięcznych ETF (8-17-9)"""
        try:
            from models import ETF, ETFPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen miesięcznych z bazy danych
            db_service = DatabaseService(api_service=api_service)
            monthly_prices = db_service.get_monthly_prices(etf.id)
            
            if not monthly_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen miesięcznych dla {ticker}'
                }), 404
            
            # Przygotowanie danych dla obliczeń
            price_data = []
            for price in monthly_prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),  # Konwertuj date na string
                    'close': price.close_price
                })
            
            logger.info(f"Przygotowano {len(price_data)} cen miesięcznych dla MACD (8-17-9)")
            
            # Obliczanie MACD
            macd_data = api_service.calculate_macd(
                price_data, 
                fast_period=8, 
                slow_period=17, 
                signal_period=9
            )
            
            logger.info(f"Miesięczny MACD (8-17-9) zwrócił: {len(macd_data) if macd_data else 0} punktów")
            
            if not macd_data:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się obliczyć miesięcznego MACD (8-17-9) dla {ticker}'
                }), 500
            
            # Formatowanie danych dla frontend
            formatted_data = []
            for data in macd_data:
                formatted_data.append({
                    'date': data['date'],  # data jest już stringiem
                    'macd_line': round(data['macd_line'], 4),
                    'signal_line': round(data['signal_line'], 4),
                    'histogram': round(data['histogram'], 4),
                    'current_price': round(data['current_price'], 2)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'macd': formatted_data,
                    'count': len(formatted_data),
                    'parameters': {
                        'fast_period': 8,
                        'slow_period': 17,
                        'signal_period': 9
                    },
                    'date_range': {
                        'start': formatted_data[0]['date'] if formatted_data else None,
                        'end': formatted_data[-1]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF monthly MACD for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/monthly-stochastic', methods=['GET'])
    def get_etf_monthly_stochastic(ticker):
        """API endpoint do pobierania Stochastic Oscillator dla cen miesięcznych ETF (36-12-12)"""
        try:
            from models import ETF, ETFPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen miesięcznych z bazy danych
            db_service = DatabaseService(api_service=api_service)
            monthly_prices = db_service.get_monthly_prices(etf.id)
            
            if not monthly_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen miesięcznych dla {ticker}'
                }), 404
            
            # Przygotowanie danych dla obliczeń
            price_data = []
            for price in monthly_prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),  # Konwertuj date na string
                    'close': price.close_price
                })
            
            logger.info(f"Przygotowano {len(price_data)} cen miesięcznych dla Stochastic Oscillator (36-12-12)")
            
            # Obliczanie Stochastic Oscillator
            stochastic_data = api_service.calculate_stochastic_oscillator(
                price_data, 
                lookback_period=36, 
                smoothing_factor=12, 
                sma_period=12
            )
            
            logger.info(f"Miesięczny Stochastic Oscillator (36-12-12) zwrócił: {len(stochastic_data) if stochastic_data else 0} punktów")
            
            if not stochastic_data:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się obliczyć miesięcznego Stochastic Oscillator (36-12-12) dla {ticker}'
                }), 500
            
            # Formatowanie danych dla frontend
            formatted_data = []
            for data in stochastic_data:
                formatted_data.append({
                    'date': data['date'],  # data jest już stringiem
                    'k_percent': round(data['k_percent_smoothed'], 2),
                    'd_percent': round(data['d_percent'], 2),
                    'current_price': round(data['current_price'], 2),
                    'highest_high': round(data['highest_high'], 2),
                    'lowest_low': round(data['lowest_low'], 2)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'stochastic': formatted_data,
                    'count': len(formatted_data),
                    'parameters': {
                        'lookback_period': 36,
                        'smoothing_factor': 12,
                        'sma_period': 12
                    },
                    'date_range': {
                        'start': formatted_data[0]['date'] if formatted_data else None,
                        'end': formatted_data[-1]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF monthly stochastic for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/monthly-stochastic-short', methods=['GET'])
    def get_etf_monthly_stochastic_short(ticker):
        """API endpoint do pobierania krótkiego Stochastic Oscillator dla cen miesięcznych ETF (9-3-3)"""
        try:
            from models import ETF, ETFPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen miesięcznych z bazy danych
            db_service = DatabaseService(api_service=api_service)
            monthly_prices = db_service.get_monthly_prices(etf.id)
            
            if not monthly_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen miesięcznych dla {ticker}'
                }), 404
            
            # Przygotowanie danych dla obliczeń
            price_data = []
            for price in monthly_prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),  # Konwertuj date na string
                    'close': price.close_price
                })
            
            logger.info(f"Przygotowano {len(price_data)} cen miesięcznych dla krótkiego Stochastic Oscillator (9-3-3)")
            
            # Obliczanie krótkiego Stochastic Oscillator
            stochastic_data = api_service.calculate_stochastic_oscillator(
                price_data, 
                lookback_period=9, 
                smoothing_factor=3, 
                sma_period=3
            )
            
            logger.info(f"Miesięczny krótki Stochastic Oscillator (9-3-3) zwrócił: {len(stochastic_data) if stochastic_data else 0} punktów")
            
            if not stochastic_data:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się obliczyć miesięcznego krótkiego Stochastic Oscillator (9-3-3) dla {ticker}'
                }), 500
            
            # Formatowanie danych dla frontend
            formatted_data = []
            for data in stochastic_data:
                formatted_data.append({
                    'date': data['date'],  # data jest już stringiem
                    'k_percent': round(data['k_percent_smoothed'], 2),
                    'd_percent': round(data['d_percent'], 2),
                    'current_price': round(data['current_price'], 2),
                    'highest_high': round(data['highest_high'], 2),
                    'lowest_low': round(data['lowest_low'], 2)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'stochastic': formatted_data,
                    'count': len(formatted_data),
                    'parameters': {
                        'lookback_period': 9,
                        'smoothing_factor': 3,
                        'sma_period': 3
                    },
                    'date_range': {
                        'start': formatted_data[0]['date'] if formatted_data else None,
                        'end': formatted_data[-1]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF monthly stochastic short for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/daily-prices', methods=['GET'])
    def get_etf_daily_prices(ticker):
        """API endpoint do pobierania cen dziennych ETF (ostatnie 365 dni)"""
        try:
            from models import ETF, ETFDailyPrice
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen dziennych z bazy danych (ostatnie 365 dni)
            cutoff_date = date.today() - timedelta(days=365)
            daily_prices = ETFDailyPrice.query.filter(
                ETFDailyPrice.etf_id == etf.id,
                ETFDailyPrice.date >= cutoff_date
            ).order_by(ETFDailyPrice.date.desc()).all()
            
            if not daily_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen dziennych dla {ticker}'
                }), 404
            
            # Formatowanie danych dla frontend (używamy znormalizowanych cen z bazy)
            formatted_data = []
            for price in daily_prices:
                formatted_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),
                    'close': round(price.normalized_close_price, 2),  # Używamy znormalizowanej ceny z bazy
                    'open': round(price.open_price / price.split_ratio_applied, 2) if price.open_price else None,
                    'high': round(price.high_price / price.split_ratio_applied, 2) if price.high_price else None,
                    'low': round(price.low_price / price.split_ratio_applied, 2) if price.low_price else None,
                    'volume': price.volume if price.volume else None
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'daily_prices': formatted_data,
                    'count': len(formatted_data),
                    'date_range': {
                        'start': formatted_data[-1]['date'] if formatted_data else None,
                        'end': formatted_data[0]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF daily prices for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)}
            ), 500

    @app.route('/api/etfs/<ticker>/add-daily-prices', methods=['POST'])
    def add_etf_daily_prices(ticker):
        """API endpoint do dodawania cen dziennych dla istniejącego ETF"""
        try:
            from models import ETF, ETFDailyPrice
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen dziennych z API
            daily_prices = api_service.get_historical_daily_prices(ticker, days=365, normalize_splits=True)
            
            if not daily_prices:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się pobrać cen dziennych dla {ticker}'
                }), 500
            
            # Dodawanie cen do bazy danych
            added_count = 0
            for price_data in daily_prices:
                # Sprawdź czy już nie mamy tej ceny
                existing_price = ETFDailyPrice.query.filter_by(
                    etf_id=etf.id,
                    date=price_data['date']
                ).first()
                
                if not existing_price:
                    # Wyciąganie roku, miesiąca i dnia z daty
                    price_date = price_data['date']
                    if isinstance(price_date, str):
                        price_date = datetime.strptime(price_date, '%Y-%m-%d').date()
                    
                    daily_price = ETFDailyPrice(
                        etf_id=etf.id,
                        date=price_date,
                        close_price=price_data['close'],
                        normalized_close_price=price_data.get('normalized_close', price_data['close']),
                        split_ratio_applied=price_data.get('split_ratio_applied', 1.0),
                        year=price_date.year,
                        month=price_date.month,
                        day=price_date.day,
                        open_price=price_data.get('open'),
                        high_price=price_data.get('high'),
                        low_price=price_data.get('low'),
                        volume=price_data.get('volume')
                    )
                    db.session.add(daily_price)
                    added_count += 1
            
            if added_count > 0:
                db.session.commit()
                logger.info(f"Added {added_count} daily prices for {ticker}")
            
            return jsonify({
                'success': True,
                'message': f'Dodano {added_count} nowych cen dziennych dla {ticker}',
                'data': {
                    'ticker': ticker.upper(),
                    'prices_added': added_count,
                    'total_daily_prices': len(daily_prices)
                }
            })
            
        except Exception as e:
            logger.error(f"Error adding daily prices for {ticker}: {str(e)}")
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/daily-macd', methods=['GET'])
    def get_etf_daily_macd(ticker):
        """API endpoint do pobierania MACD dla cen dziennych ETF (8-17-9)"""
        try:
            from models import ETF, ETFDailyPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen dziennych z bazy danych (ostatnie 365 dni)
            cutoff_date = date.today() - timedelta(days=365)
            daily_prices = ETFDailyPrice.query.filter(
                ETFDailyPrice.etf_id == etf.id,
                ETFDailyPrice.date >= cutoff_date
            ).order_by(ETFDailyPrice.date).all()
            
            if not daily_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen dziennych dla {ticker}'
                }), 404
            
            # Przygotowanie danych dla obliczeń (używamy znormalizowanych cen z bazy)
            price_data = []
            for price in daily_prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),
                    'close': price.normalized_close_price  # Używamy znormalizowanej ceny z bazy
                })
            
            logger.info(f"Przygotowano {len(price_data)} cen dziennych dla MACD (8-17-9)")
            
            # Obliczanie MACD
            macd_data = api_service.calculate_macd(
                price_data, 
                fast_period=8, 
                slow_period=17, 
                signal_period=9
            )
            
            logger.info(f"Dzienny MACD (8-17-9) zwrócił: {len(macd_data) if macd_data else 0} punktów")
            
            if not macd_data:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się obliczyć dziennego MACD (8-17-9) dla {ticker}'
                }), 500
            
            # Formatowanie danych dla frontend
            formatted_data = []
            for data in macd_data:
                formatted_data.append({
                    'date': data['date'],
                    'macd_line': round(data['macd_line'], 4),
                    'signal_line': round(data['signal_line'], 4),
                    'histogram': round(data['histogram'], 4),
                    'current_price': round(data['current_price'], 2)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'daily_macd': formatted_data,
                    'count': len(formatted_data),
                    'parameters': {
                        'fast_period': 8,
                        'slow_period': 17,
                        'signal_period': 9
                    },
                    'date_range': {
                        'start': formatted_data[0]['date'] if formatted_data else None,
                        'end': formatted_data[-1]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF daily MACD for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/daily-stochastic', methods=['GET'])
    def get_etf_daily_stochastic(ticker):
        """API endpoint do pobierania Stochastic Oscillator dla cen dziennych ETF (36-12-12)"""
        try:
            from models import ETF, ETFDailyPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen dziennych z bazy danych (ostatnie 365 dni)
            cutoff_date = date.today() - timedelta(days=365)
            daily_prices = ETFDailyPrice.query.filter(
                ETFDailyPrice.etf_id == etf.id,
                ETFDailyPrice.date >= cutoff_date
            ).order_by(ETFDailyPrice.date).all()
            
            if not daily_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen dziennych dla {ticker}'
                }), 404
            
            # Przygotowanie danych dla obliczeń (używamy znormalizowanych cen z bazy)
            price_data = []
            for price in daily_prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),
                    'close': price.normalized_close_price  # Używamy znormalizowanej ceny z bazy
                })
            
            logger.info(f"Przygotowano {len(price_data)} cen dziennych dla Stochastic Oscillator (36-12-12)")
            
            # Obliczanie Stochastic Oscillator
            stochastic_data = api_service.calculate_stochastic_oscillator(
                price_data, 
                lookback_period=36, 
                smoothing_factor=12, 
                sma_period=12
            )
            
            logger.info(f"Dzienny Stochastic Oscillator (36-12-12) zwrócił: {len(stochastic_data) if stochastic_data else 0} punktów")
            
            if not stochastic_data:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się obliczyć dziennego Stochastic Oscillator (36-12-12) dla {ticker}'
                }), 500
            
            # Formatowanie danych dla frontend
            formatted_data = []
            for data in stochastic_data:
                formatted_data.append({
                    'date': data['date'],
                    'k_percent': round(data['k_percent_smoothed'], 2),
                    'd_percent': round(data['d_percent'], 2),
                    'current_price': round(data['current_price'], 2),
                    'highest_high': round(data['highest_high'], 2),
                    'lowest_low': round(data['lowest_low'], 2)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'daily_stochastic': formatted_data,
                    'count': len(formatted_data),
                    'parameters': {
                        'lookback_period': 36,
                        'smoothing_factor': 12,
                        'sma_period': 12
                    },
                    'date_range': {
                        'start': formatted_data[0]['date'] if formatted_data else None,
                        'end': formatted_data[-1]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF daily Stochastic for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/etfs/<ticker>/daily-stochastic-short', methods=['GET'])
    def get_etf_daily_stochastic_short(ticker):
        """API endpoint do pobierania krótkiego Stochastic Oscillator dla cen dziennych ETF (9-3-3)"""
        try:
            from models import ETF, ETFDailyPrice
            from services.database_service import DatabaseService
            
            # Sprawdzanie czy ETF istnieje
            etf = ETF.query.filter_by(ticker=ticker.upper()).first()
            if not etf:
                return jsonify({
                    'success': False,
                    'error': f'ETF {ticker} nie został znaleziony'
                }), 404
            
            # Pobieranie cen dziennych z bazy danych (ostatnie 365 dni)
            cutoff_date = date.today() - timedelta(days=365)
            daily_prices = ETFDailyPrice.query.filter(
                ETFDailyPrice.etf_id == etf.id,
                ETFDailyPrice.date >= cutoff_date
            ).order_by(ETFDailyPrice.date).all()
            
            if not daily_prices:
                return jsonify({
                    'success': False,
                    'error': f'Brak danych cen dziennych dla {ticker}'
                }), 404
            
            # Przygotowanie danych dla obliczeń (używamy znormalizowanych cen z bazy)
            price_data = []
            for price in daily_prices:
                price_data.append({
                    'date': price.date.strftime('%Y-%m-%d'),
                    'close': price.normalized_close_price  # Używamy znormalizowanej ceny z bazy
                })
            
            logger.info(f"Przygotowano {len(price_data)} cen dziennych dla Stochastic Oscillator (9-3-3)")
            
            # Obliczanie Stochastic Oscillator
            stochastic_data = api_service.calculate_stochastic_oscillator(
                price_data, 
                lookback_period=9, 
                smoothing_factor=3, 
                sma_period=3
            )
            
            logger.info(f"Dzienny Stochastic Oscillator (9-3-3) zwrócił: {len(stochastic_data) if stochastic_data else 0} punktów")
            
            if not stochastic_data:
                return jsonify({
                    'success': False,
                    'error': f'Nie udało się obliczyć dziennego Stochastic Oscillator (9-3-3) dla {ticker}'
                }), 500
            
            # Formatowanie danych dla frontend
            formatted_data = []
            for data in stochastic_data:
                formatted_data.append({
                    'date': data['date'],
                    'k_percent': round(data['k_percent_smoothed'], 2),
                    'd_percent': round(data['d_percent'], 2),
                    'current_price': round(data['current_price'], 2),
                    'highest_high': round(data['highest_high'], 2),
                    'lowest_low': round(data['lowest_low'], 2)
                })
            
            return jsonify({
                'success': True,
                'data': {
                    'ticker': ticker.upper(),
                    'daily_stochastic': formatted_data,
                    'count': len(formatted_data),
                    'parameters': {
                        'lookback_period': 9,
                        'smoothing_factor': 3,
                        'sma_period': 3
                    },
                    'date_range': {
                        'start': formatted_data[0]['date'] if formatted_data else None,
                        'end': formatted_data[-1]['date'] if formatted_data else None
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting ETF daily Stochastic Short for {ticker}: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/system/status')
    def system_status():
        """Strona statusu systemu"""
        try:
            # Pobieranie statusu schedulera
            scheduler_status = "Unknown"
            if hasattr(app, 'scheduler') and app.scheduler:
                try:
                    jobs = app.scheduler.get_jobs()
                    scheduler_status = f"Active with {len(jobs)} jobs"
                except:
                    scheduler_status = "Error getting status"
            
            # Pobieranie limitów API
            api_limits = {}
            try:
                api_service = APIService()
                api_limits = api_service.get_api_status()
            except Exception as e:
                logger.error(f"Error getting API limits: {str(e)}")
                api_limits = {}
            

            
            # Sprawdzanie kompletności danych ETF
            etfs = db_service.get_all_etfs()
            etfs_completeness = []
            
            for etf in etfs[:5]:  # Sprawdź pierwsze 5 ETF dla wydajności
                completeness = db_service.verify_data_completeness(etf.id, etf.ticker)
                etfs_completeness.append({
                    'ticker': etf.ticker,
                    'prices_complete': completeness['prices_complete'],
                    'dividends_complete': completeness['dividends_complete'],
                    'years_of_price_data': round(completeness['years_of_price_data'], 1),
                    'years_of_dividend_data': round(completeness['years_of_dividend_data'], 1),
                    'etf_age_years': completeness['etf_age_years'],
                    'expected_years': completeness['expected_years']
                })
            
            return render_template('system_status.html',
                                 scheduler_status=scheduler_status,
                                 api_limits=api_limits,
                                 etfs_completeness=etfs_completeness,
                                 total_etfs=len(etfs))
        except Exception as e:
            logger.error(f"Error loading system status: {str(e)}")
            return render_template('error.html', error=str(e))

    @app.route('/alerts')
    def alerts_page():
        """Strona zarządzania alertami"""
        try:
            return render_template('alerts.html')
        except Exception as e:
            logger.error(f"Error loading alerts page: {str(e)}")
            return render_template('error.html', error=str(e))
    
    # API endpoint do pobierania wersji systemu
    @app.route('/api/system/version')
    def get_system_version():
        """Zwraca wersję systemu"""
        try:
            from config import __version__
            return jsonify({
                'success': True,
                'version': __version__,
                'timestamp': utc_to_cet(datetime.now(timezone.utc)).isoformat()
            })
        except ImportError:
            return jsonify({
                'success': False,
                'error': 'Nie można zaimportować wersji systemu',
                'version': 'Błąd'
            }), 500
    
    # Test endpoint dla Slack webhook
    @app.route('/api/test/slack', methods=['POST'])
    def test_slack_webhook():
        """Test endpoint dla Slack webhook"""
        try:
            from services.notification_service import NotificationService
            from config import Config
            
            # Test bezpośredni Config
            config = Config()
            logger.info(f"Config test - SLACK_WEBHOOK_URL: {config.SLACK_WEBHOOK_URL}")
            logger.info(f"Config test - SLACK_CHANNEL: {config.SLACK_CHANNEL}")
            logger.info(f"Config test - SLACK_USERNAME: {config.SLACK_USERNAME}")
            
            notification_service = NotificationService(config)
            
            # Testowe powiadomienie
            test_message = "🧪 Test powiadomienia Slack z ETF Analyzer v1.9.20"
            notification_service.send_slack_notification(0, test_message, 'info')
            
            return jsonify({
                'success': True,
                'message': 'Test powiadomienia Slack wysłany',
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error testing Slack webhook: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    

    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'success': False,
            'error': 'Resource not found'
        }), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500
    
    # Ustawienie czasu startu aplikacji
    app.start_time = datetime.now(timezone.utc)
    
    @app.route('/api/alerts', methods=['GET'])
    def get_alerts():
        """Pobiera listę wszystkich alertów"""
        try:
            from models import AlertConfig, AlertHistory
            from services.notification_service import NotificationService
            from config import Config
            
            config = Config()
            notification_service = NotificationService(config)
            
            # Pobierz konfiguracje alertów
            alert_configs = AlertConfig.query.all()
            configs_data = []
            
            for config in alert_configs:
                configs_data.append({
                    'id': config.id,
                    'name': config.name,
                    'type': config.type,
                    'indicator': config.indicator,
                    'alert_type': config.alert_type,
                    'etf_ticker': config.etf_ticker,
                    'conditions': config.conditions,
                    'enabled': config.enabled,
                    'created_at': config.created_at.isoformat() if config.created_at else None,
                    'updated_at': config.updated_at.isoformat() if config.updated_at else None
                })
            
            # Pobierz historię alertów
            alert_history = AlertHistory.query.order_by(AlertHistory.triggered_at.desc()).limit(50).all()
            history_data = []
            
            for alert in alert_history:
                history_data.append({
                    'id': alert.id,
                    'alert_config_id': alert.alert_config_id,
                    'etf_ticker': alert.etf_ticker,
                    'message': alert.message,
                    'severity': alert.severity,
                    'priority': alert.priority,
                    'triggered_at': alert.triggered_at.isoformat() if alert.triggered_at else None,
                    'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
                    'status': alert.status
                })
            
            return jsonify({
                'success': True,
                'configs': configs_data,
                'history': history_data
            })
            
        except Exception as e:
            logger.error(f"Error getting alerts: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/alerts', methods=['POST'])
    def create_alert():
        """Tworzy nową regułę alertu"""
        try:
            from models import AlertConfig, db
            from config import Config
            
            data = request.get_json()
            
            # Walidacja danych
            required_fields = ['name', 'type', 'conditions']
            for field in required_fields:
                if field not in data:
                    return jsonify({
                        'success': False,
                        'error': f'Brak wymaganego pola: {field}'
                    }), 400
            
            # Sprawdź czy nazwa już istnieje
            existing_alert = AlertConfig.query.filter_by(name=data['name']).first()
            if existing_alert:
                return jsonify({
                    'success': False,
                    'error': f'Alert o nazwie "{data["name"]}" już istnieje'
                }), 400
            
            # Utwórz nową regułę alertu
            new_alert = AlertConfig(
                name=data['name'],
                type=data['type'],
                indicator=data.get('indicator'),
                alert_type=data.get('alert_type'),
                etf_ticker=data.get('etf_ticker'),
                conditions=data['conditions'],
                enabled=data.get('enabled', True)
            )
            
            db.session.add(new_alert)
            db.session.commit()
            
            logger.info(f"Utworzono nową regułę alertu: {data['name']}")
            
            return jsonify({
                'success': True,
                'message': f'Reguła alertu "{data["name"]}" została utworzona',
                'alert_id': new_alert.id
            })
            
        except Exception as e:
            logger.error(f"Error creating alert: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/alerts/<int:alert_id>', methods=['PUT'])
    def update_alert(alert_id):
        """Aktualizuje regułę alertu"""
        try:
            from models import AlertConfig, db
            
            alert = AlertConfig.query.get(alert_id)
            if not alert:
                return jsonify({
                    'success': False,
                    'error': f'Alert o ID {alert_id} nie został znaleziony'
                }), 404
            
            data = request.get_json()
            
            # Aktualizuj pola
            if 'name' in data:
                alert.name = data['name']
            if 'type' in data:
                alert.type = data['type']
            if 'indicator' in data:
                alert.indicator = data['indicator']
            if 'alert_type' in data:
                alert.alert_type = data['alert_type']
            if 'etf_ticker' in data:
                alert.etf_ticker = data['etf_ticker']
            if 'conditions' in data:
                alert.conditions = data['conditions']
            if 'enabled' in data:
                alert.enabled = data['enabled']
            
            alert.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            
            logger.info(f"Zaktualizowano regułę alertu: {alert.name}")
            
            return jsonify({
                'success': True,
                'message': f'Reguła alertu "{alert.name}" została zaktualizowana'
            })
            
        except Exception as e:
            logger.error(f"Error updating alert: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/alerts/<int:alert_id>', methods=['DELETE'])
    def delete_alert(alert_id):
        """Usuwa regułę alertu"""
        try:
            from models import AlertConfig, db
            
            alert = AlertConfig.query.get(alert_id)
            if not alert:
                return jsonify({
                    'success': False,
                    'error': f'Alert o ID {alert_id} nie został znaleziony'
                }), 404
            
            alert_name = alert.name
            db.session.delete(alert)
            db.session.commit()
            
            logger.info(f"Usunięto regułę alertu: {alert_name}")
            
            return jsonify({
                'success': True,
                'message': f'Reguła alertu "{alert_name}" została usunięta'
            })
            
        except Exception as e:
            logger.error(f"Error deleting alert: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/alerts/<int:alert_id>/toggle', methods=['POST'])
    def toggle_alert(alert_id):
        """Włącza/wyłącza regułę alertu"""
        try:
            from models import AlertConfig, db
            
            alert = AlertConfig.query.get(alert_id)
            if not alert:
                return jsonify({
                    'success': False,
                    'error': f'Alert o ID {alert_id} nie został znaleziony'
                }), 404
            
            alert.enabled = not alert.enabled
            alert.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            
            status = "włączona" if alert.enabled else "wyłączona"
            logger.info(f"Reguła alertu {alert.name} została {status}")
            
            return jsonify({
                'success': True,
                'message': f'Reguła alertu "{alert.name}" została {status}',
                'enabled': alert.enabled
            })
            
        except Exception as e:
            logger.error(f"Error toggling alert: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/alerts/technical-indicators', methods=['GET'])
    def get_technical_indicators():
        """Pobiera dostępne wskaźniki techniczne i ich typy alertów"""
        try:
            from config import Config
            
            config = Config()
            indicators = config.TECHNICAL_INDICATORS
            
            return jsonify({
                'success': True,
                'indicators': indicators
            })
            
        except Exception as e:
            logger.error(f"Error getting technical indicators: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # Error handlers
    
    return app

if __name__ == '__main__':
    app = create_app()
    # Używaj ustawień z Config (HOST/PORT) z możliwością nadpisania przez env
    host = app.config.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', app.config.get('PORT', 5005)))
    
    # Inteligentny debug mode - tylko w development
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    if debug_mode:
        logger.info("🚀 Uruchamianie w trybie DEBUG (development)")
    else:
        logger.info("🚀 Uruchamianie w trybie PRODUCTION")
    
    app.run(debug=debug_mode, host=host, port=port)
