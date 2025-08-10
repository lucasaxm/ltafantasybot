# LTA Fantasy Bot

A Telegram bot that monitors LTA Fantasy league scores and provides real-time updates in both private chats and groups.

## Features

- 🏆 Get current league standings with `/scores`
- 📱 Monitor leagues for live updates 
- 👥 **Group Support** - Attach leagues to groups for live monitoring
- 🔄 Automatic polling for score changes during events
- 🔐 Access control (owner in private, admins in groups)
- 🚀 Cloudflare bypass using optimized headers
- 💾 Persistent group-league mappings
- 🤐 **Silent Operation** - Only responds to its own valid commands
- 📋 **Smart Command Menu** - Context-aware command suggestions when typing `/`

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

# Optional: logging level (DEBUG, INFO, WARNING, ERROR - default: INFO)
LOG_LEVEL=INFO
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

### Private Chat Commands:

- `/start` - Show help message
- `/scores <league_slug>` - Get current standings for a league
- `/watch <league_slug>` - Start monitoring league for updates
- `/unwatch` - Stop monitoring
- `/auth <token>` - Update session token at runtime

### Group Commands (Admin Only):

- `/setleague <league_slug>` - Attach a league to this group
- `/getleague` - Show the current attached league
- `/startwatch` - Start monitoring the group's league
- `/stopwatch` - Stop monitoring
- `/scores` - Get current standings for the group's league

### Example Usage:

**In Private Chat:**
```
/scores regata-exrzlize75
/watch regata-exrzlize75
```

**In Group Chat (as admin):**
```
/setleague regata-exrzlize75
/startwatch
/scores
```

## How it Works

1. **Cloudflare Bypass**: Uses `bruno-runtime/2.9.0` User-Agent to avoid bot detection
2. **Session Management**: Maintains aiohttp sessions with proper headers
3. **Group Support**: Each group can be attached to one league with persistent storage
4. **Smart Live Updates**: 
   - Sends **one message** that gets **edited every 30 seconds** with live scores
   - Shows ⬆️ **up arrows** when player scores increase
   - Shows ⬇️ **down arrows** when player scores decrease  
   - Includes 🕒 **timestamp** showing last update time
   - Only sends **new messages** when team rankings actually change (🔄 "RANKING CHANGED!")
5. **Minimal Spam**: Edits same message for score updates, new messages only for ranking changes
6. **Access Control**: Private chat (owner only) and group chat (admins only)
7. **Silent Operation**: Ignores unknown commands to coexist with other bots
8. **Error Handling**: Graceful handling of auth failures and API errors

## API Endpoints Used

- `/leagues/{slug}/rounds` - Get league rounds
- `/leagues/{slug}/ranking` - Get team rankings
- `/rosters/per-round/{round_id}/{team_id}` - Get individual team scores

## Security

- **Private Chat**: Only specified Telegram user (ALLOWED_USER_ID) can use bot
- **Group Chat**: Only group administrators can manage league settings and monitoring
- **Data Persistence**: Group settings stored in local JSON file
- **Environment Variables**: All sensitive data in .env file
- **No Hardcoded Credentials**: All secrets externalized

## File Structure

```
ltafantasybot/
├── bot.py                 # Main bot code
├── .env                   # Your secrets (gitignored)
├── .env.example           # Template
├── group_settings.json    # Group-league mappings (auto-created)
├── requirements.txt       # Dependencies
├── README.md             # This file
└── .gitignore            # Git protection
```

## Troubleshooting

### Bot gets 403 errors:
- Update your `X_SESSION_TOKEN` in `.env` and try again
- Use `/auth <new_token>` to update at runtime
- Some VPS ranges get stricter Cloudflare checks. You can:
   - Set `FORCE_IPV4=true` in `.env` to avoid IPv6 paths
   - If your browser session passes but server doesn't, copy your Cloudflare clearance cookie into `.env`:
      - `CF_CLEARANCE=<value>` and optionally `_lolfantasy_session` as `LTAFANTASY_SESSION=<value>`
   - If you access through a corporate/egress proxy, set `HTTPS_PROXY`/`HTTP_PROXY` and the bot will use it

### Bot doesn't respond:
- Check `ALLOWED_USER_ID` matches your Telegram ID
- Ensure you're messaging the bot in a private chat

### "Conflict" errors:
- Only one bot instance can run at a time
- Kill any existing processes before starting

### Enable detailed logging:
- Set `LOG_LEVEL=DEBUG` in `.env` to see API requests and detailed operation logs
- Use `LOG_LEVEL=WARNING` to reduce log output
- Default is `LOG_LEVEL=INFO` for normal operation

## Development

The bot uses:
- `python-telegram-bot` for Telegram integration
- `aiohttp` for async HTTP requests  
- Environment variables for configuration
- Async/await for concurrent API calls
- Optional: Cloudflare mitigation via Bruno UA, IPv4-only connector, and cookie support

## License

This project is for personal use with LTA Fantasy leagues.
