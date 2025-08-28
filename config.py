import os
from dotenv import load_dotenv

load_dotenv()

# Wersja systemu - CENTRALNE ŹRÓDŁO PRAWDY
__version__ = "1.9.22"

# Informacje o wersji
VERSION_INFO = {
    'version': __version__,
    'release_date': '2025-08-28',
    'status': 'production_ready',
    'build': '82169fc'  # Git commit hash
}

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///etf_analyzer.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Port settings
    PORT = 5005
    HOST = '127.0.0.1'

    # API Keys - PRIORYTET 1: FMP, BACKUP: EODHD, FALLBACK: Tiingo
    FMP_API_KEY = os.environ.get('FMP_API_KEY')
    EODHD_API_KEY = os.environ.get('EODHD_API_KEY')
    TIINGO_API_KEY = os.environ.get('TIINGO_API_KEY')
    
    # Notification Settings
    SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
    SLACK_CHANNEL = os.environ.get('SLACK_CHANNEL', '#etf-analyzer')
    SLACK_USERNAME = os.environ.get('SLACK_USERNAME', 'ETF Analyzer Bot')

    # Technical Indicators Configuration
    TECHNICAL_INDICATORS = {
        'stochastic': {
            'name': 'Stochastic Oscillator',
            'description': 'Wskaźnik stochastyczny',
            'preset_parameters': [
                {'name': 'Standard (9,3,3)', 'k': 9, 'd': 3, 'smooth': 3},
                {'name': 'Długoterminowy (36,12,12)', 'k': 36, 'd': 12, 'smooth': 12}
            ],
            'alert_types': {
                'level_below': {
                    'name': 'Poniżej poziomu',
                    'description': 'Wskaźnik spadł poniżej określonego poziomu',
                    'fields': ['threshold', 'timeframe']
                },
                'level_above': {
                    'name': 'Powyżej poziomu', 
                    'description': 'Wskaźnik wzrósł powyżej określonego poziomu',
                    'fields': ['threshold', 'timeframe']
                },
                'crossover_in_oversold': {
                    'name': 'Przecięcie w obszarze oversold (20%)',
                    'description': 'Linia %K przecina linię %D w obszarze poniżej 20%',
                    'fields': ['timeframe']
                },
                'crossover_in_overbought': {
                    'name': 'Przecięcie w obszarze overbought (80%)',
                    'description': 'Linia %K przecina linię %D w obszarze powyżej 80%',
                    'fields': ['timeframe']
                },
                'crossover_general': {
                    'name': 'Przecięcie (ogólne)',
                    'description': 'Linia %K przecina linię %D w dowolnym obszarze',
                    'fields': ['timeframe']
                }
            }
        },
        'macd': {
            'name': 'MACD',
            'description': 'Moving Average Convergence Divergence',
            'preset_parameters': [
                {'name': 'Standard (12,26,9)', 'fast': 12, 'slow': 26, 'signal': 9}
            ],
            'alert_types': {
                'crossover_bullish': {
                    'name': 'Przecięcie w górę (bullish)',
                    'description': 'Linia MACD przecina linię sygnału w górę',
                    'fields': ['timeframe']
                },
                'crossover_bearish': {
                    'name': 'Przecięcie w dół (bearish)', 
                    'description': 'Linia MACD przecina linię sygnału w dół',
                    'fields': ['timeframe']
                }
            }
        }
    }

    # Base URLs
    FMP_BASE_URL = 'https://financialmodelingprep.com/api/v3'
    EODHD_BASE_URL = 'https://eodhistoricaldata.com/api'
    TIINGO_BASE_URL = 'https://api.tiingo.com/tiingo/daily'

    # Scheduler settings
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = 'UTC'

    # Data settings
    MAX_HISTORY_YEARS = 15
    DIVIDEND_CHECK_INTERVAL_HOURS = 24
    
    # Timeframe settings
    DAILY_PRICES_WINDOW_DAYS = 365  # Rolling window dla cen dziennych
    WEEKLY_PRICES_WINDOW_DAYS = 780  # 15 lat * 52 tygodnie
    MONTHLY_PRICES_WINDOW_DAYS = 5475  # 15 lat * 365 dni
    
    # Cache settings
    CACHE_TTL_SECONDS = 3600  # 1 godzina
    
    # Logging settings
    DEBUG_LEVEL = os.environ.get('DEBUG_LEVEL', 'INFO')  # DEBUG, INFO, WARNING, ERROR
    ENABLE_DEBUG_LOGS = os.environ.get('ENABLE_DEBUG_LOGS', 'False').lower() == 'true'
    
    # Retry settings
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 0.5  # seconds - zmniejszone z 2 na 0.5
    
    # Known splits configuration
    KNOWN_SPLITS = {
        'SCHD': [
            {
                'date': '2024-10-11',
                'ratio': 3.0,
                'description': '3:1 Stock Split'
            }
        ]
        # Dodaj więcej ETF z splitami tutaj
    }
