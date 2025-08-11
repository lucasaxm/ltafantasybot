#!/bin/bash

# LTA Fantasy Bot Management Script for VPS

# Configuration
BOT_DIR="${BOT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
BOT_SCRIPT="bot.py"
VENV_PATH="$BOT_DIR/.venv/bin/activate"
PID_FILE="$BOT_DIR/bot.pid"
LOG_FILE="$BOT_DIR/bot.log"

# Color codes for better output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Validation functions
check_bot_dir() {
    if [ ! -d "$BOT_DIR" ]; then
        echo -e "${RED}❌ Bot directory not found: $BOT_DIR${NC}"
        exit 1
    fi
}

check_venv() {
    if [ ! -f "$VENV_PATH" ]; then
        echo -e "${YELLOW}⚠️ Virtual environment not found at: $VENV_PATH${NC}"
        echo -e "${YELLOW}Please create virtual environment first: python3 -m venv .venv${NC}"
        exit 1
    fi
}

check_bot_script() {
    if [ ! -f "$BOT_DIR/$BOT_SCRIPT" ]; then
        echo -e "${RED}❌ Bot script not found: $BOT_DIR/$BOT_SCRIPT${NC}"
        exit 1
    fi
}

activate_venv() {
    check_venv
    source "$VENV_PATH" || {
        echo -e "${RED}❌ Failed to activate virtual environment${NC}"
        exit 1
    }
}

is_bot_running() {
    [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE" 2>/dev/null) 2>/dev/null
}

case "$1" in
    start)
        echo -e "${BLUE}🚀 Starting LTA Fantasy Bot...${NC}"
        
        # Pre-flight checks
        check_bot_dir
        check_bot_script
        
        # Check if already running
        if is_bot_running; then
            echo -e "${YELLOW}⚠️ Bot is already running (PID: $(cat "$PID_FILE"))${NC}"
            exit 1
        fi
        
        cd "$BOT_DIR" || exit 1
        activate_venv
        
        # Start bot with better error handling
        nohup python3 "$BOT_SCRIPT" > "$LOG_FILE" 2>&1 &
        BOT_PID=$!
        echo $BOT_PID > "$PID_FILE"
        
        # Verify startup
        sleep 2
        if is_bot_running; then
            echo -e "${GREEN}✅ Bot started successfully! PID: $BOT_PID${NC}"
            echo -e "${BLUE}📋 View logs: tail -f $LOG_FILE${NC}"
        else
            echo -e "${RED}❌ Bot failed to start. Check logs for details.${NC}"
            echo -e "${YELLOW}Recent logs:${NC}"
            tail -10 "$LOG_FILE" 2>/dev/null || echo "No log file found"
            rm -f "$PID_FILE"
            exit 1
        fi
        ;;
    
    stop)
        echo -e "${BLUE}🛑 Stopping LTA Fantasy Bot...${NC}"
        
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if kill -0 $PID 2>/dev/null; then
                # Try graceful shutdown first
                kill -TERM $PID 2>/dev/null
                sleep 3
                
                # Check if still running
                if kill -0 $PID 2>/dev/null; then
                    echo -e "${YELLOW}⚠️ Graceful shutdown failed, forcing stop...${NC}"
                    kill -KILL $PID 2>/dev/null
                fi
                
                # Wait for process to actually stop
                for i in {1..10}; do
                    if ! kill -0 $PID 2>/dev/null; then
                        break
                    fi
                    sleep 1
                done
                
                rm -f "$PID_FILE"
                echo -e "${GREEN}✅ Bot stopped successfully!${NC}"
            else
                echo -e "${YELLOW}⚠️ PID file exists but process not running${NC}"
                rm -f "$PID_FILE"
            fi
        else
            echo -e "${YELLOW}❌ Bot PID file not found. Trying to kill by name...${NC}"
            if pkill -f "python3.*$BOT_SCRIPT"; then
                echo -e "${GREEN}✅ Bot processes stopped${NC}"
            else
                echo -e "${RED}❌ No bot processes found${NC}"
            fi
        fi
        ;;
    
    restart)
        echo "🔄 Restarting LTA Fantasy Bot..."
        $0 stop
        sleep 2
        $0 start
        ;;
    
    status)
        echo -e "${BLUE}📊 Bot Status:${NC}"
        
        if is_bot_running; then
            PID=$(cat "$PID_FILE")
            echo -e "${GREEN}✅ Bot is running (PID: $PID)${NC}"
            
            # Show process info if available
            if command -v ps >/dev/null 2>&1; then
                echo -e "${BLUE}📈 Process info:${NC}"
                ps -p $PID -o pid,ppid,pcpu,pmem,etime,cmd 2>/dev/null || echo "Process info unavailable"
            fi
        else
            echo -e "${RED}❌ Bot is not running${NC}"
            if [ -f "$PID_FILE" ]; then
                echo -e "${YELLOW}⚠️ Stale PID file found, cleaning up...${NC}"
                rm -f "$PID_FILE"
            fi
        fi
        
        echo ""
        echo -e "${BLUE}🔍 Recent logs (last 10 lines):${NC}"
        if [ -f "$LOG_FILE" ]; then
            tail -10 "$LOG_FILE" | while IFS= read -r line; do
                echo "  $line"
            done
        else
            echo -e "${YELLOW}  No log file found${NC}"
        fi
        
        # Show log file info
        if [ -f "$LOG_FILE" ]; then
            LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
            LOG_LINES=$(wc -l < "$LOG_FILE" 2>/dev/null || echo "unknown")
            echo -e "${BLUE}📄 Log file: $LOG_FILE ($LOG_SIZE, $LOG_LINES lines)${NC}"
        fi
        ;;
    
    logs)
        if [ ! -f "$LOG_FILE" ]; then
            echo -e "${YELLOW}❌ Log file not found: $LOG_FILE${NC}"
            exit 1
        fi
        
        case "${2:-tail}" in
            "head")
                echo -e "${BLUE}📋 Bot logs (first 50 lines):${NC}"
                head -50 "$LOG_FILE"
                ;;
            "clear")
                echo -e "${YELLOW}🗑️ Clearing log file...${NC}"
                > "$LOG_FILE"
                echo -e "${GREEN}✅ Log file cleared${NC}"
                ;;
            "size")
                LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
                LOG_LINES=$(wc -l < "$LOG_FILE" 2>/dev/null || echo "unknown")
                echo -e "${BLUE}📊 Log file stats: $LOG_SIZE, $LOG_LINES lines${NC}"
                ;;
            *)
                echo -e "${BLUE}📋 Bot logs (press Ctrl+C to exit):${NC}"
                tail -f "$LOG_FILE"
                ;;
        esac
        ;;
        
    install)
        echo -e "${BLUE}📦 Installing/updating bot dependencies...${NC}"
        check_bot_dir
        cd "$BOT_DIR" || exit 1
        
        # Check if virtual environment exists, create if needed
        if [ ! -f "$VENV_PATH" ]; then
            echo -e "${YELLOW}⚠️ Virtual environment not found. Creating one...${NC}"
            python3 -m venv .venv
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}✅ Virtual environment created successfully${NC}"
            else
                echo -e "${RED}❌ Failed to create virtual environment${NC}"
                exit 1
            fi
        fi
        
        # Activate virtual environment
        activate_venv
        
        # Upgrade pip first
        echo -e "${BLUE}📈 Upgrading pip...${NC}"
        python3 -m pip install --upgrade pip --quiet
        
        # Install/update dependencies
        if [ -f "requirements.txt" ]; then
            echo -e "${BLUE}📋 Installing/updating dependencies from requirements.txt...${NC}"
            pip install -r requirements.txt --upgrade
            
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}✅ Dependencies installed/updated successfully${NC}"
            else
                echo -e "${RED}❌ Failed to install/update dependencies${NC}"
                exit 1
            fi
        else
            echo -e "${RED}❌ requirements.txt not found${NC}"
            echo "Create a requirements.txt file with your dependencies first"
            exit 1
        fi
        ;;
        
    update)
        echo -e "${YELLOW}� Note: 'update' is an alias for 'install' - they do the same thing${NC}"
        $0 install
        ;;
        
    test)
        echo -e "${BLUE}🧪 Running bot health check and tests...${NC}"
        check_bot_dir
        check_bot_script
        check_venv
        
        cd "$BOT_DIR" || exit 1
        activate_venv
        
        echo -e "${GREEN}✅ Basic environment checks passed${NC}"
        echo -e "${BLUE}📋 Environment info:${NC}"
        echo "  Bot directory: $BOT_DIR"
        echo "  Virtual env: $VENV_PATH"
        echo "  Python version: $(python3 --version 2>/dev/null || echo 'Not available')"
        echo "  Bot script: $BOT_SCRIPT"
        
        echo -e "\n${BLUE}🧪 Running comprehensive test suite...${NC}"
        if [ -f "test_bot.py" ]; then
            python3 test_bot.py
        else
            echo -e "${RED}❌ test_bot.py not found${NC}"
            echo "Please ensure test_bot.py exists for comprehensive testing"
            exit 1
        fi
        ;;
        
    health)
        echo -e "${YELLOW}💡 Note: 'health' is an alias for 'test' - they do the same thing${NC}"
        $0 test
        ;;
    
    *)
        echo -e "${BLUE}LTA Fantasy Bot Management${NC}"
        echo ""
        echo -e "${GREEN}Usage: $0 {start|stop|restart|status|logs|test|install}${NC}"
        echo ""
        echo -e "${YELLOW}Core Commands:${NC}"
        echo "  start    - Start the bot in background"
        echo "  stop     - Stop the bot (graceful shutdown)"
        echo "  restart  - Restart the bot (stop + start)"
        echo "  status   - Show bot status, process info and recent logs"
        echo "  logs     - Show live bot logs (or 'logs head/clear/size')"
        echo "  test     - Run comprehensive health check and tests"
        echo "  install  - Install/update dependencies in virtual environment"
        echo ""
        echo -e "${YELLOW}Aliases:${NC}"
        echo "  health   - Same as 'test'"
        echo "  update   - Same as 'install'"
        echo ""
        echo -e "${BLUE}Examples:${NC}"
        echo "  $0 install          - Setup/update dependencies (handles both fresh install and updates)"
        echo "  $0 test             - Run all health checks and tests"
        echo "  $0 logs head        - Show first 50 log lines"
        echo "  $0 logs clear       - Clear the log file"
        echo "  $0 logs size        - Show log file statistics"
        echo ""
        echo -e "${YELLOW}Setup Workflow:${NC}"
        echo "  1. Clone the repository"
        echo "  2. Configure .env file with your tokens"
        echo "  3. Run: $0 install"
        echo "  4. Run: $0 test"
        echo "  5. Run: $0 start"
        echo ""
        exit 1
        ;;
esac
