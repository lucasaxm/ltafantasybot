# LTA Fantasy Bot

A Telegram bot for monitoring LTA Fantasy league scores and rankings with real-time notifications.

## Features

- **Real-time Score Monitoring**: Automatically polls and reports score changes in your fantasy leagues
- **Champion Name Mapping**: Shows League of Legends champion names in team details with pick success indicators
- **Ranking Notifications**: Get notified when team rankings change
- **Multi-League Support**: Monitor multiple leagues simultaneously
- **Smart API Routing**: Auto-detects best API endpoint (direct vs Cloudflare Worker proxy)
- **VPS-Friendly**: Built-in Cloudflare bypass for server deployments
- **Group Support**: Full group chat integration with admin controls
- **Secure Configuration**: Environment-based configuration with sensitive data protection

## Quick Start

### Prerequisites

- Python 3.8+
- A Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- LTA Fantasy session token

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/lucasaxm/ltafantasybot.git
   cd ltafantasybot
   ```

2. **Install dependencies and setup environment**
   ```bash
   ./manage-bot.sh install
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Test your setup**
   ```bash
   ./manage-bot.sh test
   ```

5. **Run the bot**
   ```bash
   ./manage-bot.sh start
   ```

## Configuration

The bot uses environment variables for configuration. Create a `.env` file in the project root:

### Required Configuration

```bash
# Telegram Bot Configuration
BOT_TOKEN=your_telegram_bot_token_here
ALLOWED_USER_ID=your_telegram_user_id

# LTA Fantasy API Token
X_SESSION_TOKEN=your_lta_fantasy_session_token
```

### Optional Configuration

```bash
# Bot Settings
POLL_SECS=30                    # How often to check for updates (seconds)
LOG_LEVEL=INFO                  # Logging level (DEBUG, INFO, WARNING, ERROR)

# Champion Configuration (League of Legends champion name mapping)
CHAMPION_API_URL=https://ddragon.leagueoflegends.com/cdn/15.16.1/data/en_US/champion.json
CHAMPION_CACHE_TTL=86400        # Champion data cache duration (24 hours)
CHAMPION_API_TIMEOUT=10         # Champion API request timeout (seconds)

# API Endpoint Configuration
LTA_API_URL=https://api.ltafantasy.com        # Direct API (default)
# OR for VPS with Cloudflare challenges:
# LTA_API_URL=https://your-worker.workers.dev  # Cloudflare Worker proxy
```

## Simple API Endpoint Configuration

The bot uses a single `LTA_API_URL` setting for maximum simplicity:

- **Direct API**: `LTA_API_URL=https://api.ltafantasy.com` (default)
- **Cloudflare Worker Proxy**: `LTA_API_URL=https://your-worker.workers.dev`

Users simply choose which endpoint to use based on their deployment:
- **Local Development**: Use direct API (default)  
- **VPS with Cloudflare challenges**: Use Worker proxy URL

### Why Use Cloudflare Worker?

If you're running the bot on a VPS, you might encounter Cloudflare challenges that block direct API access. The [Cloudflare Worker](./cloudflare-worker/README.md) acts as a proxy with the correct headers to bypass these restrictions.

**For VPS deployments with Cloudflare issues**: See the [Cloudflare Worker setup guide](./cloudflare-worker/README.md).

## Champion Mapping Feature

The bot includes intelligent champion name mapping for League of Legends champions, enhancing team and player information with human-readable champion names.

### How It Works

- **Owner's Picks**: Shows which champion the team owner selected for each player
- **Actual Games**: Displays champions actually played in each game
- **Pick Success Indicators**:
  - ✅ **Green checkmark** with game number when owner's pick matches actual game
  - ☑️ **Gray checkmark** when owner's pick doesn't match any game

### Example Output

```
⚔️ Robo (LOUD)
✅ Rumble (Game 2)
💰 12.7M • 📊 27.28 pts

Game 1 vs Fluxo W7M: 20.16 (Gwen)
Game 2 vs Fluxo W7M: 42.73 (x1.3) (Rumble)  ← Successful pick with multiplier!
Game 3 vs Fluxo W7M: 18.95 (Renekton)
```

