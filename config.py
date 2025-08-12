import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///etf_analyzer.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # API Keys - PRIORYTET 1: FMP, BACKUP: EODHD, FALLBACK: Tiingo
    FMP_API_KEY = os.environ.get('FMP_API_KEY')
    EODHD_API_KEY = os.environ.get('EODHD_API_KEY')
    TIINGO_API_KEY = os.environ.get('TIINGO_API_KEY')

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
    
    # Cache settings
    CACHE_TTL_SECONDS = 3600  # 1 godzina
    
    # Retry settings
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 2  # seconds
