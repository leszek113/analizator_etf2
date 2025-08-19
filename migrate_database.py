#!/usr/bin/env python3
"""
Skrypt migracji bazy danych dla normalizacji splitów
Dodaje nowe kolumny do istniejących tabel i tworzy nową tabelę ETFSplit
"""

import sqlite3
import os
from datetime import datetime

def migrate_database():
    """Wykonuje migrację bazy danych"""
    
    db_path = 'instance/etf_analyzer.db'
    
    if not os.path.exists(db_path):
        print(f"Baza danych nie istnieje: {db_path}")
        return
    
    print("Rozpoczynam migrację bazy danych...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 1. Dodanie nowych kolumn do tabeli etf_dividends
        print("Dodaję kolumny do tabeli etf_dividends...")
        cursor.execute("""
            ALTER TABLE etf_dividends 
            ADD COLUMN normalized_amount REAL
        """)
        
        cursor.execute("""
            ALTER TABLE etf_dividends 
            ADD COLUMN split_ratio_applied REAL DEFAULT 1.0
        """)
        
        # 2. Dodanie nowych kolumn do tabeli etf_prices
        print("Dodaję kolumny do tabeli etf_prices...")
        cursor.execute("""
            ALTER TABLE etf_prices 
            ADD COLUMN normalized_close_price REAL
        """)
        
        cursor.execute("""
            ALTER TABLE etf_prices 
            ADD COLUMN split_ratio_applied REAL DEFAULT 1.0
        """)
        
        # 3. Tworzenie nowej tabeli etf_splits
        print("Tworzę tabelę etf_splits...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS etf_splits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                etf_id INTEGER NOT NULL,
                split_date DATE NOT NULL,
                split_ratio REAL NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (etf_id) REFERENCES etfs (id) ON DELETE CASCADE
            )
        """)
        
        # 4. Tworzenie indeksów
        print("Tworzę indeksy...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_etf_splits_etf_id 
            ON etf_splits (etf_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_etf_splits_split_date 
            ON etf_splits (split_date)
        """)
        
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_etf_splits_etf_date 
            ON etf_splits (etf_id, split_date)
        """)
        
        # 5. Inicjalizacja istniejących danych
        print("Inicjalizuję istniejące dane...")
        
        # Dla dywidend - ustaw normalized_amount = amount i split_ratio_applied = 1.0
        cursor.execute("""
            UPDATE etf_dividends 
            SET normalized_amount = amount, split_ratio_applied = 1.0
            WHERE normalized_amount IS NULL
        """)
        
        # Dla cen - ustaw normalized_close_price = close_price i split_ratio_applied = 1.0
        cursor.execute("""
            UPDATE etf_prices 
            SET normalized_close_price = close_price, split_ratio_applied = 1.0
            WHERE normalized_close_price IS NULL
        """)
        
        # 6. Dodanie hardcoded split dla SCHD
        print("Dodaję split dla SCHD...")
        cursor.execute("SELECT id FROM etfs WHERE ticker = 'SCHD'")
        schd_result = cursor.fetchone()
        
        if schd_result:
            schd_id = schd_result[0]
            cursor.execute("""
                INSERT OR IGNORE INTO etf_splits (etf_id, split_date, split_ratio, description)
                VALUES (?, '2024-10-11', 3.0, '3:1 Stock Split')
            """, (schd_id,))
            
            # Aktualizacja dywidend SCHD z 2023 i wcześniej
            print("Aktualizuję dywidendy SCHD...")
            cursor.execute("""
                UPDATE etf_dividends 
                SET normalized_amount = amount / 3.0, split_ratio_applied = 3.0
                WHERE etf_id = ? AND payment_date < '2024-10-11'
            """, (schd_id,))
            
            # Aktualizacja cen SCHD z 2023 i wcześniej
            print("Aktualizuję ceny SCHD...")
            cursor.execute("""
                UPDATE etf_prices 
                SET normalized_close_price = close_price / 3.0, split_ratio_applied = 3.0
                WHERE etf_id = ? AND date < '2024-10-11'
            """, (schd_id,))
        
        conn.commit()
        print("Migracja zakończona pomyślnie!")
        
        # 7. Sprawdzenie wyników
        print("\nSprawdzam wyniki migracji...")
        
        cursor.execute("SELECT COUNT(*) FROM etf_dividends WHERE normalized_amount IS NOT NULL")
        dividend_count = cursor.fetchone()[0]
        print(f"Dywidendy z normalized_amount: {dividend_count}")
        
        cursor.execute("SELECT COUNT(*) FROM etf_prices WHERE normalized_close_price IS NOT NULL")
        price_count = cursor.fetchone()[0]
        print(f"Ceny z normalized_close_price: {price_count}")
        
        cursor.execute("SELECT COUNT(*) FROM etf_splits")
        split_count = cursor.fetchone()[0]
        print(f"Splitów w bazie: {split_count}")
        
        if schd_result:
            cursor.execute("""
                SELECT amount, normalized_amount, split_ratio_applied 
                FROM etf_dividends 
                WHERE etf_id = ? AND payment_date < '2024-10-11' 
                LIMIT 3
            """, (schd_id,))
            
            schd_dividends = cursor.fetchall()
            print(f"\nPrzykłady dywidend SCHD (przed splitem):")
            for amount, normalized, ratio in schd_dividends:
                print(f"  Oryginalna: {amount}, Znormalizowana: {normalized}, Ratio: {ratio}")
        
    except Exception as e:
        print(f"Błąd podczas migracji: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()
