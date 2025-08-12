# Changelog

Wszystkie istotne zmiany w projekcie ETF Analyzer będą dokumentowane w tym pliku.

Format jest oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/),
a projekt przestrzega [Semantic Versioning](https://semver.org/lang/pl/).

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

### Zmienione
- **Logika sprawdzania dywidend** - teraz pobiera wszystkie dostępne (15 lat)
- **Metoda _check_new_dividends** - porównuje z istniejącymi w bazie zamiast tylko ostatniej

### Techniczne
- **Poprawiona wydajność** - system dodaje wszystkie brakujące dywidendy za jednym razem
- **Lepsze monitorowanie** - widoczne dokładnie ile danych API zwraca vs ile system przetwarza

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
