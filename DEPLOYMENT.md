# 🚀 ETF Analyzer - Instrukcje Wdrażania v1.9.24

## 📋 **Przegląd Wersji**

**Wersja:** v1.9.24  
**Data wydania:** 1 września 2025  
**Typ wydania:** Feature Release (ulepszenie zadania aktualizacji cen dziennych)

## 🆕 **Co nowego w v1.9.24**

### **Ulepszenia Zadania Aktualizacji Cen Dziennych**
- ✅ **Rozszerzenie zakresu sprawdzania**: Zwiększono z 250 do 365 dni roboczych dla lepszej kompletności danych
- ✅ **Nowa funkcja `check_historical_completeness()`**: Mierzy i raportuje kompletność danych historycznych
- ✅ **Naprawiona funkcja `_save_historical_prices_to_db()`**: Poprawnie zapisuje ceny historyczne z odpowiednimi datami
- ✅ **Ulepszone logowanie kompletności**: Szczegółowe raporty o kompletności danych przed i po aktualizacji
- ✅ **Inteligentne uzupełnianie braków**: Automatyczne pobieranie brakujących cen historycznych z różnych API

### **Nowe Funkcjonalności**
- ✅ **Pomiar kompletności danych**: System automatycznie mierzy kompletność danych historycznych
- ✅ **Raportowanie ulepszeń**: Szczegółowe logi pokazujące ile cen zostało dodanych i jak poprawiła się kompletność
- ✅ **Rozszerzone zarządzanie API**: Lepsze wykorzystanie limitów API z fallbackami (FMP → EODHD → Tiingo)

### **Ulepszenia Techniczne**
- ✅ **Optymalizacja zapisywania danych**: Bezpośrednie tworzenie rekordów ETFDailyPrice z odpowiednimi datami
- ✅ **Lepsze zarządzanie błędami**: Obsługa limitów API i inteligentne fallbacki
- ✅ **Automatyczne czyszczenie**: Usuwanie cen starszych niż 250 dni roboczych

## 🆕 **Co nowego w v1.9.23**

### **Struktura Schedulera**
```
06:00 CET - Sprawdzanie dywidend (codziennie)
18:00 CET - Aktualizacja cen dziennych z uzupełnianiem historii (pon-piątek)
23:00 CET - Sprawdzanie alertów (pon-piątek)
02:00 CET - Czyszczenie logów (niedziela)
```

### **Priorytety Zadań API**
1. **Priorytet 1**: Aktualizacje cen w czasie rzeczywistym
2. **Priorytet 2**: Uzupełnianie brakujących cen historycznych
3. **Priorytet 3**: Sprawdzanie dywidend
4. **Priorytet 4**: Historyczne dane
5. **Priorytet 5**: Wskaźniki techniczne
6. **Priorytet 6**: Dane pomocnicze

## 🆕 **Co nowego w v1.9.22**

### **Dodano**
- ✅ **Zakładka "Dokumentacja Powiadomień"** - kompletną dokumentację systemu w `/alerts`
- ✅ **Harmonogram zadań** - szczegółowa tabela z godzinami wykonywania wszystkich zadań
- ✅ **Zasady powiadomień** - dokumentacja typów alertów i ich zachowań czasowych
- ✅ **Architektura systemu** - wyjaśnienie Events, Alerts i Notifications

### **Zmienione**
- ✅ **Harmonogram zadań** - aktualizacja godzin zgodnie z wymaganiami CEO:
  - Aktualizacja wszystkich ram czasowych: **22:45 CET** (pon-pią)
  - Sprawdzanie alertów wskaźników: **23:00 CET** (pon-pią)
  - Wysyłanie powiadomień wskaźników: **10:00 CET** (następny dzień)
  - Aktualizacja cen ETF: **15:35-22:05 CET co 15 min** (pon-pią)
  - Sprawdzanie alertów (ceny, logi, zadania): **co 10 min**

### **Naprawione**
- ✅ **Dashboard wersja systemu** - naprawa wyświetlania numeru wersji systemu
- ✅ **Błąd JavaScript** - usunięcie odwołania do nieistniejącego elementu `totalEtfs`
- ✅ **Race condition** - dodanie opóźnienia i ponownego sprawdzania elementów DOM
- ✅ **Cache przeglądarki** - wymuszenie odświeżania JavaScript po zmianach

## 🆕 **Co nowego w v1.9.21**

### **Dodano**
- ✅ **System powiadomień Slack** - pełna infrastruktura alertów i powiadomień
- ✅ **Modele bazy danych** - `AlertConfig`, `AlertHistory`, `Notification` dla systemu alertów
- ✅ **Serwis powiadomień** - `NotificationService` z logiką sprawdzania alertów
- ✅ **Integracja ze schedulerem** - sprawdzanie alertów co 10 min + raz dziennie o 10:30 CET
- ✅ **Slack webhook** - powiadomienia na telefon przez aplikację Slack

### **Zmienione**
- ✅ **Optymalizacja schedulera** - timeout API zmniejszony z 10s do 5s, limit czasu 10 min
- ✅ **Konfiguracja Slack** - `SLACK_WEBHOOK_URL`, `SLACK_CHANNEL`, `SLACK_USERNAME`
- ✅ **Endpoint testowy** - `/api/test/slack` do testowania webhook

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
docker build -t etf-analyzer:v1.9.23 .

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
  "version": "1.9.23",
  "timestamp": "2025-01-27T..."
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
git checkout v1.9.22

# Ponowne uruchomienie
./scripts/manage-app.sh start
```

### **Docker Rollback**

```bash
# Zatrzymanie kontenera
docker-compose down

# Uruchomienie poprzedniej wersji
docker run -p 5005:5005 etf-analyzer:v1.9.22
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

**🎉 Gratulacje! ETF Analyzer v1.9.23 został pomyślnie wdrożony!**
