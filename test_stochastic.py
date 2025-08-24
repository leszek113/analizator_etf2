#!/usr/bin/env python3
"""
Test funkcji calculate_stochastic_oscillator
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.api_service import APIService

def test_stochastic():
    print("🧪 Test funkcji calculate_stochastic_oscillator")
    
    # Inicjalizacja APIService
    api_service = APIService()
    
    # Testowe dane (261 cen tygodniowych jak w SCHD)
    test_prices = []
    for i in range(261):
        date_str = f"2020-{((i // 4) % 12) + 1:02d}-{((i % 4) * 7) + 1:02d}"
        price = 20.0 + (i % 10) * 0.5  # Ceny od 20.0 do 24.5
        test_prices.append({
            'date': date_str,
            'close': price
        })
    
    print(f"📊 Utworzono {len(test_prices)} testowych cen")
    print(f"📅 Zakres dat: {test_prices[0]['date']} do {test_prices[-1]['date']}")
    print(f"💰 Przykładowe ceny: {test_prices[0]['close']}, {test_prices[10]['close']}, {test_prices[100]['close']}")
    
    # Test funkcji
    print("\n🔍 Testuję funkcję calculate_stochastic_oscillator...")
    try:
        result = api_service.calculate_stochastic_oscillator(
            test_prices,
            lookback_period=36,
            smoothing_factor=12,
            sma_period=12
        )
        
        print(f"✅ Funkcja zwróciła {len(result)} punktów")
        
        if result:
            print(f"📈 Pierwszy punkt: {result[0]}")
            print(f"📉 Ostatni punkt: {result[-1]}")
            
            # Sprawdź czy mamy %K i %D
            first_point = result[0]
            if 'k_percent_smoothed' in first_point and 'd_percent' in first_point:
                print("✅ Wszystkie wymagane pola są obecne")
            else:
                print("❌ Brakuje wymaganych pól")
                print(f"   Dostępne pola: {list(first_point.keys())}")
        else:
            print("❌ Funkcja zwróciła pustą listę")
            
    except Exception as e:
        print(f"❌ Błąd podczas testu: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_stochastic()
