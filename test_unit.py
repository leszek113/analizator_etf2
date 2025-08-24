#!/usr/bin/env python3
"""
Testy jednostkowe dla ETF Analyzer
Testuje kluczowe funkcje bez zewnętrznych zależności
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date, timezone
import sys
import os

# Dodaj katalog główny do ścieżki
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

class TestAPIService(unittest.TestCase):
    """Testy dla APIService"""
    
    def setUp(self):
        """Przygotowanie testów"""
        from services.api_service import APIService
        self.api_service = APIService()
    
    def test_check_rate_limit_fmp(self):
        """Test sprawdzania rate limitu dla FMP"""
        # Mock API calls
        self.api_service.api_calls = {
            'fmp': {
                'count': 4,
                'daily_limit': 500,
                'last_reset': datetime.now(),
                'minute_count': 4,
                'minute_reset': datetime.now()
            }
        }
        
        # Test - możemy wykonać wywołanie
        result = self.api_service._check_rate_limit('fmp')
        self.assertTrue(result)
    
    def test_check_rate_limit_exceeded(self):
        """Test przekroczenia rate limitu"""
        # Mock API calls z przekroczonym limitem
        self.api_service.api_calls = {
            'fmp': {
                'count': 500,
                'daily_limit': 500,
                'last_reset': datetime.now(),
                'minute_count': 0,
                'minute_reset': datetime.now()
            }
        }
        
        # Test - nie możemy wykonać wywołania
        result = self.api_service._check_rate_limit('fmp')
        self.assertFalse(result)
    
    def test_increment_api_call(self):
        """Test zwiększania licznika API calls"""
        # Mock API calls
        self.api_service.api_calls = {
            'fmp': {
                'count': 0,
                'daily_limit': 500,
                'last_reset': datetime.now(),
                'minute_count': 0,
                'minute_reset': datetime.now()
            }
        }
        
        # Test zwiększania licznika
        self.api_service._increment_api_call('fmp')
        self.assertEqual(self.api_service.api_calls['fmp']['count'], 1)
        self.assertEqual(self.api_service.api_calls['fmp']['minute_count'], 1)

class TestDatabaseService(unittest.TestCase):
    """Testy dla DatabaseService"""
    
    def setUp(self):
        """Przygotowanie testów"""
        from services.database_service import DatabaseService
        self.db_service = DatabaseService()
    
    def test_validate_ticker_valid(self):
        """Test walidacji poprawnego ticker"""
        # Test poprawnego ticker
        ticker = "SPY"
        result = self.db_service._validate_ticker(ticker)
        self.assertTrue(result)
    
    def test_validate_ticker_invalid(self):
        """Test walidacji niepoprawnego ticker"""
        # Test niepoprawnego ticker
        ticker = ""
        result = self.db_service._validate_ticker(ticker)
        self.assertFalse(result)
        
        ticker = "A" * 25  # Za długi
        result = self.db_service._validate_ticker(ticker)
        self.assertFalse(result)
    
    def test_calculate_dividend_growth_forecast(self):
        """Test obliczania prognozy wzrostu dywidendy"""
        # Mock ETF i dywidendy
        mock_etf = Mock()
        mock_etf.id = 1
        
        # Test z danymi testowymi
        with patch.object(self.db_service, 'get_etf_dividends') as mock_get_dividends:
            mock_get_dividends.return_value = [
                Mock(payment_date=date(2024, 1, 1), normalized_amount=0.5),
                Mock(payment_date=date(2024, 2, 1), normalized_amount=0.5),
                Mock(payment_date=date(2023, 1, 1), normalized_amount=0.4),
                Mock(payment_date=date(2023, 2, 1), normalized_amount=0.4),
            ]
            
            result = self.db_service.calculate_dividend_growth_forecast(1, 'monthly')
            self.assertIsInstance(result, float)
            self.assertGreater(result, 0)  # Powinien być wzrost

class TestModels(unittest.TestCase):
    """Testy dla modeli bazy danych"""
    
    def test_etf_to_dict(self):
        """Test konwersji ETF na dict"""
        from models import ETF
        from datetime import datetime, timezone
        
        # Tworzenie mock ETF
        etf = ETF(
            id=1,
            ticker="SPY",
            name="SPDR S&P 500 ETF Trust",
            current_price=500.0,
            current_yield=1.2,
            frequency="monthly",
            inception_date=date(1993, 1, 29),
            last_updated=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc)
        )
        
        # Test konwersji
        etf_dict = etf.to_dict()
        self.assertEqual(etf_dict['ticker'], "SPY")
        self.assertEqual(etf_dict['name'], "SPDR S&P 500 ETF Trust")
        self.assertEqual(etf_dict['current_price'], 500.0)
        self.assertIsInstance(etf_dict['last_updated'], str)
        self.assertIsInstance(etf_dict['created_at'], str)

class TestUtilityFunctions(unittest.TestCase):
    """Testy dla funkcji pomocniczych"""
    
    def test_utc_to_cet_conversion(self):
        """Test konwersji UTC na CET"""
        from models import utc_to_cet
        from datetime import datetime, timezone
        
        # Test konwersji
        utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        cet_time = utc_to_cet(utc_time)
        
        self.assertIsNotNone(cet_time)
        self.assertNotEqual(utc_time, cet_time)
        
        # CET powinno być o 1-2 godziny później niż UTC
        time_diff = (cet_time - utc_time).total_seconds() / 3600
        self.assertGreaterEqual(time_diff, 1)
        self.assertLessEqual(time_diff, 2)

def run_tests():
    """Uruchamia wszystkie testy"""
    # Tworzenie test suite
    loader = unittest.TestLoader()
    suite = loader.discover('.', pattern='test_unit.py')
    
    # Uruchamianie testów
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Zwracanie wyniku
    return result.wasSuccessful()

if __name__ == '__main__':
    print("🧪 Uruchamianie testów jednostkowych ETF Analyzer...")
    print("=" * 50)
    
    success = run_tests()
    
    if success:
        print("\n✅ Wszystkie testy przeszły pomyślnie!")
    else:
        print("\n❌ Niektóre testy nie przeszły!")
    
    print("\n🎯 Testy zakończone!")
