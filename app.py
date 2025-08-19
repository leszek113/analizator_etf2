from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import logging
import os

from config import Config
from models import db
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
    
    # Pobieranie portu i hosta z konfiguracji
    port = app.config.get('PORT', 5005)
    host = app.config.get('HOST', '127.0.0.1')
    
    # Inicjalizacja rozszerzeń
    db.init_app(app)
    CORS(app)
    
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
    
    # Dodawanie zadań do schedulera
    def update_all_etfs():
        with app.app_context():
            try:
                etfs = db_service.get_all_etfs()
                updated_count = 0
                for etf in etfs:
                    if db_service.update_etf_data(etf.ticker):
                        updated_count += 1
                
                logger.info(f"Updated {updated_count} out of {len(etfs)} ETFs")
                
                # Czyszczenie starych logów
                db_service.cleanup_old_data()
                
            except Exception as e:
                logger.error(f"Error in scheduled update: {str(e)}")
    
    # Uruchamianie aktualizacji raz dziennie o 9:00 UTC
    scheduler.add_job(
        func=update_all_etfs,
        trigger="cron",
        hour=9,
        minute=0,
        id="daily_etf_update"
    )
    
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
            dividend_sum = db_service.calculate_recent_dividend_sum(etf.id, etf.frequency)
            
            return render_template('etf_details.html', 
                                 etf=etf, 
                                 dividends=dividends,
                                 dividend_sum=dividend_sum)
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
            
            # Sprawdzanie parametru force_update
            force_update = request.args.get('force', 'false').lower() == 'true'
            
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
            from models import ETF, ETFPrice, ETFDividend, SystemLog
            
            etf_count = ETF.query.count()
            price_count = ETFPrice.query.count()
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
                    'dividend_count': dividend_count,
                    'log_count': log_count,
                    'last_update': last_update.isoformat() if last_update else None,
                    'scheduler_running': scheduler.running,
                    'uptime': str(datetime.utcnow() - app.start_time) if hasattr(app, 'start_time') else 'Unknown',
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
                    'timestamp': datetime.utcnow().isoformat()
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting API token status: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/system/status')
    def system_status_page():
        """Strona z systemowymi informacjami"""
        try:
            from models import ETF, ETFPrice, ETFDividend, SystemLog
            from services.api_service import APIService
            
            # Pobieranie statystyk systemu
            etf_count = ETF.query.count()
            price_count = ETFPrice.query.count()
            dividend_count = ETFDividend.query.count()
            log_count = SystemLog.query.count()
            
            # Sprawdzanie ostatniej aktualizacji
            latest_update = ETF.query.order_by(ETF.last_updated.desc()).first()
            last_update = latest_update.last_updated if latest_update else None
            
            # Status tokenów API
            api_health = {}
            api_status = {}
            try:
                api_service = APIService()
                api_health = api_service.check_api_health()
                api_status = api_service.get_api_status()  # Dodanie pełnego statusu API
            except Exception as e:
                api_health = {'error': str(e)}
                api_status = {'error': str(e)}
            
            return render_template('system_status.html', 
                                etf_count=etf_count,
                                price_count=price_count,
                                dividend_count=dividend_count,
                                log_count=log_count,
                                last_update=last_update,
                                api_health=api_health,
                                api_status=api_status)  # Przekazanie minutowych limitów
            
        except Exception as e:
            logger.error(f"Error rendering system status page: {str(e)}")
            return render_template('error.html', error=str(e))
    
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
    app.start_time = datetime.utcnow()
    
    return app

if __name__ == '__main__':
    app = create_app()
    # Używaj ustawień z Config (HOST/PORT) z możliwością nadpisania przez env
    host = app.config.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', app.config.get('PORT', 5005)))
    app.run(debug=True, host=host, port=port)
