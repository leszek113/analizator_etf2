#!/bin/bash

# =============================================================================
# ETF Analyzer - Skrypt Automatycznego Zwiększania Wersji
# =============================================================================
# 
# Użycie:
#   ./bump-version.sh [patch|minor|major]
# 
# Przykłady:
#   ./bump-version.sh patch    # 1.9.19 -> 1.9.20
#   ./bump-version.sh minor    # 1.9.19 -> 1.10.0
#   ./bump-version.sh major    # 1.9.19 -> 2.0.0
# =============================================================================

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
    echo "  ETF Analyzer - Automatyczne Zwiększanie Wersji"
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

# Sprawdzenie argumentów
if [ $# -eq 0 ]; then
    print_error "Brak argumentu. Użycie: $0 [patch|minor|major]"
    echo
    echo "Przykłady:"
    echo "  $0 patch    # 1.9.19 -> 1.9.20"
    echo "  $0 minor    # 1.9.19 -> 1.10.0"
    echo "  $0 major    # 1.9.19 -> 2.0.0"
    exit 1
fi

BUMP_TYPE=$1

# Walidacja typu bump
if [[ ! "$BUMP_TYPE" =~ ^(patch|minor|major)$ ]]; then
    print_error "Nieprawidłowy typ bump: $BUMP_TYPE"
    print_error "Dozwolone typy: patch, minor, major"
    exit 1
fi

print_header

# Sprawdzenie czy jesteśmy w głównym katalogu projektu
if [ ! -f "config.py" ]; then
    print_error "Nie jesteś w głównym katalogu projektu. Uruchom z katalogu głównego."
    exit 1
fi

# Sprawdzenie czy git jest dostępny
if ! command -v git &> /dev/null; then
    print_error "Git nie jest zainstalowany lub nie jest dostępny"
    exit 1
fi

# Sprawdzenie czy jesteśmy w repozytorium git
if [ ! -d ".git" ]; then
    print_error "Nie jesteś w repozytorium git"
    exit 1
fi

# Sprawdzenie czy working directory jest clean
if [ -n "$(git status --porcelain)" ]; then
    print_warning "Working directory nie jest clean. Masz niezcommitowane zmiany."
    print_info "Zalecane: commit lub stash zmian przed bump wersji"
    read -p "Kontynuować mimo to? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Anulowano bump wersji"
        exit 0
    fi
fi

# Pobranie aktualnej wersji
print_step "Pobieranie aktualnej wersji..."
CURRENT_VERSION=$(python3 -c "from config import __version__; print(__version__)" 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$CURRENT_VERSION" ]; then
    print_error "Nie można odczytać aktualnej wersji z config.py"
    exit 1
fi

print_info "Aktualna wersja: $CURRENT_VERSION"

# Parsowanie wersji
IFS='.' read -ra VERSION_PARTS <<< "$CURRENT_VERSION"
MAJOR=${VERSION_PARTS[0]}
MINOR=${VERSION_PARTS[1]}
PATCH=${VERSION_PARTS[2]}

# Obliczenie nowej wersji
case $BUMP_TYPE in
    "patch")
        NEW_PATCH=$((PATCH + 1))
        NEW_VERSION="$MAJOR.$MINOR.$NEW_PATCH"
        print_info "Zwiększanie patch: $CURRENT_VERSION -> $NEW_VERSION"
        ;;
    "minor")
        NEW_MINOR=$((MINOR + 1))
        NEW_VERSION="$MAJOR.$NEW_MINOR.0"
        print_info "Zwiększanie minor: $CURRENT_VERSION -> $NEW_VERSION"
        ;;
    "major")
        NEW_MAJOR=$((MAJOR + 1))
        NEW_VERSION="$NEW_MAJOR.0.0"
        print_info "Zwiększanie major: $CURRENT_VERSION -> $NEW_VERSION"
        ;;
esac

# Aktualizacja config.py
print_step "Aktualizacja config.py..."
sed -i.bak "s/__version__ = \"$CURRENT_VERSION\"/__version__ = \"$NEW_VERSION\"/" config.py

if [ $? -eq 0 ]; then
    print_success "config.py zaktualizowany"
    rm -f config.py.bak
else
    print_error "Błąd podczas aktualizacji config.py"
    exit 1
fi

# Aktualizacja app.py (jeśli ma hardcoded wersję)
print_step "Sprawdzanie app.py..."
if grep -q "__version__ = \"$CURRENT_VERSION\"" app.py 2>/dev/null; then
    sed -i.bak "s/__version__ = \"$CURRENT_VERSION\"/# Wersja importowana z config.py/" app.py
    print_success "app.py zaktualizowany"
    rm -f app.py.bak
fi

# Aktualizacja manage-app.sh (jeśli ma hardcoded wersję)
print_step "Sprawdzanie manage-app.sh..."
if grep -q "APP_VERSION=\"v$CURRENT_VERSION\"" scripts/manage-app.sh 2>/dev/null; then
    sed -i.bak "s/APP_VERSION=\"v$CURRENT_VERSION\"/# Wersja pobierana dynamicznie/" scripts/manage-app.sh
    print_success "manage-app.sh zaktualizowany"
    rm -f scripts/manage-app.sh.bak
fi

# Aktualizacja CHANGELOG.md
print_step "Aktualizacja CHANGELOG.md..."
CURRENT_DATE=$(date +%Y-%m-%d)
CHANGELOG_ENTRY="# [$NEW_VERSION] - $CURRENT_DATE

### 🚀 **Nowa Wersja**
- **Wersja**: $NEW_VERSION
- **Data**: $CURRENT_DATE
- **Typ**: $BUMP_TYPE bump
- **Status**: W trakcie rozwoju

### 📝 **Dodaj zmiany tutaj**
- 

"

# Dodanie nowego wpisu na początku CHANGELOG.md
echo -e "$CHANGELOG_ENTRY\n$(cat CHANGELOG.md)" > CHANGELOG.md
print_success "CHANGELOG.md zaktualizowany"

# Git operations
print_step "Git operations..."

# Dodanie zmian
git add config.py app.py scripts/manage-app.sh CHANGELOG.md 2>/dev/null
git add . 2>/dev/null

# Commit
git commit -m "Bump version: $CURRENT_VERSION -> $NEW_VERSION

🔧 Automatyczne zwiększenie wersji: $BUMP_TYPE
📅 Data: $CURRENT_DATE
📝 Zaktualizowano: config.py, app.py, manage-app.sh, CHANGELOG.md"

if [ $? -eq 0 ]; then
    print_success "Git commit utworzony"
else
    print_warning "Git commit nie powiódł się (może nie ma zmian do commitowania)"
fi

# Tag
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"
if [ $? -eq 0 ]; then
    print_success "Git tag v$NEW_VERSION utworzony"
else
    print_warning "Git tag nie powiódł się"
fi

# Final message
echo
print_success "Wersja została zwiększona: $CURRENT_VERSION -> $NEW_VERSION"
print_info "Następne kroki:"
echo "  1. Sprawdź zmiany: git log --oneline -5"
echo "  2. Wypchnij na GitHub: git push origin main --tags"
echo "  3. Przetestuj aplikację: ./scripts/manage-app.sh restart"
echo "  4. Zaktualizuj dokumentację jeśli potrzeba"
echo

print_info "Aktualna wersja w config.py: $NEW_VERSION"
print_info "Git tag: v$NEW_VERSION"
print_info "Commit: $(git rev-parse --short HEAD)"
