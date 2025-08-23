#!/usr/bin/env python3
"""
Skrypt migracji bazy danych dla ETF Analyzer
Dodaje nowe pola do tabeli system_logs dla logowania zadań schedulera
"""

import os
import sys
from sqlalchemy import text
from datetime import datetime, timezone

# Dodaj katalog główny do ścieżki
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from models import db

def migrate_system_logs_table():
    """Migruje tabelę system_logs dodając nowe pola dla zadań schedulera"""
    app = create_app()
    
    with app.app_context():
        try:
            print("🔧 Rozpoczynam migrację tabeli system_logs...")
            
            # Sprawdź czy nowe kolumny już istnieją
            inspector = db.inspect(db.engine)
            existing_columns = [col['name'] for col in inspector.get_columns('system_logs')]
            
            new_columns = [
                'job_name',
                'execution_time_ms', 
                'records_processed',
                'success',
                'error_message'
            ]
            
            missing_columns = [col for col in new_columns if col not in existing_columns]
            
            if not missing_columns:
                print("✅ Wszystkie kolumny już istnieją - migracja nie jest potrzebna")
                return
            
            print(f"📋 Dodaję brakujące kolumny: {', '.join(missing_columns)}")
            
            # Dodaj nowe kolumny
            for column in missing_columns:
                if column == 'job_name':
                    sql = text("ALTER TABLE system_logs ADD COLUMN job_name VARCHAR(100)")
                elif column == 'execution_time_ms':
                    sql = text("ALTER TABLE system_logs ADD COLUMN execution_time_ms INTEGER")
                elif column == 'records_processed':
                    sql = text("ALTER TABLE system_logs ADD COLUMN records_processed INTEGER")
                elif column == 'success':
                    sql = text("ALTER TABLE system_logs ADD COLUMN success BOOLEAN DEFAULT TRUE")
                elif column == 'error_message':
                    sql = text("ALTER TABLE system_logs ADD COLUMN error_message TEXT")
                
                db.session.execute(sql)
                print(f"  ✅ Dodano kolumnę: {column}")
            
            # Dodaj indeks dla job_name
            try:
                sql = text("CREATE INDEX IF NOT EXISTS ix_system_logs_job_name ON system_logs (job_name)")
                db.session.execute(sql)
                print("  ✅ Dodano indeks dla job_name")
            except Exception as e:
                print(f"  ⚠️ Indeks job_name już istnieje lub błąd: {e}")
            
            # Zatwierdź zmiany
            db.session.commit()
            print("✅ Migracja zakończona pomyślnie!")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Błąd podczas migracji: {e}")
            raise

def main():
    """Główna funkcja migracji"""
    print("🚀 ETF Analyzer - Migracja bazy danych")
    print("=" * 50)
    
    try:
        migrate_system_logs_table()
        print("\n🎉 Migracja zakończona pomyślnie!")
        print("Możesz teraz uruchomić aplikację z nowymi funkcjami logowania zadań.")
        
    except Exception as e:
        print(f"\n💥 Błąd podczas migracji: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
