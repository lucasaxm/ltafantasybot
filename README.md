# LTA Fantasy Bot

A Telegram bot that monitors LTA Fantasy league scores and provides real-time updates.

## Features

- 🏆 Get current league standings with `/scores <league_slug>`
- 📱 Watch leagues for live updates with `/watch <league_slug>`
- 🔄 Automatic polling for score changes
- 🔐 User access control for security
- 🚀 Cloudflare bypass using optimized headers

## Setup

### 1. Prerequisites

- Python 3.12+
- Telegram Bot Token (from @BotFather)
- LTA Fantasy session token

### 2. Installation

```bash
# Clone/download the bot files
cd ltafantasybot

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

### 3. Configuration

Edit `.env` file with your credentials:

```env
# Get this from @BotFather on Telegram
BOT_TOKEN=your_telegram_bot_token_here

# Your Telegram user ID (get from @userinfobot)
ALLOWED_USER_ID=your_telegram_user_id

# LTA Fantasy session token (see below how to get)
X_SESSION_TOKEN=your_lta_fantasy_session_token

# Optional: polling interval in seconds (default: 30)
POLL_SECS=30
```

### 4. Getting LTA Fantasy Session Token

1. Log into [ltafantasy.com](https://ltafantasy.com) in your browser
2. Open Developer Tools (F12)
3. Go to **Network** tab
4. Make any API request on the site
5. Find a request to `api.ltafantasy.com`
6. Copy the `x-session-token` header value
7. Paste it in your `.env` file

## Usage

### Start the bot:
```bash
python bot.py
```

### Available Commands:

- `/start` - Show help message
- `/scores <league_slug>` - Get current standings for a league
- `/watch <league_slug>` - Start monitoring league for updates
- `/unwatch` - Stop monitoring
- `/auth <token>` - Update session token at runtime

### Example:
```
/scores regata-exrzlize75
/watch regata-exrzlize75
```

## How it Works

1. **Cloudflare Bypass**: Uses `bruno-runtime/2.9.0` User-Agent to avoid bot detection
2. **Session Management**: Maintains aiohttp sessions with proper headers
3. **Live Updates**: Polls API every 30 seconds (configurable)
4. **Smart Notifications**: Only sends updates when scores actually change
5. **Error Handling**: Graceful handling of auth failures and API errors

## API Endpoints Used

- `/leagues/{slug}/rounds` - Get league rounds
- `/leagues/{slug}/ranking` - Get team rankings
- `/rosters/per-round/{round_id}/{team_id}` - Get individual team scores

## Security

- User access control (only specified Telegram user can use bot)
- Private chat only (won't respond in groups)
- Environment variables for sensitive data
- No hardcoded credentials in code

## Troubleshooting

### Bot gets 403 errors:
- Update your `X_SESSION_TOKEN` in `.env`
- Use `/auth <new_token>` to update at runtime

### Bot doesn't respond:
- Check `ALLOWED_USER_ID` matches your Telegram ID
- Ensure you're messaging the bot in a private chat

### "Conflict" errors:
- Only one bot instance can run at a time
- Kill any existing processes before starting

## Development

The bot uses:
- `python-telegram-bot` for Telegram integration
- `aiohttp` for async HTTP requests  
- Environment variables for configuration
- Async/await for concurrent API calls

## License

This project is for personal use with LTA Fantasy leagues.
