# LTA Fantasy Bot - AI Agent Instructions

## Project Overview

Python-based Telegram bot monitoring LTA Fantasy League of Legends fantasy league scores with real-time notifications, state-machine-based polling, and group chat support.

## Architecture & Data Flow

**Three-tier architecture:**
1. **Telegram layer** ([app.py](../ltabot/app.py)) - Bot initialization, command handlers, lifecycle management
2. **Core logic** ([watchers.py](../ltabot/watchers.py)) - State machine with three phases (PRE_MARKET, MARKET_OPEN, LIVE), adaptive polling with backoff
3. **External APIs** - LTA Fantasy API (direct or via Cloudflare Worker proxy), Champion Data Dragon API

**State machine phases** (WatcherPhase enum in [state.py](../ltabot/state.py)):
- `PRE_MARKET`: No active round, checks for market open every POLL_SECS
- `MARKET_OPEN`: Round active but not live, monitors for roster locks + sends reminders (1h, 24h before close)
- `LIVE`: Round in progress, polls for score changes with smart backoff when stale

**Persistent state files:**
- `group_settings.json`: League slugs attached to Telegram groups
- `runtime_state.json`: Last scores, rankings, watcher phases, reminder schedules, message IDs for resuming after restart

## Critical Patterns

### 1. Session Management & Caching
- All API calls use shared `aiohttp.ClientSession` via `make_session()` context manager ([http.py](../ltabot/http.py))
- API responses cached with `@cached_api_call` decorator using TTL cache (5min default) - invalidate via `CACHE.clear()`
- Champion data cached separately with configurable TTL (24h default)

### 2. Watcher Lifecycle
Start: `start_watcher(chat_id, league, bot)` in [watchers.py](../ltabot/watchers.py) creates asyncio task
Stop: Cancel task via `WATCHERS[chat_id].cancel()`, cleanup state in `WATCHER_PHASES`, `SCHEDULED_TASKS`
Resume: `resume_watchers()` in [app.py](../ltabot/app.py) called on bot startup, reads `runtime_state.json` to restart active watchers

### 3. Command Routing Pattern
- Private chat commands require league slug arg: `/scores <league_slug>`
- Group commands use attached league from `group_settings.json`: `/scores` (no arg)
- Admin-only commands (`/setleague`, `/startwatch`, `/stopwatch`) use `@guard_admin` decorator ([auth.py](../ltabot/auth.py))
- Read commands (`/scores`, `/team`) use `@guard_read` (checks `ALLOWED_USER_ID` for private chats)

### 4. Dual Ranking System
- **Split score**: Cumulative points across all rounds in current split (from `/leagues/{slug}/ranking?roundId=X&orderBy=split_score`)
- **Round score**: Points for current round only (calculated via `calculate_partial_ranking()` in [watchers.py](../ltabot/watchers.py))
- Chart generation ([charts.py](../ltabot/charts.py)) uses round-level stats from `/user-teams/{id}/round-stats` endpoint

## Development Workflows

### Running the Bot
```bash
# Production (background daemon)
./manage-bot.sh start
./manage-bot.sh stop
./manage-bot.sh status
./manage-bot.sh logs

# Development (foreground with logs)
source .venv/bin/activate
python bot.py
```

### Testing
```bash
# Full test suite (requires valid .env with tokens)
./manage-bot.sh test

# Individual test in Python shell
source .venv/bin/activate
python -c "from ltabot.api import get_rounds; import asyncio; print(asyncio.run(get_rounds(...)))"
```

### Debugging State Issues
- Check `runtime_state.json` for watcher phases, last scores, reminder schedules
- Use `LOG_LEVEL=DEBUG` in `.env` to see API calls, phase transitions, cache hits
- Watcher not resuming? Verify `get_active_chats_to_resume()` returns expected chat IDs

## Configuration Gotchas

**API endpoint selection** (`LTA_API_URL` in [config.py](../ltabot/config.py)):
- Local dev: `https://api.ltafantasy.com` (default)
- VPS with Cloudflare challenges: Deploy [cloudflare-worker/](../cloudflare-worker/) first, then use worker URL

**Session token expiry**: LTA Fantasy tokens expire periodically. Users update via `/auth <new_token>` command which updates `X_SESSION_TOKEN` at runtime (not persisted to `.env`).

**Polling behavior**: Adaptive backoff kicks in after `MAX_STALE_POLLS` consecutive unchanged polls, multiplying interval by `BACKOFF_MULTIPLIER` up to `MAX_POLL_SECS` (default: 12 polls → 2x → max 900s).

## Integration Points

**External APIs:**
1. LTA Fantasy API: All endpoints in [api.py](../ltabot/api.py) require `x-session-token` header (set in [http.py](../ltabot/http.py))
2. Champion Data Dragon: Fetched once per bot session, cached in `CHAMPION_DATA` dict ([champions.py](../ltabot/champions.py))
3. Telegram Bot API: Managed by python-telegram-bot library, configured in [app.py](../ltabot/app.py)

**Cloudflare Worker proxy** ([cloudflare-worker/](../cloudflare-worker/)):
- Deployed separately via `npm run deploy` (uses Wrangler CLI)
- Forwards `x-session-token`, adds Bruno runtime headers to bypass Cloudflare challenges
- Only proxies whitelisted paths: `/leagues/`, `/rosters/per-round/`, `/users/me`

## Code Conventions

- **Type hints**: All functions use type annotations (imported from `__future__` for Python 3.8 compat)
- **Async everywhere**: All I/O operations (API, file, database) use async/await
- **HTML escaping**: Telegram messages use HTML parse mode; escape user input via `_escape_html()` in [formatting.py](../ltabot/formatting.py)
- **Logging emojis**: Status messages use emojis (✅ success, ❌ error, ⚠️ warning, 🔄 in-progress) for terminal/log readability

## Testing with Wiremock

The [wiremock/](../wiremock/) directory contains mock API responses for testing without live API:
```bash
cd wiremock && docker-compose up -d
# Set LTA_API_URL=http://localhost:8080 in .env
# Modify mappings/*.json to test specific round states (pre-market, live, completed)
```

Mock files organized by scenario: `rounds-live.json`, `rounds-market-open-1h.json`, `ranking-round5.json`, etc.
