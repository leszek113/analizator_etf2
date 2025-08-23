#!/bin/bash

# =============================================================================
# ETF Analyzer - Application Management Script
# =============================================================================
# 
# Usage: ./scripts/manage-app.sh [start|stop|restart|status|logs|clean]
# 
# Commands:
#   start   - Start the ETF Analyzer application
#   stop    - Stop the running application
#   restart - Restart the application
#   status  - Show application status and information
#   logs    - Show recent application logs
#   clean   - Clean up old processes and logs
# =============================================================================

# Configuration
APP_NAME="ETF Analyzer"
APP_PORT=${APP_PORT_OVERRIDE:-5005}
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_FILE="$APP_DIR/app.py"
VENV_DIR="$APP_DIR/venv"
PID_FILE="$APP_DIR/etf-analyzer.pid"
LOG_FILE="$APP_DIR/etf-analyzer.log"
LOCK_FILE="$APP_DIR/etf-analyzer.lock"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    local color=$1
    local message=$2
    echo -e "${color}[$(date '+%Y-%m-%d %H:%M:%S')] $message${NC}"
}

# Function to check if application is running
is_running() {
    # First check PID file
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        else
            # PID file exists but process is dead
            rm -f "$PID_FILE"
        fi
    fi
    
    # Check if any Python process is running app.py
    if pgrep -f "python.*app\.py" > /dev/null 2>&1; then
        return 0
    fi
    
    # Check if port is listening
    if lsof -i :$APP_PORT > /dev/null 2>&1; then
        return 0
    fi
    
    return 1
}

# Function to get running PID
get_running_pid() {
    # First try PID file
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "$pid"
            return 0
        fi
    fi
    
    # Try to find Python process running app.py
    local python_pid=$(pgrep -f "python.*app\.py" | head -1)
    if [ -n "$python_pid" ]; then
        echo "$python_pid"
        return 0
    fi
    
    # Try to find process using the port
    local port_pid=$(lsof -ti :$APP_PORT 2>/dev/null | head -1)
    if [ -n "$port_pid" ]; then
        echo "$port_pid"
        return 0
    fi
    
    echo ""
    return 1
}

# Function to get application status
get_status() {
    if is_running; then
        local pid=$(get_running_pid)
        if [ -z "$pid" ]; then
            echo -e "${RED}✗ $APP_NAME is NOT RUNNING${NC}"
            echo -e "  Port $APP_PORT is available"
            return 1
        fi
        
        local uptime=$(ps -o etime= -p "$pid" 2>/dev/null || echo "Unknown")
        local memory=$(ps -o rss= -p "$pid" 2>/dev/null | awk '{print $1/1024 " MB"}' || echo "Unknown")
        local cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null || echo "Unknown")
        
        echo -e "${GREEN}✓ $APP_NAME is RUNNING${NC}"
        echo -e "  PID: $pid"
        echo -e "  Port: $APP_PORT"
        echo -e "  Uptime: $uptime"
        echo -e "  Memory: $memory"
        echo -e "  CPU: $cpu%"
        
        # Check if port is listening
        if lsof -i :$APP_PORT > /dev/null 2>&1; then
            echo -e "  Port Status: ${GREEN}LISTENING${NC}"
        else
            echo -e "  Port Status: ${RED}NOT LISTENING${NC}"
        fi
        
        # Check API health
        if curl -s "http://localhost:$APP_PORT/api/system/status" > /dev/null 2>&1; then
            echo -e "  API Health: ${GREEN}HEALTHY${NC}"
            
            # Get system version
            local version=$(curl -s "http://localhost:$APP_PORT/api/system/version" | awk -F'"' '/"version":/ {print $4}' 2>/dev/null || echo "Unknown")
            echo -e "  System Version: ${CYAN}v$version${NC}"
        else
            echo -e "  API Health: ${RED}UNHEALTHY${NC}"
        fi
        
    else
        echo -e "${RED}✗ $APP_NAME is NOT RUNNING${NC}"
        echo -e "  Port $APP_PORT is available"
    fi
}