### Strategic Value

- **Instant Feedback**: See which champion predictions were correct
- **Multiplier Tracking**: Successful picks earn bonus multipliers (1.3x, 1.5x, etc.)
- **Performance Analysis**: Compare owner strategy vs actual player performance

### Configuration

Champion data is automatically cached for 24 hours from Riot's official Data Dragon API:

```bash
CHAMPION_API_URL=https://ddragon.leagueoflegends.com/cdn/15.16.1/data/en_US/champion.json
CHAMPION_CACHE_TTL=86400  # 24 hours (champion data doesn't change often)
CHAMPION_API_TIMEOUT=10   # 10 seconds timeout for API requests
```

## Getting Your Session Token

1. Log in to [LTA Fantasy](https://ltafantasy.com) in your browser
2. Open Developer Tools (F12)
3. Go to Network tab and refresh the page
4. Find any request to `api.ltafantasy.com`
5. Copy the `x-session-token` header value

## Bot Commands

### Private Chat Commands
- `/start` - Initialize the bot
- `/scores <league_name>` - Get current scores for a league
- `/team <team_name>` - Get detailed team information with champion picks
- `/owner <owner_name>` - Get team information by owner name
- `/watch <league_name>` - Start monitoring a league
- `/unwatch` - Stop monitoring
- `/auth <token>` - Update session token

### Group Chat Commands (Admin Only)
- `/setleague <league_name>` - Attach a league to this group
- `/getleague` - Get current league information
- `/startwatch` - Start watching the group's league
- `/stopwatch` - Stop watching
- `/scores` - Get current scores for group's league
- `/team <team_name>` - Get detailed team information for group's league
- `/owner <owner_name>` - Get team information by owner name for group's league

## Management Script

The bot includes a comprehensive management script for easy deployment and maintenance. The script automatically handles virtual environment setup, dependency management, and bot lifecycle operations.

### Core Commands

```bash
# Setup and dependency management
./manage-bot.sh install    # Install/update dependencies (handles both fresh installs and updates)
./manage-bot.sh test       # Run comprehensive health checks and tests

# Bot lifecycle
./manage-bot.sh start      # Start the bot in background
./manage-bot.sh stop       # Stop the bot (graceful shutdown)
./manage-bot.sh restart    # Restart the bot (stop + start)

# Monitoring and logs
./manage-bot.sh status     # Show bot status, process info and recent logs
./manage-bot.sh logs       # Show live bot logs (or 'logs head/clear/size')
```

### Advanced Log Commands

```bash
./manage-bot.sh logs head   # Show first 50 log lines
./manage-bot.sh logs clear  # Clear the log file
./manage-bot.sh logs size   # Show log file statistics
```

### Setup Workflow

```bash
# 1. Clone and enter directory
git clone https://github.com/lucasaxm/ltafantasybot.git
cd ltafantasybot

# 2. Install dependencies and setup virtual environment
./manage-bot.sh install

# 3. Configure your .env file
cp .env.example .env
# Edit .env with your tokens

# 4. Run comprehensive tests
./manage-bot.sh test

# 5. Start the bot
./manage-bot.sh start
```

The management script automatically:
- Creates and manages Python virtual environment (`.venv`)
- Handles dependency installation and updates
- Provides comprehensive health checks and API testing
- Manages bot process lifecycle with proper PID tracking
- Offers detailed logging and monitoring capabilities

## Project Structure

```
├── bot.py                 # Main bot application entry point
├── test_bot.py            # Comprehensive test suite for validation
├── manage-bot.sh          # Management script with virtual environment support
├── requirements.txt       # Python dependencies
├── .env                   # Environment configuration
├── .env.example          # Configuration template
├── ltabot/               # Modular bot package
│   ├── __init__.py       # Package exports and compatibility layer
│   ├── app.py           # Application bootstrap and wiring
│   ├── config.py        # Environment configuration and caching
│   ├── api.py           # LTA Fantasy API interactions
│   ├── champions.py     # Champion ID to name mapping (Riot API)
│   ├── commands.py      # Telegram command handlers
│   ├── formatting.py    # Message formatting utilities
│   ├── auth.py          # Access control and permissions
│   ├── storage.py       # Settings and state persistence
│   ├── watchers.py      # Live score monitoring and notifications
│   └── http.py          # HTTP session and request helpers
├── cloudflare-worker/     # Optional Cloudflare Worker for VPS deployments
│   ├── worker.js          # Worker proxy code
│   ├── wrangler.toml      # Wrangler configuration
│   ├── package.json       # Node.js dependencies for Wrangler
│   └── README.md          # Worker-specific documentation
└── README.md             # Main documentation
```

## Architecture Principles

The bot follows clean code and SOLID principles with a modular architecture:

- **Single Responsibility**: Each module handles a specific concern (API, commands, formatting, etc.)
- **Open/Closed**: Easy to extend with new features, API endpoints, or champion data sources
- **Dependency Inversion**: Configurable abstractions for APIs and data sources
- **Environment-driven**: All configuration via environment variables with smart defaults
- **Efficient Caching**: Separate caching strategies for different data types (LTA API vs Champion data)
- **Modular Design**: Clean separation between bot logic, API interactions, and data formatting

## Configuration Examples

### Local Development
```bash
# Minimal configuration - uses direct API and official champion data
BOT_TOKEN=your_token
ALLOWED_USER_ID=123456789
X_SESSION_TOKEN=your_session_token
LTA_API_URL=https://api.ltafantasy.com
CHAMPION_API_URL=https://ddragon.leagueoflegends.com/cdn/15.16.1/data/en_US/champion.json
CHAMPION_CACHE_TTL=86400
```

### VPS with Cloudflare Worker
```bash
# Uses worker proxy to bypass Cloudflare challenges
BOT_TOKEN=your_token
ALLOWED_USER_ID=123456789
X_SESSION_TOKEN=your_session_token
LTA_API_URL=https://your-proxy.workers.dev
CHAMPION_API_URL=https://ddragon.leagueoflegends.com/cdn/15.16.1/data/en_US/champion.json
CHAMPION_CACHE_TTL=86400
```

## Troubleshooting

### Common Issues

1. **"User not found" errors**
   - Your LTA Fantasy session token has expired
   - Get a new token following the instructions above

2. **Cloudflare challenges on VPS**
   - Set `LTA_API_URL` to your Cloudflare Worker URL instead of the direct API
   - Deploy the Worker using the [Cloudflare Worker setup guide](./cloudflare-worker/README.md)

3. **Bot not responding**
   - Check that `BOT_TOKEN` and `ALLOWED_USER_ID` are correct
   - Verify the bot is running: `./manage-bot.sh status`
   - Check recent logs: `./manage-bot.sh logs`

4. **Wrong API endpoint**
   - Check logs on startup - shows which endpoint is being used
   - Set `LTA_API_URL` to the correct endpoint (direct API or Worker URL)
   - Use `LOG_LEVEL=DEBUG` for detailed request logging

5. **Champion names not showing**
   - Check if `CHAMPION_API_URL` is accessible from your deployment
   - Verify champion data loading in logs: "✅ Loaded X champions from Riot Data Dragon"
   - Champion data is cached for 24 hours - restart bot if needed

### Debug Mode

Enable detailed logging and run comprehensive tests:
```bash
# Run full test suite with environment validation
./manage-bot.sh test

# Enable debug logging for detailed output
LOG_LEVEL=DEBUG ./manage-bot.sh start
```

The management script provides:
- Environment validation and dependency checking
- API connectivity testing with authentication verification  
- Comprehensive health checks before starting the bot
- Real-time log monitoring and analysis

## Security Notes

- Never commit your `.env` file to version control
- Use environment variables for all sensitive configuration
- The `ALLOWED_USER_ID` restricts bot usage to your Telegram account only
- Session tokens should be refreshed periodically

## License

This project is open source. See the repository for license details.
