"""
Wspólne funkcje pomocnicze dla ETF Analyzer
"""

from datetime import datetime, timezone
import pytz

def utc_to_cet(utc_datetime):
    """Konwertuje datetime UTC na CET/CEST"""
    if utc_datetime is None:
        return None
    if utc_datetime.tzinfo is None:
        utc_datetime = utc_datetime.replace(tzinfo=timezone.utc)
    cet_tz = pytz.timezone('Europe/Warsaw')
    return utc_datetime.astimezone(cet_tz)