# Function to start application
start_app() {
    if is_running; then
        print_status $YELLOW "$APP_NAME is already running"
        get_status
        return 0
    fi
    
    # Check if port is available
    if lsof -i :$APP_PORT > /dev/null 2>&1; then
        print_status $RED "Port $APP_PORT is already in use by another process"
        lsof -i :$APP_PORT
        return 1
    fi
    
    # Check if app file exists
    if [ ! -f "$APP_FILE" ]; then
        print_status $RED "Application file not found: $APP_FILE"
        return 1
    fi
    
    # Check if virtual environment exists
    if [ ! -d "$VENV_DIR" ]; then
        print_status $RED "Virtual environment not found: $VENV_DIR"
        return 1
    fi
    
    print_status $BLUE "Starting $APP_NAME..."
    
    # Create log directory if it doesn't exist
    mkdir -p "$(dirname "$LOG_FILE")"
    
    # Start application in background
    cd "$APP_DIR"
    source "$VENV_DIR/bin/activate"
    
    # Start with nohup to keep it running
    nohup python "$APP_FILE" > "$LOG_FILE" 2>&1 &
    local pid=$!
    
    # Save PID to file
    echo $pid > "$PID_FILE"
    
    # Wait a moment and check if it started successfully
    sleep 3
    
    if is_running; then
        print_status $GREEN "$APP_NAME started successfully (PID: $pid)"
        print_status $BLUE "Logs: $LOG_FILE"
        print_status $BLUE "Dashboard: http://localhost:$APP_PORT"
        get_status
    else
        print_status $RED "Failed to start $APP_NAME"
        print_status $YELLOW "Check logs: $LOG_FILE"
        return 1
    fi
}

# Function to stop application
stop_app() {
    if ! is_running; then
        print_status $YELLOW "$APP_NAME is not running"
        return 0
    fi
    
    local pid=$(get_running_pid)
    if [ -z "$pid" ]; then
        print_status $RED "Could not determine PID of running application"
        return 1
    fi
    
    print_status $BLUE "Stopping $APP_NAME (PID: $pid)..."
    
    # Try graceful shutdown first
    kill "$pid" 2>/dev/null
    
    # Wait for graceful shutdown
    local count=0
    while [ $count -lt 10 ] && is_running; do
        sleep 1
        count=$((count + 1))
    done
    
    # Force kill if still running
    if is_running; then
        print_status $YELLOW "Force killing process..."
        kill -9 "$pid" 2>/dev/null
        sleep 1
    fi
    
    # Clean up PID file
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
    fi
    
    # Check if port is free
    if ! lsof -i :$APP_PORT > /dev/null 2>&1; then
        print_status $GREEN "$APP_NAME stopped successfully"
    else
        print_status $RED "Failed to stop $APP_NAME - port still in use"
        lsof -i :$APP_PORT
        return 1
    fi
}

# Function to restart application
restart_app() {
    print_status $BLUE "Restarting $APP_NAME..."
    stop_app
    sleep 2
    start_app
}

# Function to show logs
show_logs() {
    if [ -f "$LOG_FILE" ]; then
        print_status $BLUE "Recent logs from $LOG_FILE:"
        echo "----------------------------------------"
        tail -50 "$LOG_FILE"
    else
        print_status $YELLOW "No log file found: $LOG_FILE"
    fi
}

# Function to clean up
clean_up() {
    print_status $BLUE "Cleaning up $APP_NAME..."
    
    # Remove PID file if process is not running
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ! ps -p "$pid" > /dev/null 2>&1; then
            rm -f "$PID_FILE"
            print_status $GREEN "Removed stale PID file"
        fi
    fi
    
    # Remove lock file if exists
    if [ -f "$LOCK_FILE" ]; then
        rm -f "$LOCK_FILE"
        print_status $GREEN "Removed lock file"
    fi
    
    # Kill any remaining processes on the port
    local port_processes=$(lsof -ti :$APP_PORT 2>/dev/null)
    if [ -n "$port_processes" ]; then
        print_status $YELLOW "Killing processes using port $APP_PORT: $port_processes"
        echo "$port_processes" | xargs kill -9 2>/dev/null
    fi
    
    print_status $GREEN "Cleanup completed"
}

# Function to show help
show_help() {
    echo -e "${CYAN}$APP_NAME Management Script${NC}"
    echo "=================================="
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo -e "  ${GREEN}start${NC}   - Start the $APP_NAME application"
    echo -e "  ${GREEN}stop${NC}    - Stop the running application"
    echo -e "  ${GREEN}restart${NC} - Restart the application"
    echo -e "  ${GREEN}status${NC}  - Show application status and information"
    echo -e "  ${GREEN}logs${NC}    - Show recent application logs"
    echo -e "  ${GREEN}clean${NC}   - Clean up old processes and logs"
    echo -e "  ${GREEN}help${NC}    - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start"
    echo "  $0 status"
    echo "  $0 restart"
    echo ""
    echo "Configuration:"
    echo "  App Directory: $APP_DIR"
    echo "  Port: $APP_PORT"
    echo "  PID File: $PID_FILE"
    echo "  Log File: $LOG_FILE"
}

# Main script logic
case "${1:-help}" in
    start)
        start_app
        ;;
    stop)
        stop_app
        ;;
    restart)
        restart_app
        ;;
    status)
        get_status
        ;;
    logs)
        show_logs
        ;;
    clean)
        clean_up
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_status $RED "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac

