#!/bin/bash

# LTA Fantasy Bot Management Script for VPS

case "$1" in
    start)
        echo "🚀 Starting LTA Fantasy Bot..."
        cd ~/bots/ltafantasybot
        nohup python3 bot.py > bot.log 2>&1 &
        echo $! > bot.pid
        echo "✅ Bot started! PID: $(cat bot.pid)"
        echo "📋 View logs: tail -f ~/bots/ltafantasybot/bot.log"
        ;;
    
    stop)
        echo "🛑 Stopping LTA Fantasy Bot..."
        if [ -f bot.pid ]; then
            PID=$(cat bot.pid)
            kill $PID 2>/dev/null
            rm -f bot.pid
            echo "✅ Bot stopped!"
        else
            echo "❌ Bot PID file not found. Trying to kill by name..."
            pkill -f "python3 bot.py"
            echo "✅ Attempted to stop bot processes"
        fi
        ;;
    
    restart)
        echo "🔄 Restarting LTA Fantasy Bot..."
        $0 stop
        sleep 2
        $0 start
        ;;
    
    status)
        echo "📊 Bot Status:"
        if [ -f bot.pid ] && kill -0 $(cat bot.pid) 2>/dev/null; then
            echo "✅ Bot is running (PID: $(cat bot.pid))"
        else
            echo "❌ Bot is not running"
        fi
        echo ""
        echo "🔍 Recent logs (last 10 lines):"
        tail -10 ~/bots/ltafantasybot/bot.log 2>/dev/null || echo "No log file found"
        ;;
    
    logs)
        echo "📋 Bot logs (press Ctrl+C to exit):"
        tail -f ~/bots/ltafantasybot/bot.log
        ;;
    
    test)
        echo "🧪 Testing API connectivity..."
        cd ~/bots/ltafantasybot
        python3 -c "
import sys
sys.path.insert(0, '.')
import bot
import asyncio

async def test():
    session = bot.make_session()
    try:
        result = await bot.fetch_json(session, f'{bot.BASE}/leagues/active')
        print('✅ API working!')
    except Exception as e:
        if 'League not found' in str(e) or '404' in str(e):
            print('✅ Worker proxy working (API endpoint/token issue is normal)')
        else:
            print(f'❌ Issue: {e}')
    finally:
        await session.close()

asyncio.run(test())
"
        ;;
    
    *)
        echo "LTA Fantasy Bot Management"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs|test}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the bot in background"
        echo "  stop    - Stop the bot"
        echo "  restart - Restart the bot"
        echo "  status  - Show bot status and recent logs"
        echo "  logs    - Show live bot logs"
        echo "  test    - Test API connectivity"
        echo ""
        exit 1
        ;;
esac
