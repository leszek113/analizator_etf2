# ETF Analyzer - Management Scripts

## 📋 Overview

This directory contains management scripts for the ETF Analyzer application.

## 🚀 Main Script: `manage-app.sh`

A comprehensive bash script for managing the ETF Analyzer application lifecycle.

### Usage

```bash
./scripts/manage-app.sh [COMMAND]
```

### Commands

| Command | Description |
|---------|-------------|
| `start` | Start the ETF Analyzer application |
| `stop` | Stop the running application |
| `restart` | Restart the application |
| `status` | Show application status and information |
| `logs` | Show recent application logs |
| `clean` | Clean up old processes and logs |
| `help` | Show help message |

### Examples

```bash
# Start the application
./scripts/manage-app.sh start

# Check status
./scripts/manage-app.sh status

# View logs
./scripts/manage-app.sh logs

# Restart the application
./scripts/manage-app.sh restart

# Stop the application
./scripts/manage-app.sh stop

# Clean up
./scripts/manage-app.sh clean
```

### Features

- ✅ **Process Management**: Automatic PID tracking and cleanup
- ✅ **Health Monitoring**: Port status and API health checks
- ✅ **Logging**: Centralized logging with log rotation
- ✅ **Error Handling**: Graceful shutdown and force kill fallback
- ✅ **Status Reporting**: Detailed status with memory, CPU, and uptime
- ✅ **Port Conflict Detection**: Prevents port conflicts on startup
- ✅ **Virtual Environment**: Automatic venv activation
- ✅ **Colored Output**: Easy-to-read colored status messages

### Configuration

The script automatically detects:
- Application directory
- Virtual environment location
- Port configuration (5005)
- PID and log file locations

### Files Created

- `etf-analyzer.pid` - Process ID file
- `etf-analyzer.log` - Application log file
- `etf-analyzer.lock` - Lock file (if needed)

### Requirements

- Bash shell
- Python 3.11+
- Virtual environment with required packages
- `lsof` command (usually pre-installed on macOS/Linux)
- `curl` command for health checks

### Troubleshooting

#### Port Already in Use
```bash
./scripts/manage-app.sh clean
./scripts/manage-app.sh start
```

#### Application Won't Start
```bash
./scripts/manage-app.sh logs
# Check for error messages in the logs
```

#### Stale PID File
```bash
./scripts/manage-app.sh clean
./scripts/manage-app.sh status
```

### Security Notes

- The script runs with your user permissions
- PID files are stored in the application directory
- Logs may contain sensitive information
- Use in production environments with caution

### Production Use

For production environments, consider:
- Using a proper process manager (systemd, supervisor)
- Implementing log rotation
- Adding monitoring and alerting
- Using environment-specific configurations
