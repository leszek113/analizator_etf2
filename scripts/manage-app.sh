#!/bin/bash

# =============================================================================
# ETF Analyzer - Skrypt Zarządzania Aplikacją
# =============================================================================

# Automatyczne przejście do głównego katalogu projektu
# Skrypt może być uruchamiany z dowolnego miejsca
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Przejście do głównego katalogu projektu
cd "$PROJECT_ROOT"

# Sprawdzenie czy jesteśmy w odpowiednim katalogu
if [ ! -f "app.py" ] || [ ! -f "config.py" ] || [ ! -f "requirements.txt" ]; then
    echo "❌ Błąd: Skrypt musi być uruchamiany z katalogu scripts/ lub głównego katalogu projektu"
    echo "📁 Aktualny katalog: $(pwd)"
    echo "📁 Oczekiwany katalog: $PROJECT_ROOT"
    exit 1
fi

echo "📁 Przejście do głównego katalogu projektu: $(pwd)"
# 
# Użycie:
#   ./manage-app.sh [start|stop|restart|status|logs|test|deploy|version]
# 
# Przykłady:
#   ./manage-app.sh start      # Uruchomienie aplikacji
#   ./manage-app.sh stop       # Zatrzymanie aplikacji
#   ./manage-app.sh restart    # Restart aplikacji
#   ./manage-app.sh status     # Status aplikacji
#   ./manage-app.sh logs       # Wyświetlenie logów
#   ./manage-app.sh test       # Uruchomienie testów
#   ./manage-app.sh deploy     # Wdrożenie nowej wersji
#   ./manage-app.sh version    # Informacje o wersji
# =============================================================================

# Konfiguracja
APP_NAME="ETF Analyzer"
APP_FILE="app.py"
APP_PORT="5005"
APP_HOST="127.0.0.1"
LOG_FILE="etf-analyzer.log"
PID_FILE="etf-analyzer.pid"
VENV_DIR="venv"
PYTHON_CMD="python3"

# Dynamiczne pobieranie wersji z config.py
get_app_version() {
    if [ -f "config.py" ]; then
        # Sprawdź czy virtual environment istnieje i użyj go
        if [ -f "$VENV_DIR/bin/python" ]; then
            VERSION=$("$VENV_DIR/bin/python" -c "from config import __version__; print(__version__)" 2>/dev/null)
        else
            VERSION=$(python3 -c "from config import __version__; print(__version__)" 2>/dev/null)
        fi
        
        if [ $? -eq 0 ] && [ ! -z "$VERSION" ]; then
            echo "v$VERSION"
        else
            echo "v1.9.24"  # Fallback
        fi
    else
        echo "v1.9.24"  # Fallback
    fi
}

APP_VERSION=$(get_app_version)

# Kolory dla output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Funkcje pomocnicze
print_header() {
    echo -e "${CYAN}"
    echo "============================================================================="
    echo "  $APP_NAME $APP_VERSION - Skrypt Zarządzania"
    echo "============================================================================="
    echo -e "${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_step() {
    echo -e "${PURPLE}🔧 $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Sprawdzenie czy aplikacja jest uruchomiona
is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null 2>&1; then
            return 0
        else
            rm -f "$PID_FILE"
            return 1
        fi
    fi
    return 1
}

# Sprawdzenie czy port jest zajęty
is_port_occupied() {
    if lsof -Pi :$APP_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Sprawdzenie czy virtual environment istnieje
check_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        print_warning "Virtual environment nie istnieje. Tworzenie..."
        $PYTHON_CMD -m venv "$VENV_DIR"
        print_success "Virtual environment utworzony"
    fi
    
    if [ ! -f "$VENV_DIR/bin/activate" ]; then
        print_error "Błąd: Virtual environment jest uszkodzony"
        exit 1
    fi
}

# Aktywacja virtual environment
activate_venv() {
    source "$VENV_DIR/bin/activate"
    print_info "Virtual environment aktywowany"
}

# Sprawdzenie zależności
check_dependencies() {
    print_step "Sprawdzanie zależności..."
    
    if ! pip show Flask > /dev/null 2>&1; then
        print_warning "Flask nie jest zainstalowany. Instalowanie zależności..."
        pip install -r requirements.txt
        print_success "Zależności zainstalowane"
    else
        print_success "Wszystkie zależności są zainstalowane"
    fi
}

# Uruchomienie aplikacji
start_app() {
    print_step "Uruchamianie $APP_NAME..."
    
    if is_running; then
        print_warning "Aplikacja jest już uruchomiona (PID: $(cat $PID_FILE))"
        return 1
    fi
    
    if is_port_occupied; then
        print_error "Port $APP_PORT jest już zajęty"
        return 1
    fi
    
    check_venv
    activate_venv
    check_dependencies
    
    print_step "Uruchamianie aplikacji na porcie $APP_PORT..."
    
    # Uruchomienie w tle z logowaniem
    nohup $PYTHON_CMD $APP_FILE > "$LOG_FILE" 2>&1 &
    PID=$!
    echo $PID > "$PID_FILE"
    
    # Czekanie na uruchomienie
    sleep 3
    
    if is_running; then
        print_success "Aplikacja uruchomiona pomyślnie (PID: $PID)"
        print_info "Dashboard dostępny pod adresem: http://$APP_HOST:$APP_PORT"
        print_info "API status: http://$APP_HOST:$APP_PORT/api/system/status"
        print_info "Logi: tail -f $LOG_FILE"
    else
        print_error "Błąd uruchamiania aplikacji"
        rm -f "$PID_FILE"
        return 1
    fi
}

# Zatrzymanie aplikacji
stop_app() {
    print_step "Zatrzymywanie $APP_NAME..."
    
    if ! is_running; then
        print_warning "Aplikacja nie jest uruchomiona"
        return 1
    fi
    
    PID=$(cat "$PID_FILE")
    print_info "Zatrzymywanie procesu (PID: $PID)..."
    
    kill $PID
    
    # Czekanie na zakończenie
    for i in {1..10}; do
        if ! is_running; then
            break
        fi
        sleep 1
    done
    
    if is_running; then
        print_warning "Proces nie zakończył się. Wymuszenie zakończenia..."
        kill -9 $PID
        sleep 1
    fi
    
    rm -f "$PID_FILE"
    print_success "Aplikacja zatrzymana"
}

# Restart aplikacji - POPRAWIONA FUNKCJA
restart_app() {
    print_step "Restart $APP_NAME..."
    
    # Sprawdzenie czy aplikacja jest uruchomiona
    if is_running; then
        print_info "Aplikacja jest uruchomiona, zatrzymuję..."
        stop_app
        sleep 3  # Dłuższe oczekiwanie na zwolnienie portu
    else
        print_info "Aplikacja nie jest uruchomiona"
    fi
    
    # Sprawdzenie czy port jest wolny
    if is_port_occupied; then
        print_warning "Port $APP_PORT jest nadal zajęty. Wymuszenie zwolnienia..."
        
        # Znajdź proces używający portu
        PORT_PID=$(lsof -ti :$APP_PORT 2>/dev/null)
        if [ ! -z "$PORT_PID" ]; then
            print_warning "Proces $PORT_PID używa portu $APP_PORT. Zatrzymuję..."
            kill -9 $PORT_PID 2>/dev/null
            sleep 2
        fi
        
        # Sprawdź ponownie
        if is_port_occupied; then
            print_error "Nie można zwolnić portu $APP_PORT"
            return 1
        fi
    fi
    
    # Uruchom aplikację
    print_info "Uruchamianie aplikacji..."
    start_app
    
    # Sprawdź czy się uruchomiła
    sleep 3
    if is_running; then
        print_success "Restart zakończony pomyślnie"
    else
        print_error "Restart nie powiódł się"
        return 1
    fi
}

# Status aplikacji
show_status() {
    print_step "Status $APP_NAME..."
    
    if is_running; then
        PID=$(cat "$PID_FILE")
        print_success "Aplikacja jest uruchomiona (PID: $PID)"
        
        # Sprawdzenie portu
        if is_port_occupied; then
            print_success "Port $APP_PORT jest aktywny"
        else
            print_warning "Port $APP_PORT nie jest aktywny"
        fi
        
        # Sprawdzenie API
        if curl -s "http://$APP_HOST:$APP_PORT/api/system/status" > /dev/null 2>&1; then
            print_success "API odpowiada"
        else
            print_warning "API nie odpowiada"
        fi
        
        # Informacje o procesie
        if ps -p $PID > /dev/null 2>&1; then
            CPU=$(ps -p $PID -o %cpu | tail -1 | tr -d ' ')
            MEM=$(ps -p $PID -o %mem | tail -1 | tr -d ' ')
            print_info "Użycie CPU: ${CPU}%, Pamięć: ${MEM}%"
        fi
        
    else
        print_warning "Aplikacja nie jest uruchomiona"
        
        # Sprawdzenie czy port jest zajęty przez inny proces
        if is_port_occupied; then
            print_warning "Port $APP_PORT jest zajęty przez inny proces"
            lsof -i :$APP_PORT
        fi
    fi
    
    # Informacje o systemie
    echo
    print_info "Informacje o systemie:"
    echo "  - Python: $($PYTHON_CMD --version 2>/dev/null || echo 'Nie zainstalowany')"
    echo "  - Virtual Environment: $([ -d "$VENV_DIR" ] && echo 'Dostępny' || echo 'Nie istnieje')"
    echo "  - Port: $APP_PORT"
    echo "  - Host: $APP_HOST"
    echo "  - Logi: $LOG_FILE"
}

# Wyświetlenie logów
show_logs() {
    print_step "Logi $APP_NAME..."
    
    if [ ! -f "$LOG_FILE" ]; then
        print_warning "Plik logów nie istnieje"
        return 1
    fi
    
    if [ "$1" = "follow" ]; then
        print_info "Wyświetlanie logów w czasie rzeczywistym (Ctrl+C aby zatrzymać)..."
        tail -f "$LOG_FILE"
    else
        print_info "Ostatnie 50 linii logów:"
        tail -50 "$LOG_FILE"
        echo
        print_info "Aby śledzić logi w czasie rzeczywistym: $0 logs follow"
    fi
}

# Uruchomienie testów
run_tests() {
    print_step "Uruchamianie testów $APP_NAME..."
    
    check_venv
    activate_venv
    check_dependencies
    
    echo
    print_info "Testy jednostkowe (nie wymagają uruchomionej aplikacji):"
    $PYTHON_CMD test_unit.py
    
    echo
    print_info "Testy integracyjne (wymagają uruchomionej aplikacji):"
    if is_running; then
        $PYTHON_CMD test_system.py
    else
        print_warning "Aplikacja nie jest uruchomiona. Uruchom testy po uruchomieniu aplikacji."
    fi
    
    echo
    print_info "Testy Stochastic Oscillator:"
    $PYTHON_CMD test_stochastic.py
}

# Wdrożenie nowej wersji
deploy_app() {
    print_step "Wdrażanie nowej wersji $APP_NAME..."
    
    print_info "Wersja docelowa: $APP_VERSION"
    
    # Sprawdzenie czy są niezacommitowane zmiany
    if [ -d ".git" ]; then
        if ! git diff-index --quiet HEAD --; then
            print_warning "Wykryto niezacommitowane zmiany. Zatwierdź je przed wdrożeniem."
            git status --short
            return 1
        fi
    fi
    
    # Zatrzymanie aplikacji
    if is_running; then
        print_info "Zatrzymywanie aplikacji przed wdrożeniem..."
        stop_app
    fi
    
    # Aktualizacja zależności
    print_step "Aktualizacja zależności..."
    check_venv
    activate_venv
    pip install -r requirements.txt --upgrade
    
    # Uruchomienie testów
    print_step "Uruchamianie testów po aktualizacji..."
    run_tests
    
    # Uruchomienie aplikacji
    print_step "Uruchamianie aplikacji po aktualizacji..."
    start_app
    
    print_success "Wdrożenie zakończone pomyślnie!"
}

# Informacje o wersji
show_version() {
    print_header
    echo "  Wersja: $APP_VERSION"
    echo "  Data: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  Python: $($PYTHON_CMD --version 2>/dev/null || echo 'Nie zainstalowany')"
    echo "  Katalog: $(pwd)"
    echo "  Użytkownik: $(whoami)"
    echo "  System: $(uname -s) $(uname -r)"
    echo
    print_info "Dostępne komendy:"
    echo "  start    - Uruchomienie aplikacji"
    echo "  stop     - Zatrzymanie aplikacji"
    echo "  restart  - Restart aplikacji"
    echo "  status   - Status aplikacji"
    echo "  logs     - Wyświetlenie logów"
    echo "  test     - Uruchomienie testów"
    echo "  deploy   - Wdrożenie nowej wersji"
    echo "  version  - Informacje o wersji"
}

# Główna logika
case "$1" in
    start)
        print_header
        start_app
        ;;
    stop)
        print_header
        stop_app
        ;;
    restart)
        print_header
        restart_app
        ;;
    status)
        print_header
        show_status
        ;;
    logs)
        print_header
        show_logs "$2"
        ;;
    test)
        print_header
        run_tests
        ;;
    deploy)
        print_header
        deploy_app
        ;;
    version)
        show_version
        ;;
    *)
        show_version
        echo
        print_error "Nieznana komenda: $1"
        echo
        print_info "Użycie: $0 [start|stop|restart|status|logs|test|deploy|version]"
        exit 1
        ;;
esac

exit 0

