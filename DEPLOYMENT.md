# 🚀 ETF Analyzer - Instrukcje Wdrażania v1.9.17

## 📋 **Przegląd Wersji**

**Wersja:** v1.9.18  
**Data wydania:** 24 sierpnia 2025  
**Typ wydania:** Minor Release (normalizacja cen 1D + poprawki)

## 🆕 **Co nowego w v1.9.17**

### **Nowe Funkcjonalności**
- ✅ **Normalizacja cen 1D** - kolumny `normalized_close_price` i `split_ratio_applied` w tabeli `etf_daily_prices`
- ✅ **Model `ETFDailyPrice`** - rozszerzony o kolumny year, month, day dla optymalizacji zapytań
- ✅ **Znormalizowane ceny** - wszystkie endpointy 1D używają znormalizowanych cen z bazy danych
- ✅ **Wskaźniki 1D** - MACD, Stochastic (36-12-12), Stochastic Short (9-3-3) dla danych dziennych
- ✅ **Przełącznik timeframe 1D** - opcja "1D (Dzienne)" w interfejsie użytkownika

### **Ulepszenia Systemu**
- ✅ **Normalizacja splitów** - ceny 1D są teraz normalizowane tak samo jak 1W i 1M
- ✅ **Struktura bazy danych** - dodano brakujące kolumny do modelu `ETFDailyPrice`
- ✅ **Endpointy API** - wszystkie endpointy 1D poprawnie obsługują znormalizowane ceny

### **Poprawki Techniczne**
- ✅ **Problem z normalizacją** - wykresy 1D nie pokazują już dramatycznych skoków cen spowodowanych splitami
- ✅ **Brakujące kolumny** - dodano kolumny `year`, `month`, `day` do tabeli `etf_daily_prices`
- ✅ **Błędne endpointy** - naprawiono wszystkie endpointy 1D żeby używały znormalizowanych cen

## 🆕 **Co nowego w v1.9.16**

### **Nowe Funkcjonalności**
- ✅ **Dane dzienne (1D)** - nowa tabela `etf_daily_prices` z rolling window 365 dni
- ✅ **Nowe zadanie schedulera** - `update_all_timeframes()` zastępuje `update_all_etfs()`
- ✅ **API endpointy 1D** - `/api/etfs/<ticker>/daily-prices` i `/api/etfs/<ticker>/add-daily-prices`
- ✅ **Priorytet źródeł API dla 1D** - EODHD → FMP → Tiingo (EODHD lepszy dla cen dziennych)
- ✅ **Automatyczny cleanup** - usuwanie cen dziennych starszych niż 365 dni

### **Ulepszenia Systemu**
- ✅ **Harmonogram schedulera** - zmieniony z 5:00 CET na 23:50 CET
- ✅ **Logika kompletności** - sprawdzanie wszystkich ram czasowych (1M, 1W, 1D)
- ✅ **System status** - aktualizacja opisów i nazw zadań

### **Poprawki Techniczne**
- ✅ **Rozszerzenie `smart_history_completion`** - obsługa danych 1D wraz z 1M i 1W
- ✅ **Relacje modeli** - dodano relację `daily_prices` w modelu ETF
- ✅ **Funkcje konwersji** - dodano `_convert_*_prices_to_daily` dla wszystkich źródeł API

## 🔧 **Co zostało naprawione w v1.9.11**

### **Krytyczne Poprawki**
- ✅ **Walidacja inputów** - sprawdzanie poprawności ticker (regex: A-Z, 0-9, max 20 znaków)
- ✅ **Spójność formatowania dat** - wszystkie modele używają UTC->CET konwersji
- ✅ **Aktualizacja zależności** - Flask 2.3.3, Werkzeug 2.3.7, NumPy 2.0.4

### **Nowe Funkcjonalności**
- ✅ **Testy jednostkowe** - pokrycie kodu testami dla kluczowych funkcji
- ✅ **Wspólny CSS** - uniwersalne style dla całej aplikacji
- ✅ **Lepsze logowanie błędów** - szczegółowe komunikaty dla problemów z walidacją

### **Ulepszenia Jakości**
- ✅ **Refaktoryzacja CSS** - usunięcie duplikatów, lepsza organizacja
- ✅ **Poprawione nazewnictwo** - usunięcie mylących aliasów w API service
- ✅ **Dokumentacja** - szczegółowy changelog z wszystkimi zmianami

## 🛠️ **Wymagania Systemowe**

### **Python**
- **Wersja:** 3.11+ (zalecane 3.11.5+)
- **Virtual Environment:** Wymagane

### **Zależności**
- **Flask:** 2.3.3 (stabilna wersja produkcyjna)
- **Werkzeug:** 2.3.7 (kompatybilna z Flask 2.3.3)
- **NumPy:** 2.0.4 (zaktualizowana wersja)

### **API Keys**
- **FMP API:** Główny klucz (500 requestów/dzień)
- **EODHD API:** Backup klucz (100 requestów/dzień)
- **Tiingo API:** Fallback klucz (50 requestów/dzień)

## 📥 **Instrukcje Wdrażania**

### **1. Przygotowanie Środowiska**

```bash
# Klonowanie repozytorium
git clone https://github.com/leszek113/analizator_etf2.git
cd analizator_etf2

# Sprawdzenie wersji Python
python3 --version  # Powinno być 3.11+

# Tworzenie virtual environment
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# lub
venv\Scripts\activate  # Windows
```

### **2. Instalacja Zależności**

```bash
# Aktualizacja pip
pip install --upgrade pip

# Instalacja zależności
pip install -r requirements.txt

# Sprawdzenie zainstalowanych wersji
pip list | grep -E "(Flask|Werkzeug|NumPy)"
```

