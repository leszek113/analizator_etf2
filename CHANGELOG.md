# Changelog

Wszystkie istotne zmiany w projekcie ETF Analyzer będą dokumentowane w tym pliku.

Format jest oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/),
a projekt przestrzega [Semantic Versioning](https://semver.org/lang/pl/).

## [1.4.0] - 2025-08-19

### Dodane
- **Suma ostatnich dywidend**: Automatyczne obliczanie sumy ostatnich dywidend w zależności od częstotliwości
  - Miesięczne ETF: suma 12 ostatnich dywidend
  - Kwartalne ETF: suma 4 ostatnich dywidend
  - Roczne ETF: ostatnia dywidenda
  - Auto-detekcja częstotliwości na podstawie dat
- **System powiadomień API**: Monitoring tokenów API z ostrzeżeniami o wyczerpaniu limitów
  - Szczegółowe powiadomienia o wyczerpaniu tokenów
  - Ostrzeżenia przy 80% limitu
  - Automatyczne resetowanie liczników co 24h
  - Logi wyczerpania tokenów do pliku
- **Strona statusu systemu**: Dedykowana pod-strona `/system/status` z informacjami o:
  - Statystykach systemu (ETF, ceny, dywidendy, logi)
  - Statusie bazy danych (ostatnia aktualizacja)
  - Statusie tokenów API (FMP, EODHD, Tiingo)
  - Zdrowiu systemu
  - Szybkich akcjach
- **Dashboard link**: Kafelek "Status systemu" zmieniony na link do pod-strony systemowej
- **API endpoints**: Nowe endpointy `/api/system/api-status` i `/system/status`

### Ulepszone
- **Inteligentne sprawdzanie API**: System automatycznie używa cache gdy API niedostępne
- **Rate limiting**: Kontrola liczby wywołań API dla każdego dostawcy
- **Error handling**: Lepsze obsługiwanie błędów i fallback do cache
- **User experience**: Łatwiejszy dostęp do informacji systemowych

## [1.3.1] - 2025-08-13

### Zmienione
- **Port aplikacji** - zmieniony z 6000 na 5005 (rozwiązanie problemu ERR_UNSAFE_PORT w przeglądarkach)
- **Domyślna wartość portu** - zaktualizowana w app.py i config.py

## [1.3.0] - 2025-08-13

### Dodane
- **Historical Dividend Matrix** - szczegółowy widok historii dywidend w formie tabeli lat/miesięcy
- **Stock Split Normalization** - automatyczna normalizacja danych po splitach akcji
- **Split column w matrycy** - oznaczenie lat z splitami akcji
- **Nowy endpoint `/etf/<ticker>`** - szczegółowy widok ETF z matrycą dywidend
- **Automatyczna normalizacja cen** - uwzględnienie splitów w historycznych cenach
- **Color-coded annual sums** - zielone (wzrost), żółte (spadek), szare (bez zmian)

### Funkcjonalności Historical Dividend Matrix
- **Tabela lat/miesięcy** - od najstarszych do najnowszych lat
- **Kolumna "Suma Roczna"** - suma dywidend z danego roku z color-coding
- **Kolumna "Split"** - oznaczenie splitów akcji (np. 3:1 dla SCHD 2024)
- **Tooltips z wartościami** - dokładne kwoty zmian rok do roku
- **Dynamiczne generowanie** - automatyczne dodawanie nowych lat

### Stock Split Normalization
- **Automatyczne wykrywanie splitów** - z FMP API
- **Normalizacja dywidend** - przeliczanie kwot po splitach
- **Normalizacja cen** - przeliczanie historycznych cen po splitach
- **Zachowanie oryginalnych danych** - backup oryginalnych wartości
- **Split ratio tracking** - śledzenie zastosowanych współczynników

### Techniczne
- **Nowe funkcje w APIService** - `get_stock_splits()`, `normalize_dividends_for_splits()`, `normalize_prices_for_splits()`
- **Nowy template HTML** - `etf_details.html` z matrycą dywidend
- **Integracja z dashboardem** - linki do szczegółowych widoków
- **Port aplikacji** - zmieniony z 6000 na 5005 (bezpieczny port)

### Naprawione
- **Port conflicts** - aplikacja działa na porcie 5005 (bezpieczny port)
- **Split data handling** - automatyczna normalizacja dla SCHD i innych ETF

## [1.2.0] - 2025-08-13

### Dodane
- **Dividend Streak Growth (DSG)** - nowa funkcjonalność obliczająca streak wzrostu dywidend
- **API endpoint `/api/etfs/<ticker>/dsg`** - zwraca szczegółowe informacje o DSG
- **Kolumna DSG w dashboardzie** - wyświetla aktualny i najdłuższy streak
- **Sortowanie po DSG** - możliwość sortowania tabeli według streak
- **Tooltips z informacjami DSG** - szczegółowe informacje o streak w dashboardzie
- **Automatyczne obliczanie DSG** - dla wszystkich ETF w endpoint `/api/etfs`

### Funkcjonalności DSG
- **Obliczanie streak** - rok do roku (średnia roczna dywidenda)
- **Aktualny streak** - bieżący streak wzrostu dywidend
- **Najdłuższy streak** - najdłuższy streak w historii
- **Okres streak** - lata rozpoczęcia i zakończenia najdłuższego streak
- **Ostatnia zmiana** - informacja o ostatniej zmianie dywidendy
- **Metoda obliczania** - year-over-year average

### Techniczne
- **Nowa funkcja w APIService** - `calculate_dividend_streak_growth()`
- **Integracja z dashboardem** - DSG wyświetlane w tabeli ETF
- **Obsługa błędów** - bezpieczne obliczanie DSG z fallback do wartości domyślnych
- **Wydajność** - DSG obliczane na żądanie, nie przechowywane w bazie

## [1.1.0] - 2025-08-12

### Naprawione
- **Problem z dywidendami** - system teraz pobiera wszystkie dostępne dane historyczne
- **Metoda _check_new_dividends** - zmieniono logikę z 1 roku na 15 lat historii
- **SPY ETF** - z 4 dywidend na 60 dywidend (2010-2025)
- **Debug logging** - dodano szczegółowe logowanie procesu pobierania dywidend

### Dodane
- **Debug logging** w get_dividend_history dla lepszego monitorowania
- **Szczegółowe logowanie** procesu filtrowania i dodawania dywidend
- **Informacje o liczbie dywidend** z API vs w bazie danych
- **Dokumentacja logiki systemu** - starting point 15 lat + automatyczny wzrost historii

### Zmienione
- **Logika sprawdzania dywidend** - teraz pobiera wszystkie dostępne (15 lat)
- **Metoda _check_new_dividends** - porównuje z istniejącymi w bazie zamiast tylko ostatniej

### Techniczne
- **Poprawiona wydajność** - system dodaje wszystkie brakujące dywidendy za jednym razem
- **Lepsze monitorowanie** - widoczne dokładnie ile danych API zwraca vs ile system przetwarza

### Dokumentacja
- **Dodano sekcję "Logika Systemu Dywidend"** w README.md
- **Wyjaśniono starting point 15 lat** i automatyczny wzrost historii
- **Przykłady dla SPY i SCHD** - jak historia rośnie z czasem

## [1.0.0] - 2025-08-12

### Dodane
- **Główna aplikacja Flask** z portem 5002
- **Modele bazy danych** (ETF, ETFPrice, ETFDividend, SystemLog)
- **API Service** z integracją FMP, EODHD i Tiingo
- **Database Service** z CRUD operacjami
- **Dashboard HTML** z sortowaniem i filtrowaniem
- **Scheduler APScheduler** z automatycznymi aktualizacjami
- **Cache system** w pamięci (TTL: 1 godzina)
- **Retry logic** z exponential backoff
- **Docker support** z docker-compose
- **CRUD operacje** - dodawanie, aktualizacja, usuwanie ETF

### Zmienione
- **Strategia API** - FMP jako główne źródło, EODHD jako backup, Tiingo jako fallback
- **Usunięcie mock data** - system używa tylko prawdziwych danych
- **Port aplikacji** - zmieniony z 5000 na 5002
- **Struktura projektu** - profesjonalna architektura z serwisami

### Usunięte
- **Yahoo Finance API** - z powodu błędów API
- **Alpha Vantage API** - z powodu limitów (25 requestów/dzień)
- **Wszystkie mock data** - zgodnie z wymaganiami CEO

### Naprawione
- **SQLAlchemy metadata error** - zmiana nazwy kolumny na metadata_json
- **Port conflicts** - aplikacja działa na porcie 5002
- **API integration** - wszystkie API sources działają poprawnie

### Techniczne
- **Python 3.11+** compatibility
- **Flask 3.0.0** z najnowszymi funkcjonalnościami
- **SQLAlchemy 3.1.1** z ORM
- **APScheduler 3.10.4** dla automatyzacji
- **Docker** z health checks
- **GitHub** ready

## [0.1.0] - 2025-08-12 (Development)

### Dodane
- Podstawowa struktura projektu
- Konfiguracja środowiska
- Pierwsze testy API

### Zmienione
- Wiele iteracji API strategy
- Testowanie różnych źródeł danych

### Usunięte
- Eksperymentalne implementacje
- Nieudane API integrations

---

## Uwagi

- **Wersja 1.1.0** oznacza pierwszy patch release z naprawami
- **Wersja 1.0.0** oznacza pierwszy stabilny release
- **Wszystkie wymagania CEO** zostały spełnione
- **System jest gotowy do produkcji**
- **Żadne mock data** - tylko prawdziwe dane z API
- **Problem z dywidendami ROZWIĄZANY** - pełna historia danych dostępna
