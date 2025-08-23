#!/usr/bin/env python3
"""
Skrypt testowy dla ETF Analyzer
Sprawdza podstawowe funkcjonalności systemu
"""

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:5005"

def test_api_connection():
    """Test połączenia z API"""
    print("🔌 Test połączenia z API...")
    try:
        response = requests.get(f"{BASE_URL}/api/system/status", timeout=10)
        if response.status_code == 200:
            print("✅ Połączenie z API udane")
            return True
        else:
            print(f"❌ Błąd API: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Błąd połączenia: {e}")
        return False

def test_system_status():
    """Test statusu systemu"""
    print("\n📊 Test statusu systemu...")
    try:
        response = requests.get(f"{BASE_URL}/api/system/status")
        if response.status_code == 200:
            data = response.json()
            if data['success']:
                status = data['data']
                print(f"✅ Status systemu:")
                print(f"   - ETF w bazie: {status['etf_count']}")
                print(f"   - Rekordy cen: {status['price_count']}")
                print(f"   - Rekordy dywidend: {status['dividend_count']}")
                print(f"   - Logi systemu: {status['log_count']}")
                print(f"   - Scheduler: {'Aktywny' if status['scheduler_running'] else 'Nieaktywny'}")
                return True
            else:
                print(f"❌ Błąd API: {data['error']}")
                return False
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

def test_add_etf(ticker="SPY"):
    """Test dodawania ETF"""
    print(f"\n➕ Test dodawania ETF: {ticker}")
    try:
        data = {"ticker": ticker}
        response = requests.post(
            f"{BASE_URL}/api/etfs",
            json=data,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            if result['success']:
                print(f"✅ ETF {ticker} dodany pomyślnie")
                print(f"   - Nazwa: {result['data']['name']}")
                print(f"   - Cena: ${result['data']['current_price']}")
                print(f"   - Yield: {result['data']['current_yield']}%")
                return True
            else:
                print(f"❌ Błąd dodawania: {result['error']}")
                return False
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

def test_get_etfs():
    """Test pobierania listy ETF"""
    print("\n📋 Test pobierania listy ETF...")
    try:
        response = requests.get(f"{BASE_URL}/api/etfs")
        if response.status_code == 200:
            result = response.json()
            if result['success']:
                etfs = result['data']
                print(f"✅ Pobrano {len(etfs)} ETF:")
                for etf in etfs:
                    print(f"   - {etf['ticker']}: {etf['name']} (${etf['current_price']})")
                return True
            else:
                print(f"❌ Błąd API: {result['error']}")
                return False
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

def test_get_etf_details(ticker="SPY"):
    """Test pobierania szczegółów ETF"""
    print(f"\n🔍 Test szczegółów ETF: {ticker}")
    try:
        response = requests.get(f"{BASE_URL}/api/etfs/{ticker}")
        if response.status_code == 200:
            result = response.json()
            if result['success']:
                etf = result['data']
                print(f"✅ Szczegóły ETF {ticker}:")
                print(f"   - Nazwa: {etf['name']}")
                print(f"   - Cena: ${etf['current_price']}")
                print(f"   - Yield: {etf['current_yield']}%")
                print(f"   - Częstotliwość: {etf['frequency']}")
                return True
            else:
                print(f"❌ Błąd API: {result['error']}")
                return False
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

def test_get_prices(ticker="SPY"):
    """Test pobierania historii cen"""
    print(f"\n📈 Test historii cen ETF: {ticker}")
    try:
        response = requests.get(f"{BASE_URL}/api/etfs/{ticker}/prices?limit=5")
        if response.status_code == 200:
            result = response.json()
            if result['success']:
                prices = result['data']
                print(f"✅ Pobrano {len(prices)} ostatnich cen:")
                for price in prices[:3]:  # Pokaż tylko 3 ostatnie
                    print(f"   - {price['date']}: ${price['close_price']}")
                return True
            else:
                print(f"❌ Błąd API: {result['error']}")
                return False
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

def test_get_dividends(ticker="SPY"):
    """Test pobierania historii dywidend"""
    print(f"\n💰 Test historii dywidend ETF: {ticker}")
    try:
        response = requests.get(f"{BASE_URL}/api/etfs/{ticker}/dividends?limit=5")
        if response.status_code == 200:
            result = response.json()
            if result['success']:
                dividends = result['data']
                print(f"✅ Pobrano {len(dividends)} ostatnich dywidend:")
                for div in dividends[:3]:  # Pokaż tylko 3 ostatnie
                    print(f"   - {div['payment_date']}: ${div['amount']}")
                return True
            else:
                print(f"❌ Błąd API: {result['error']}")
                return False
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

def test_update_etf(ticker="SPY"):
    """Test aktualizacji ETF"""
    print(f"\n🔄 Test aktualizacji ETF: {ticker}")
    try:
        response = requests.post(f"{BASE_URL}/api/etfs/{ticker}/update")
        if response.status_code == 200:
            result = response.json()
            if result['success']:
                print(f"✅ ETF {ticker} zaktualizowany pomyślnie")
                return True
            else:
                print(f"❌ Błąd aktualizacji: {result['error']}")
                return False
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

def test_dashboard():
    """Test dostępu do dashboardu"""
    print("\n🌐 Test dostępu do dashboardu...")
    try:
        response = requests.get(f"{BASE_URL}/")
        if response.status_code == 200:
            print("✅ Dashboard dostępny")
            return True
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

def run_all_tests():
    """Uruchomienie wszystkich testów"""
    print("🚀 Uruchamianie testów ETF Analyzer")
    print("=" * 50)
    
    tests = [
        ("Połączenie z API", test_api_connection),
        ("Status systemu", test_system_status),
        ("Dashboard", test_dashboard),
        ("Dodawanie ETF", lambda: test_add_etf("SPY")),
        ("Lista ETF", test_get_etfs),
        ("Szczegóły ETF", lambda: test_get_etf_details("SPY")),
        ("Historia cen", lambda: test_get_prices("SPY")),
        ("Historia dywidend", lambda: test_get_dividends("SPY")),
        ("Aktualizacja ETF", lambda: test_update_etf("SPY")),
        ("Usuwanie ETF", lambda: test_delete_etf("VTI"))
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
            time.sleep(1)  # Krótka przerwa między testami
        except Exception as e:
            print(f"❌ Test '{test_name}' nieoczekiwanie się zakończył: {e}")
    
    print("\n" + "=" * 50)
    print(f"📊 Wyniki testów: {passed}/{total} pomyślnych")
    
    if passed == total:
        print("🎉 Wszystkie testy przeszły pomyślnie!")
        return True
    else:
        print("⚠️  Niektóre testy nie przeszły")
        return False

def test_delete_etf(ticker):
    """Test usuwania ETF"""
    print(f"\n🗑️ Test usuwania ETF: {ticker}")
    try:
        response = requests.delete(f"{BASE_URL}/api/etfs/{ticker}")
        
        if response.status_code == 200:
            result = response.json()
            if result['success']:
                print(f"✅ ETF {ticker} został usunięty pomyślnie")
                return True
            else:
                print(f"❌ Błąd usuwania: {result['error']}")
                return False
        else:
            print(f"❌ Błąd HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

if __name__ == "__main__":
    print("ETF Analyzer - System Test")
    print("Upewnij się, że aplikacja jest uruchomiona na http://localhost:5005")
    print()
    
    try:
        success = run_all_tests()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏹️  Testy przerwane przez użytkownika")
        exit(1)
    except Exception as e:
        print(f"\n\n💥 Nieoczekiwany błąd: {e}")
        exit(1)
