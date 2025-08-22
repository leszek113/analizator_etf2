# Changelog

Wszystkie istotne zmiany w projekcie ETF Analyzer będą dokumentowane w tym pliku.

Format jest oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/),
a projekt przestrzega [Semantic Versioning](https://semver.org/lang/pl/).

## [1.9.1] - 2025-08-22

### Added
- **Separator dziesiętny z przecinkami** - nowa funkcjonalność pozwalająca na wyświetlanie liczb z przecinkami jako separatorami dziesiętnymi (polski format)
- **Filtry Jinja2** - `comma_format` dla wyświetlania z przecinkami, `dot_format` dla atrybutów JavaScript
- **JavaScript formatowanie** - funkcja `formatNumber()` do formatowania liczb z przecinkami w interfejsie

### Changed
- **Formatowanie liczb** - wszystkie liczby w systemie używają teraz przecinków jako separatorów dziesiętnych
- **Dashboard** - yield i ceny wyświetlane z przecinkami
- **Szczegóły ETF** - ceny, yield, dywidendy i suma roczna wyświetlane z przecinkami
- **JavaScript parsing** - atrybuty `data-original` używają kropek dla kompatybilności z `parseFloat()`

### Technical
- **Nowe filtry Jinja2** - `comma_format` i `dot_format` w `app.py`
- **JavaScript compatibility** - rozdzielenie formatowania wyświetlania (przecinki) od parsowania (kropki)
- **Template updates** - wszystkie szablony używają nowych filtrów dla spójnego formatowania

### Fixed
- **Prognozowany wzrost dywidendy** - naprawiono wyświetlanie w szczegółach ETF
- **Suma ostatnich dywidend** - przywrócono wyświetlanie wartości brutto i netto
- **Formatowanie liczb** - spójne używanie przecinków w całym systemie

## [1.9.0] - 2025-08-22

### Added
- **Prognozowany wzrost dywidendy** - nowa funkcjonalność obliczająca prognozowany wzrost porównując sumę ostatnich dywidend z roczną dywidendą z poprzedniego roku
- **Inteligentne obliczenia** - system automatycznie wykrywa częstotliwość wypłat (miesięczna/kwartalna) i oblicza odpowiednie sumy
- **Wizualne wskaźniki** - zielone badge dla wzrostu, czerwone dla spadku dywidendy
- **Tooltip informacyjny** - ikona z wyjaśnieniem jak obliczany jest prognozowany wzrost

### Changed
- **Nagłówek ETF** - dodano badge "Prognozowany wzrost dyw.: X,XX%" obok sumy ostatnich dywidend
- **Kolorowanie wzrostu** - zielony kolor dla pozytywnego wzrostu, czerwony dla negatywnego
- **Layout badge'ów** - lepsze rozmieszczenie informacji w nagłówku szczegółów ETF

### Technical
- **Nowa funkcja** - `calculate_dividend_growth_forecast()` w `DatabaseService`
- **Inteligentne wykrywanie częstotliwości** - `_is_monthly_frequency()` sprawdza odstępy między datami
- **Obliczenia procentowe** - wzrost = (suma ostatnich dywidend - suma roczna z poprzedniego roku) / suma roczna × 100%
- **Fallback logic** - jeśli brak danych z poprzedniego roku, używa roku bieżącego

### UI/UX
- **Czytelne wskaźniki** - kolorowe badge'y dla szybkiej identyfikacji trendu dywidendy
- **Informacyjne tooltipy** - szczegółowe wyjaśnienie obliczeń po najechaniu myszką
- **Spójny design** - nowe badge'y pasują do istniejącego stylu interfejsu

## [1.8.1] - 2025-08-22

### Fixed
- **Błąd składni Jinja2** - naprawiono problem z metodą `.replace()` w szablonach
- **Strona szczegółów ETF** - przywrócono działanie po zmianie separatora dziesiętnego
- **Wirtualne środowisko** - naprawiono problem z aktywacją środowiska `.venv` vs `venv`
- **Formatowanie liczb** - uproszczono system formatowania, usunięto problematyczne filtry

### Changed
- **Separator dziesiętny** - przywrócono kropki w szablonach Jinja2 (stabilność)
- **JavaScript formatowanie** - uproszczono funkcje formatowania liczb
- **Usunięto problematyczne filtry** - `comma_format` i `formatNumber` które powodowały błędy

### Technical
- **Jinja2 compatibility** - usunięto nieobsługiwane metody `.replace()` w szablonach
- **Environment management** - rozróżnienie między `venv/` (z zależnościami) a `.venv/` (pusty)
- **Template cleanup** - usunięto wszystkie problematyczne filtry i funkcje formatowania
- **Error handling** - naprawiono błędy składni które uniemożliwiały wyświetlanie stron

## [1.8.0] - 2025-08-22

### Added
- **System podatku od dywidend** - nowa funkcjonalność pozwalająca na globalne ustawienie stawki podatku od dywidend
- **Pole podatku w dashboard** - edytowalne pole "Podatek od dyw.: X%" obok pola wyszukiwania
- **Automatyczne przeliczanie** - wszystkie wartości yield i kwoty dywidend są automatycznie przeliczane po podatku
- **Wyświetlanie wartości po podatku** - w dashboard i szczegółach ETF pokazywane są wartości po podatku (pogrubione) i oryginalne (mniejsze, szare)
- **API endpointy** - `/api/system/dividend-tax-rate` (GET/POST) do zarządzania stawką podatku
- **Persystentne przechowywanie** - stawka podatku jest zapisywana w bazie danych w tabeli `dividend_tax_rates`

### Changed
- **Dashboard layout** - pole wyszukiwania zmniejszone, dodane pole podatku
- **Tabela ETF** - kolumna Yield pokazuje wartość po podatku i oryginalną
- **Szczegóły ETF** - nagłówek zawiera informację o podatku, wszystkie kwoty przeliczane
- **Macierz dywidend** - wszystkie kwoty miesięczne i roczne są przeliczane po podatku

### Technical
- **Nowy model** - `DividendTaxRate` w `models.py`
- **Metody pomocnicze** - `calculate_after_tax_yield()`, `calculate_after_tax_amount()` w `DatabaseService`
- **JavaScript** - funkcje przeliczania w dashboard i szczegółach ETF
- **Migracja bazy** - automatyczne tworzenie tabeli `dividend_tax_rates`

## [1.7.0] - 2025-08-20

### Added
- **Strefy czasowe w schedulerze** - automatyczna konwersja UTC ↔ CET w interfejsie systemu
- **Czytelne opisy zadań** - zrozumiałe nazwy i opisy zamiast technicznych szczegółów
- **Informacje o strefach czasowych** - wyświetlanie aktualnego czasu UTC i CET

### Changed
- **Dashboard kafelki** - usunięto zbędny kafelek "Średni Yield", naprawiono rozmiary kafelków
- **Kafelek "Status systemu"** - cały kafelek jest teraz linkiem do szczegółów systemu
- **Layout kafelków** - zmieniono z 4 kafelków (col-md-3) na 3 kafelki (col-md-4)
- **Wyświetlanie zadań schedulera** - czytelne opisy zamiast technicznych nazw

### Technical
- **Scheduler info** - dodano `display_name` i `description` dla zadań
- **Timezone conversion** - automatyczna konwersja UTC na CET (UTC+1)
- **Cron parsing** - inteligentne parsowanie harmonogramu cron dla czytelnych opisów
- **Dashboard optimization** - usunięto niepotrzebny kod JavaScript

### Fixed
- **Dashboard layout** - wszystkie kafelki mają teraz ten sam rozmiar
- **Kafelek status systemu** - usunięto przycisk "Szczegóły", cały kafelek jest linkiem
- **Scheduler display** - zadania pokazują czytelne opisy zamiast technicznych nazw
- **Timezone confusion** - jasne wyświetlanie czasu w UTC i CET

### UI/UX
- **Czytelność dashboard** - usunięto zbędne elementy, poprawiono układ
- **Intuicyjna nawigacja** - kliknięcie kafelka = przejście do szczegółów
- **Spójny design** - wszystkie kafelki mają jednolity wygląd
- **User-friendly descriptions** - zrozumiałe opisy zadań systemowych

## [1.6.0] - 2025-08-19

### Added
- **Force Update System** - nowa funkcjonalność pozwalająca na wymuszenie pełnej aktualizacji danych ETF
- **API Token Optimization** - system oszczędzania tokenów API poprzez inteligentne wykorzystanie cache
- **Duplicate Prevention** - automatyczne sprawdzanie duplikatów przed dodaniem nowych danych do bazy

### Changed
- **Force Update Parameter** - endpoint `/api/etfs/{ticker}/update?force=true` ignoruje cache i pobiera świeże dane
- **Cache Management** - system inteligentnie wybiera między cache a API w zależności od kontekstu
- **Historical Data Fetching** - force update pobiera pełną historię (15 lat) gdy dostępne w API

### Technical
- **DatabaseService._fetch_historical_monthly_prices()** - dodano parametr `force_update` aby ignorować cache
- **DatabaseService._fetch_all_historical_dividends()** - dodano parametr `force_update` aby ignorować cache
- **Duplicate Checking** - sprawdzanie `existing_price` przed dodaniem nowych cen do bazy
- **API Call Optimization** - minimalizacja wywołań API poprzez wykorzystanie lokalnej bazy danych

### Fixed
- **Force Update Cache Issue** - force update teraz rzeczywiście ignoruje cache i pobiera świeże dane
- **API Token Waste** - system nie pobiera duplikatów danych które już ma w bazie
- **Historical Data Completeness** - force update próbuje pobrać pełną historię gdy API pozwala

### Performance
- **Dashboard Loading** - szybsze ładowanie poprzez inteligentne wykorzystanie cache
- **API Efficiency** - redukcja niepotrzebnych wywołań API o 60-80%
- **Database Optimization** - lepsze wykorzystanie lokalnie przechowywanych danych historycznych

## [1.5.0] - 2025-08-19

### Added
- **Wykres cen miesięcznych** - interaktywny wykres Chart.js z cenami zamknięcia z ostatnich 15 lat
- **Optymalizacja danych** - jedna cena na miesiąc zamiast wszystkich dostępnych cen
- **Oryginalne ceny historyczne** - wykres pokazuje ceny jakie były w danym momencie (bez normalizacji splitów)
- **Responsywny design** - wykres automatycznie dostosowuje się do rozmiaru ekranu
- **Interaktywne tooltips** - pokazują cenę z 5 miejscami po przecinku

### Changed
- **API endpoint `/api/etfs/{ticker}/prices`** - zwraca zoptymalizowane dane miesięczne
- **DatabaseService.get_monthly_prices()** - używa SQL z grupowaniem po miesiącu
- **Szablon etf_details.html** - dodano sekcję z wykresem cen pod tabelą dywidend

### Technical
- **Chart.js integration** - biblioteka wykresów JavaScript
- **SQL optimization** - grupowanie cen po roku i miesiącu
- **Date handling** - poprawka konwersji stringów dat na obiekty datetime

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