### **3. Konfiguracja**

```bash
# Kopiowanie pliku konfiguracyjnego
cp .env.example .env

# Edycja .env - dodanie kluczy API
nano .env  # lub vim .env

# Wymagane zmienne:
FMP_API_KEY=your_fmp_key_here
EODHD_API_KEY=your_eodhd_key_here
TIINGO_API_KEY=your_tiingo_key_here
```

### **4. Inicjalizacja Bazy Danych**

```bash
# Uruchomienie migracji (jeśli potrzebne)
python3 migrate_database.py

# Sprawdzenie struktury bazy
python3 -c "from app import create_app; from models import db; app = create_app(); app.app_context().push(); db.create_all(); print('✅ Baza danych zainicjalizowana')"
```

### **5. Testowanie**

```bash
# Testy jednostkowe (nie wymagają uruchomionej aplikacji)
python3 test_unit.py

# Testy integracyjne (wymagają uruchomionej aplikacji)
python3 test_system.py
```

### **6. Uruchomienie**

```bash
# Uruchomienie aplikacji
python3 app.py

# Lub przez skrypt zarządzania
./scripts/manage-app.sh start

# Sprawdzenie statusu
./scripts/manage-app.sh status
```

## 🐳 **Wdrażanie przez Docker**

### **1. Budowanie Obrazu**

```bash
# Budowanie obrazu Docker
docker build -t etf-analyzer:v1.9.11 .

# Sprawdzenie utworzonego obrazu
docker images | grep etf-analyzer
```

### **2. Uruchomienie Kontenera**

```bash
# Uruchomienie przez Docker Compose
docker-compose up -d

# Sprawdzenie statusu
docker-compose ps

# Logi kontenera
docker-compose logs -f etf-analyzer
```

### **3. Sprawdzenie Działania**

```bash
# Test API
curl http://localhost:5005/api/system/status

# Test wersji
curl http://localhost:5005/api/system/version
```

## 🔍 **Weryfikacja Wdrożenia**

### **Sprawdzenie Wersji**

```bash
# API endpoint
curl http://localhost:5005/api/system/version

# Oczekiwana odpowiedź:
{
  "success": true,
  "version": "1.9.11",
  "timestamp": "2025-08-24T..."
}
```

### **Sprawdzenie Funkcjonalności**

1. **Dashboard** - http://localhost:5005/
2. **Status systemu** - http://localhost:5005/system/status
3. **API health** - http://localhost:5005/api/system/api-status

### **Testy Bezpieczeństwa**

```bash
# Test walidacji ticker
curl -X POST http://localhost:5005/api/etfs \
  -H "Content-Type: application/json" \
  -d '{"ticker": ""}'  # Powinno zwrócić błąd walidacji

curl -X POST http://localhost:5005/api/etfs \
  -H "Content-Type: application/json" \
  -d '{"ticker": "SPY"}'  # Powinno działać
```

## 📊 **Monitoring i Logi**

### **Logi Aplikacji**

```bash
# Logi w czasie rzeczywistym
tail -f etf-analyzer.log

# Logi przez skrypt
./scripts/manage-app.sh logs
```

### **Status Systemu**

```bash
# Sprawdzenie statusu schedulera
curl http://localhost:5005/api/system/status

# Sprawdzenie limitów API
curl http://localhost:5005/api/system/api-status
```

## 🚨 **Rozwiązywanie Problemów**

### **Typowe Problemy**

1. **Błąd importu modułów**
   ```bash
   # Sprawdź czy virtual environment jest aktywne
   which python3
   pip list | grep Flask
   ```

2. **Błąd bazy danych**
   ```bash
   # Sprawdź uprawnienia do pliku bazy
   ls -la instance/
   # Uruchom migrację
   python3 migrate_database.py
   ```

3. **Błąd portu**
   ```bash
   # Sprawdź czy port 5005 jest wolny
   lsof -i :5005
   # Zatrzymaj inne procesy używające port
   ```

### **Logi Błędów**

```bash
# Szczegółowe logi błędów
grep -i error etf-analyzer.log

# Logi z ostatniej godziny
tail -100 etf-analyzer.log | grep -i error
```

## 📈 **Metryki Wydajności**

### **Sprawdzenie Wydajności**

```bash
# Czas odpowiedzi API
time curl http://localhost:5005/api/system/status

# Użycie pamięci
ps aux | grep python3 | grep app.py

# Użycie CPU
top -p $(pgrep -f "python.*app.py")
```

## 🔄 **Rollback (w razie problemów)**

### **Przywrócenie Poprzedniej Wersji**

```bash
# Zatrzymanie aplikacji
./scripts/manage-app.sh stop

# Przełączenie na poprzedni tag
git checkout v1.9.10

# Ponowne uruchomienie
./scripts/manage-app.sh start
```

### **Docker Rollback**

```bash
# Zatrzymanie kontenera
docker-compose down

# Uruchomienie poprzedniej wersji
docker run -p 5005:5005 etf-analyzer:v1.9.10
```

## 📞 **Wsparcie**

### **W przypadku problemów**

1. **Sprawdź logi** - `./scripts/manage-app.sh logs`
2. **Sprawdź status** - `./scripts/manage-app.sh status`
3. **Uruchom testy** - `python3 test_unit.py`
4. **Sprawdź dokumentację** - README.md, CHANGELOG.md

### **Kontakt**

- **CEO:** Leszek
- **Project Manager & Developer:** AI Assistant
- **Status:** Projekt gotowy do produkcji

---

**🎉 Gratulacje! ETF Analyzer v1.9.11 został pomyślnie wdrożony!**
