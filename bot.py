import asyncio
import os
import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import aiohttp
from telegram import Update, ChatMember, BotCommand, BotCommandScopeAllPrivateChats
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Load environment variables from .env file if it exists
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_env()

# Set up logging with configurable level
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, log_level, logging.INFO)
)
logger = logging.getLogger(__name__)

# Reduce telegram library verbosity to avoid getUpdates spam
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING) 
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
logging.getLogger("telegram.bot").setLevel(logging.WARNING)

# ====== Configuration ======
class Config:
    """Application configuration with smart API endpoint selection."""
    
    # Telegram Bot Configuration
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
    
    # LTA Fantasy API Configuration
    X_SESSION_TOKEN = os.getenv("X_SESSION_TOKEN", "").strip()
    POLL_SECS = int(os.getenv("POLL_SECS", "30"))
    
    # API Endpoint Configuration
    LTA_API_URL = os.getenv("LTA_API_URL", "https://api.ltafantasy.com").strip()
    
    @classmethod
    def validate_config(cls) -> None:
        """Validate required configuration is present."""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN environment variable is required")
        if cls.ALLOWED_USER_ID == 0:
            raise ValueError("ALLOWED_USER_ID environment variable is required")
        if not cls.X_SESSION_TOKEN:
            logger.warning("X_SESSION_TOKEN not configured - bot may not work until token is provided via /auth")
    
    @classmethod
    def get_api_base_url(cls) -> str:
        """
        Get the API base URL.
        Uses LTA_API_URL which can be set to either:
        - https://api.ltafantasy.com (direct API)  
        - https://your-worker.workers.dev (Cloudflare Worker proxy)
        """
        logger.info(f"Using API endpoint: {cls.LTA_API_URL}")
        return cls.LTA_API_URL

# Initialize and validate configuration
config = Config()
config.validate_config()
BASE = config.get_api_base_url()

# Legacy variables for backward compatibility
BOT_TOKEN = config.BOT_TOKEN
ALLOWED_USER_ID = config.ALLOWED_USER_ID
X_SESSION_TOKEN = config.X_SESSION_TOKEN
POLL_SECS = config.POLL_SECS

# runtime state
WATCHERS: Dict[int, asyncio.Task] = {}
LAST_SENT_HASH: Dict[int, str] = {}
WATCH_MESSAGE_IDS: Dict[int, int] = {}  # chat_id -> message_id for editing
LAST_SCORES: Dict[int, Dict[str, float]] = {}  # chat_id -> {team_name: round_score}
LAST_RANKINGS: Dict[int, List[str]] = {}  # chat_id -> [team_names in round rank order]
LAST_SPLIT_RANKINGS: Dict[int, List[str]] = {}  # chat_id -> [team_names in split rank order]
CURRENT_TOKEN: Dict[str, str] = {"x_session_token": X_SESSION_TOKEN}  # mutable store
FIRST_POLL_AFTER_RESUME: Dict[int, bool] = {}  # chat_id -> True if this is first poll after resume

# persistent storage
GROUP_SETTINGS_FILE = "group_settings.json"
GROUP_SETTINGS: Dict[str, Dict[str, Any]] = {}
RUNTIME_STATE_FILE = "runtime_state.json"


# ====== Persistent Storage ======
def load_group_settings():
    """Load group settings from JSON file"""
    global GROUP_SETTINGS
    try:
        if os.path.exists(GROUP_SETTINGS_FILE):
            with open(GROUP_SETTINGS_FILE, 'r') as f:
                GROUP_SETTINGS = json.load(f)
            logger.info(f"Loaded settings for {len(GROUP_SETTINGS)} groups")
        else:
            logger.info("No existing group settings file found")
    except Exception as e:
        logger.error(f"Could not load group settings: {e}")
        GROUP_SETTINGS = {}

def save_group_settings():
    """Save group settings to JSON file"""
    try:
        with open(GROUP_SETTINGS_FILE, 'w') as f:
            json.dump(GROUP_SETTINGS, f, indent=2)
        logger.debug("Group settings saved to file")
    except Exception as e:
        logger.error(f"Could not save group settings: {e}")

def load_runtime_state():
    """Load runtime state from JSON file for seamless restarts"""
    global LAST_SCORES, LAST_RANKINGS, LAST_SPLIT_RANKINGS, WATCH_MESSAGE_IDS
    try:
        if os.path.exists(RUNTIME_STATE_FILE):
            with open(RUNTIME_STATE_FILE, 'r') as f:
                state = json.load(f)
            
            # Convert string keys back to int for chat_ids
            LAST_SCORES = {int(k): v for k, v in state.get("last_scores", {}).items()}
            LAST_RANKINGS = {int(k): v for k, v in state.get("last_rankings", {}).items()}
            LAST_SPLIT_RANKINGS = {int(k): v for k, v in state.get("last_split_rankings", {}).items()}
            WATCH_MESSAGE_IDS = {int(k): v for k, v in state.get("watch_message_ids", {}).items()}
            
            logger.info(f"Loaded runtime state for {len(LAST_SCORES)} chats")
        else:
            logger.info("No existing runtime state file found")
    except Exception as e:
        logger.error(f"Could not load runtime state: {e}")
        # Initialize empty dictionaries on error
        LAST_SCORES = {}
        LAST_RANKINGS = {}
        LAST_SPLIT_RANKINGS = {}
        WATCH_MESSAGE_IDS = {}

def save_runtime_state():
    """Save runtime state to JSON file for seamless restarts"""
    try:
        # Get list of actively watched chats
        active_chats = list(WATCHERS.keys())
        
        state = {
            "active_chats": active_chats,
            "last_scores": {str(k): v for k, v in LAST_SCORES.items()},
            "last_rankings": {str(k): v for k, v in LAST_RANKINGS.items()},
            "last_split_rankings": {str(k): v for k, v in LAST_SPLIT_RANKINGS.items()},
            "watch_message_ids": {str(k): v for k, v in WATCH_MESSAGE_IDS.items()},
            "last_updated": datetime.now().isoformat()
        }
        
        with open(RUNTIME_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.debug(f"Runtime state saved for {len(active_chats)} active chats")
    except Exception as e:
        logger.error(f"Could not save runtime state: {e}")

def get_active_chats_to_resume() -> List[int]:
    """Get list of chats that were actively being watched before restart"""
    try:
        if os.path.exists(RUNTIME_STATE_FILE):
            with open(RUNTIME_STATE_FILE, 'r') as f:
                state = json.load(f)
            return [int(chat_id) for chat_id in state.get("active_chats", [])]
    except Exception as e:
        logger.error(f"Could not load active chats list: {e}")
    return []

def get_group_league(chat_id: int) -> Optional[str]:
    """Get the league attached to a group"""
    return GROUP_SETTINGS.get(str(chat_id), {}).get("league")

def set_group_league(chat_id: int, league_slug: str):
    """Set the league for a group"""
    chat_key = str(chat_id)
    if chat_key not in GROUP_SETTINGS:
        GROUP_SETTINGS[chat_key] = {}
    GROUP_SETTINGS[chat_key]["league"] = league_slug
    save_group_settings()
    logger.info(f"Group {chat_id} attached to league '{league_slug}'")


# ====== Access control ======
async def is_group_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is a member of the group (for read-only commands)"""
    if not update.effective_chat or not update.effective_user:
        return False
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False

async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is admin in the group"""
    if not update.effective_chat or not update.effective_user:
        return False
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False

async def is_authorized_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is authorized for admin commands (write operations)"""
    if not update.effective_user or not update.effective_chat:
        return False
    
    user_id = update.effective_user.id
    chat = update.effective_chat
    
    # Private chat: check if it's the allowed user
    if chat.type == "private":
        return user_id == ALLOWED_USER_ID
    
    # Group chat: check if user is admin
    if chat.type in ["group", "supergroup"]:
        return await is_group_admin(update, context)
    
    return False

async def is_authorized_read(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is authorized for read-only commands"""
    if not update.effective_user or not update.effective_chat:
        return False
    
    user_id = update.effective_user.id
    chat = update.effective_chat
    
    # Private chat: check if it's the allowed user
    if chat.type == "private":
        return user_id == ALLOWED_USER_ID
    
    # Group chat: any member can use read-only commands
    if chat.type in ["group", "supergroup"]:
        return await is_group_member(update, context)
    
    return False

async def guard_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Guard function for admin commands"""
    if not await is_authorized_admin(update, context):
        if update.effective_chat and update.effective_chat.type == "private":
            await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")
        # Don't respond in groups to avoid spam
        return False
    return True

async def guard_read(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Guard function for read-only commands"""
    if not await is_authorized_read(update, context):
        if update.effective_chat and update.effective_chat.type == "private":
            await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")
        # Don't respond in groups to avoid spam
        return False
    return True


# ====== HTTP helpers ======
def build_headers() -> Dict[str, str]:
    token = CURRENT_TOKEN.get("x_session_token") or ""
    h = {
        "accept": "*/*",
        "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "user-agent": "bruno-runtime/2.9.0",  # Key: Bruno's UA bypasses Cloudflare
        "origin": "https://ltafantasy.com",
        "referer": "https://ltafantasy.com/",
        "pragma": "no-cache",
        "cache-control": "no-cache",
        "dnt": "1",
    }
    if token:
        h["x-session-token"] = token
    return h

def make_session() -> aiohttp.ClientSession:
    timeout = aiohttp.ClientTimeout(total=25)
    # Use environment proxies if provided (HTTPS_PROXY/HTTP_PROXY)
    return aiohttp.ClientSession(
        timeout=timeout,
        headers=build_headers(),
        trust_env=True,
    )

async def fetch_json(session: aiohttp.ClientSession, url: str, params: Dict[str, str] | None = None) -> Any:
    logger.debug(f"API request: {url}")
    async with session.get(url, params=params) as r:
        if r.status in (401, 403):
            txt = await r.text()
            error_msg = f"Auth failed ({r.status}). Update token with /auth <token>. Body: {txt[:180]}"
            logger.warning(f"API auth failure for {url}: {r.status}")
            raise PermissionError(error_msg)
        if r.status != 200:
            txt = await r.text()
            error_msg = f"HTTP {r.status} for {url} :: {txt[:300]}"
            logger.error(f"API error for {url}: {r.status}")
            raise RuntimeError(error_msg)
        logger.debug(f"API success: {url}")
        return await r.json()


# ====== LTA API ======
async def get_rounds(session: aiohttp.ClientSession, league_slug: str) -> List[Dict[str, Any]]:
    data = await fetch_json(session, f"{BASE}/leagues/{league_slug}/rounds")
    return data.get("data", [])

def pick_current_round(rounds: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick current in-progress round only (strict mode for watching)"""
    inprog = [r for r in rounds if r.get("status") == "in_progress"]
    if inprog:
        inprog.sort(key=lambda r: r.get("indexInSplit", -1), reverse=True)
        return inprog[0]
    return None

def pick_latest_round(rounds: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick current round with fallback to latest completed (for one-time queries)"""
    inprog = [r for r in rounds if r.get("status") == "in_progress"]
    if inprog:
        inprog.sort(key=lambda r: r.get("indexInSplit", -1), reverse=True)
        return inprog[0]
    # fallback: latest by marketClosesAt
    def ts(r):
        s = r.get("marketClosesAt") or ""
        try:
            from datetime import datetime
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0
    return sorted(rounds, key=ts, reverse=True)[0] if rounds else None

async def get_league_ranking(session: aiohttp.ClientSession, league_slug: str, round_id: str) -> List[Dict[str, Any]]:
    data = await fetch_json(session, f"{BASE}/leagues/{league_slug}/ranking", params={"roundId": round_id, "orderBy": "split_score"})
    return data.get("data", [])

async def get_team_round_roster(session: aiohttp.ClientSession, round_id: str, team_id: str) -> Dict[str, Any]:
    data = await fetch_json(session, f"{BASE}/rosters/per-round/{round_id}/{team_id}")
    return data.get("data", {})

async def find_team_by_name_or_owner(session: aiohttp.ClientSession, league_slug: str, search_term: str, search_type: str) -> Optional[Dict[str, Any]]:
    """Find a team by name or owner name. Returns team info with ranking data."""
    rounds = await get_rounds(session, league_slug)
    if not rounds:
        return None
    
    round_obj = pick_latest_round(rounds)  # Use latest for searches
    if not round_obj:
        return None
    
    round_id = round_obj["id"]
    ranking = await get_league_ranking(session, league_slug, round_id)
    
    search_term_lower = search_term.lower()
    
    for item in ranking:
        team_name = item["userTeam"]["name"].lower()
        owner_name = (item["userTeam"].get("ownerName") or "").lower()
        
        if search_type == "team" and search_term_lower in team_name:
            return {
                "team_info": item,
                "round_obj": round_obj,
                "round_id": round_id
            }
        elif search_type == "owner" and search_term_lower in owner_name:
            return {
                "team_info": item,
                "round_obj": round_obj,
                "round_id": round_id
            }
    
    return None


# ====== Formatting ======
def fmt_standings(league_slug: str, round_obj: Dict[str, Any], rows: List[Tuple[int, str, str, float]], 
                 score_changes: Dict[str, str] = None, include_timestamp: bool = False, score_type: str = "Round") -> str:
    # HTML escape function for text content
    def escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    title = f"🏆 <b>{escape_html(league_slug)}</b>\n🧭 <b>{escape_html(round_obj.get('name', ''))}</b> ({escape_html(round_obj.get('status', ''))})\n📊 <i>{score_type} Scores</i>"
    
    def medal(n: int) -> str:
        if n == 1:
            return "🥇"
        if n == 2:
            return "🥈"
        if n == 3:
            return "🥉"
        return f"{n:>2}."
    
    lines = []
    for r, t, o, p in rows:
        arrow = score_changes.get(t, "") if score_changes else ""
        safe_team = escape_html(t)
        safe_owner = escape_html(o)
        lines.append(f"{medal(r)} <b>{safe_team}</b> — {safe_owner} · <code>{p:.2f}</code> {arrow}")
    
    message = f"{title}\n\n" + ("\n".join(lines) if lines else "<i>No teams</i>")
    
    if include_timestamp:
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message += f"\n\n🕒 <i>Updated at {current_time}</i>"
    
    return message

def format_score_details(details: List[Dict[str, Any]]) -> str:
    """Format game scoring details into readable text"""
    lines = []
    
    detail_names = {
        "kills": "K", "asssits": "A", "deaths": "D",
        "cs": "CS", "gold_advantage_at_14": "Gold@14",
        "kp_70": "KP>70%", "damage_share_30": "DMG>30%",
        "victory": "Victory", "underdog_victory": "Underdog Win",
        "stomp": "Stomp", "perfect_scores": "Perfect Game",
        "triple_kills": "Triple Kill", "over_ten_kills": "10+ Kills",
        "jng_barons": "Baron", "jng_dragon_soul": "Dragon Soul",
        "jng_kp_over_75": "KP>75%", "sup_kp_over_75": "KP>75%",
        "sup_vision_score": "Vision", "top_damage_share": "DMG Share",
        "top_tank": "Tank", "top_solo_kills": "Solo Kill"
    }
    
    for detail in details:
        detail_type = detail.get("detailType", "")
        count = detail.get("count", 0)
        value = detail.get("value", 0)
        display_mode = detail.get("displayMode", "")
        
        name = detail_names.get(detail_type, detail_type)
        
        if display_mode == "percent":
            lines.append(f"• {name}: {count:.0%} (+{value})")
        elif display_mode == "single":
            if value > 0:
                lines.append(f"• {name} (+{value})")
        else:
            if detail_type in ["kills", "asssits", "deaths"]:
                lines.append(f"• {name}: {count} ({value:+})")
            else:
                lines.append(f"• {name}: {count} (+{value})")
    
    return "\n".join(lines)

def fmt_team_details(team_info: Dict[str, Any], round_obj: Dict[str, Any], roster_data: Dict[str, Any]) -> str:
    """Format detailed team information with roster and game details"""
    def escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # Team header
    team_name = escape_html(team_info["userTeam"]["name"])
    owner_name = escape_html(team_info["userTeam"].get("ownerName", "Unknown"))
    rank = team_info.get("rank", "?")
    
    # Round roster info
    round_roster = roster_data.get("roundRoster", {})
    points_partial = round_roster.get("pointsPartial", 0) or 0
    pre_budget = round_roster.get("preRoundBudget", 0)
    
    # Medal emoji based on rank
    def get_rank_medal(r):
        if r == 1: return "🥇"
        elif r == 2: return "🥈" 
        elif r == 3: return "🥉"
        else: return f"#{r}"
    
    rank_display = get_rank_medal(rank)
    
    message = f"🏆 <b>{team_name}</b>\n"
    message += f"👤 <b>{owner_name}</b> • {rank_display}\n"
    message += f"📊 <b>{points_partial:.2f}</b> pontos • 💰 {pre_budget:.1f}M budget\n\n"
    message += f"🧭 <b>{escape_html(round_obj.get('name', ''))}</b> ({escape_html(round_obj.get('status', ''))})\n\n"
    
    # Roster players
    roster_players = roster_data.get("rosterPlayers", [])
    if not roster_players:
        message += "<i>No roster data available</i>"
        return message
    
    role_emojis = {
        "top": "⚔️", "jungle": "🌿", "mid": "🔮", 
        "bottom": "🏹", "support": "🛡️"
    }
    
    # Sort players by role order: top, jungle, mid, bottom, support
    role_order = ["top", "jungle", "mid", "bottom", "support"]
    roster_players.sort(key=lambda p: role_order.index(p.get("role", "support")) if p.get("role") in role_order else 999)
    
    for player in roster_players:
        message += format_player_section(player, role_emojis)
    
    return message.strip()

def format_player_section(player: Dict[str, Any], role_emojis: Dict[str, str]) -> str:
    """Format individual player section"""
    def escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    role = player.get("role", "")
    role_emoji = role_emojis.get(role, "🎮")
    
    esports_player = player.get("roundEsportsPlayer", {})
    pro_player = esports_player.get("proPlayer", {})
    
    player_name = escape_html(pro_player.get("name", "Unknown"))
    team_name_short = escape_html(pro_player.get("team", {}).get("name", ""))
    price = esports_player.get("preRoundPrice", 0)
    player_points = player.get("pointsPartial") or 0
    
    section = f"{role_emoji} <b>{player_name}</b> ({team_name_short})\n"
    section += f"💰 {price}M • 📊 <b>{player_points:.2f}</b> pts\n"
    
    # Games details in expandable blockquote
    games = player.get("games", [])
    if games:
        games_text = format_games_details(games)
        if games_text:
            section += f"<blockquote expandable>{games_text.strip()}</blockquote>\n"
    else:
        section += "<i>No games played yet</i>\n"
    
    section += "\n"
    return section

def format_games_details(games: List[Dict[str, Any]]) -> str:
    """Format games details for a player"""
    def escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    games_text = ""
    for i, game in enumerate(games, 1):
        opponent = game.get("opponentTeam", {})
        opponent_name = escape_html(opponent.get("name", "Unknown"))
        game_points = game.get("points", 0)
        multiplier = game.get("multiplier", 1)
        
        multiplier_text = f" (x{multiplier})" if multiplier != 1 else ""
        games_text += f"<b>Game {i}</b> vs {opponent_name}: <b>{game_points:.2f}</b>{multiplier_text}\n"
        
        details = game.get("details", [])
        if details:
            games_text += format_score_details(details) + "\n"
        games_text += "\n"
    
    return games_text

def hash_payload(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ====== Core aggregation ======
async def gather_live_scores(league_slug: str) -> Tuple[str, Dict[str, Any]]:
    logger.debug(f"Gathering split scores for league: {league_slug}")
    async with make_session() as session:
        rounds = await get_rounds(session, league_slug)
        if not rounds:
            logger.warning(f"No rounds found for league: {league_slug}")
            raise RuntimeError("No rounds. Check league slug or token.")
        round_obj = pick_latest_round(rounds)  # Use latest for one-time queries
        if not round_obj:
            logger.warning(f"No current round found for league: {league_slug}")
            raise RuntimeError("Could not select a round.")
        round_id = round_obj["id"]
        logger.debug(f"Using round: {round_obj.get('name', round_id)} ({round_obj.get('status')})")
        ranking = await get_league_ranking(session, league_slug, round_id)

        rows: List[Tuple[int, str, str, float]] = []
        if ranking:
            for item in ranking:
                rank = item.get("rank", 0)
                team = item["userTeam"]["name"]
                owner = item["userTeam"].get("ownerName") or "—"
                # Use split score directly from ranking API
                split_score = item.get("score", 0.0)
                rows.append((rank, team, owner, float(split_score)))
            # Sort by split score descending, then by rank ascending
            rows.sort(key=lambda r: (-r[3], r[0]))
        
        msg = fmt_standings(league_slug, round_obj, rows, score_type="Split")
        logger.info(f"Generated split standings for {league_slug}: {len(rows)} teams")
        return msg, round_obj


# ====== Commands ======
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_read(update, context): return
    
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"Start command from user {user.id} in chat {chat.id} ({chat.type})")
    
    if chat.type == "private":
        await update.message.reply_text(
            "🤖 <b>LTA Fantasy Bot</b>\n\n"
            "<b>Private Chat Commands:</b>\n"
            "/scores &lt;league_slug&gt; - Get current standings\n"
            "/team &lt;league_slug&gt; &lt;team_name&gt; - Get detailed team info\n"
            "/owner &lt;league_slug&gt; &lt;owner_name&gt; - Find team by owner\n"
            "/watch &lt;league_slug&gt; - Start monitoring league\n"
            "/unwatch - Stop monitoring\n"
            "/auth &lt;token&gt; - Update session token\n\n"
            "<b>Group Commands (for admins):</b>\n"
            "/setleague &lt;league_slug&gt; - Attach league to this group\n"
            "/getleague - Show current league\n"
            "/startwatch - Start monitoring group's league\n"
            "/stopwatch - Stop monitoring",
            parse_mode="HTML"
        )
    else:
        league = get_group_league(chat.id)
        status = f"📊 Current league: <code>{league}</code>" if league else "❓ No league attached"
        await update.message.reply_text(
            f"🤖 <b>LTA Fantasy Bot</b> (Group Mode)\n\n"
            f"{status}\n\n"
            "<b>Commands for All Members:</b>\n"
            "/scores - Show current standings\n"
            "/team &lt;name&gt; - Get detailed team info\n"
            "/owner &lt;name&gt; - Find team by owner name\n"
            "/getleague - Show current league\n\n"
            "<b>Admin Only Commands:</b>\n"
            "/setleague &lt;slug&gt; - Attach league to group\n"
            "/startwatch - Start live monitoring\n"
            "/stopwatch - Stop monitoring",
            parse_mode="HTML"
        )

async def scores_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_read(update, context): return
    
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"Scores command from user {user.id} in chat {chat.id}")
    
    # In private chat, require league_slug argument
    if chat.type == "private":
        if not context.args:
            await update.message.reply_text("Usage: /scores <league_slug>")
            return
        league = context.args[0].strip()
    else:
        # In groups, use attached league
        league = get_group_league(chat.id)
        if not league:
            await update.message.reply_text("❌ No league attached to this group. Use <code>/setleague &lt;league_slug&gt;</code> first.", parse_mode="HTML")
            return
    
    try:
        msg, _ = await gather_live_scores(league)
        await update.message.reply_text(msg, parse_mode="HTML")
    except PermissionError as e:
        await update.message.reply_text(f"🔐 {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def setleague_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context): return
    
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text("❌ This command only works in groups.")
        return
    
    logger.info(f"Setleague command from user {user.id} in group {chat.id}")
    
    if not context.args:
        await update.message.reply_text("Usage: /setleague <league_slug>")
        return
    
    league_slug = context.args[0].strip()
    
    # Test if the league exists
    try:
        async with make_session() as session:
            rounds = await get_rounds(session, league_slug)
            if not rounds:
                await update.message.reply_text(f"❌ League <code>{league_slug}</code> not found or empty.")
                return
    except Exception as e:
        await update.message.reply_text(f"❌ Could not access league <code>{league_slug}</code>: {e}")
        return
    
    set_group_league(chat.id, league_slug)
    await update.message.reply_text(f"✅ League set to <code>{league_slug}</code> for this group!", parse_mode="HTML")

async def getleague_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_read(update, context): return
    
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text("❌ This command only works in groups.")
        return
    
    league = get_group_league(chat.id)
    if league:
        await update.message.reply_text(f"📊 Current league: <code>{league}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("❓ No league attached to this group. Use <code>/setleague &lt;league_slug&gt;</code> to set one.", parse_mode="HTML")

async def watch_loop(chat_id: int, league: str, bot, stop_event: asyncio.Event):
    logger.info(f"Started watch loop for chat {chat_id}, league '{league}'")
    poll_count = 0
    save_counter = 0  # Save state every 3 polls to keep persistence up-to-date
    
    # Mark this chat as having resumed (if it was resumed)
    is_resumed = FIRST_POLL_AFTER_RESUME.get(chat_id, False)
    
    while not stop_event.is_set():
        try:
            poll_count += 1
            save_counter += 1
            logger.debug(f"Poll #{poll_count} for chat {chat_id}")
            
            # Get structured data for round score tracking
            current_scores, current_ranking, teams_data, current_round = await get_structured_scores(league)
            
            # Check if round completed (no active round found)
            if current_round is None:
                # No rounds found at all - error state
                logger.error(f"No rounds found for league '{league}' (chat {chat_id}) - stopping watch")
                await bot.send_message(
                    chat_id, 
                    f"❌ <b>Error:</b> No rounds found for league <code>{league}</code>.\nStopped watching.",
                    parse_mode="HTML"
                )
                break
            elif not teams_data:
                # Round exists but it's not in_progress - check if it completed
                round_status = current_round.get('status', 'unknown')
                round_name = current_round.get('name', 'Unknown Round')
                
                if round_status == 'completed':
                    logger.info(f"Round completed for chat {chat_id}, league '{league}' - round: {round_name}")
                    
                    # Delete the current watching message if it exists
                    if chat_id in WATCH_MESSAGE_IDS:
                        try:
                            await bot.delete_message(chat_id=chat_id, message_id=WATCH_MESSAGE_IDS[chat_id])
                            logger.debug(f"Deleted watching message {WATCH_MESSAGE_IDS[chat_id]} for chat {chat_id}")
                        except Exception as e:
                            logger.warning(f"Could not delete watching message for chat {chat_id}: {e}")
                    
                    # Get final scores using the latest completed round
                    try:
                        final_msg, _ = await gather_live_scores(league)
                        final_msg += "\n\n🏁 <b>ROUND COMPLETED!</b>\n<i>Final scores above. Stopped watching.</i>"
                        await bot.send_message(chat_id, final_msg, parse_mode="HTML")
                        logger.info(f"Sent final scores for completed round to chat {chat_id}")
                    except Exception as e:
                        await bot.send_message(
                            chat_id, 
                            f"🏁 <b>Round completed!</b> Stopped watching.\n❌ Could not fetch final scores: {e}",
                            parse_mode="HTML"
                        )
                        logger.error(f"Could not fetch final scores for chat {chat_id}: {e}")
                    
                    # Stop the watch loop - cleanup will happen in finally block
                    break
                else:
                    # Unknown state - not in_progress and not completed
                    logger.error(f"Unknown round state for chat {chat_id}, league '{league}' - round: {round_name}, status: {round_status}")
                    await bot.send_message(
                        chat_id, 
                        f"❌ <b>Unknown round state:</b> <code>{round_name}</code> status is <code>{round_status}</code> (not in_progress).\nStopped watching.",
                        parse_mode="HTML"
                    )
                    break
            
            if not teams_data:
                logger.warning(f"No teams data for league: {league}")
                await asyncio.sleep(POLL_SECS)
                continue

            # Get split ranking for change detection
            round_id = current_round["id"]
            current_split_ranking, split_teams_data = await get_structured_split_ranking(league, round_id)
            
            # Calculate score changes for round scores (but not on first poll after resume to avoid false arrows)
            score_changes = calculate_score_changes(chat_id, current_scores) if not is_resumed else {}
            
            # Check if split ranking changed (will return False on first poll after resume)
            split_ranking_changed = check_split_ranking_changed(chat_id, current_split_ranking)
            
            # Build message with round scores, changes and timestamp
            message = fmt_standings(league, current_round, teams_data, score_changes, include_timestamp=True, score_type="Round")
            
            # Handle split ranking change notification (only if not first poll after resume)
            if split_ranking_changed and chat_id in LAST_SPLIT_RANKINGS and not is_resumed:
                await send_split_ranking_change_notification(bot, chat_id, league, current_round, split_teams_data)
            
            # Send or edit the main message - always try to edit first for seamless experience
            await send_or_edit_message(bot, chat_id, message, split_ranking_changed and not is_resumed, poll_count)
            
            # Update tracking data (both round and split rankings)
            update_tracking_data(chat_id, current_scores, current_ranking, current_split_ranking, message)
            
            # Save runtime state more frequently and when important changes happen
            should_save = (
                save_counter >= 3 or  # Every 3 polls (90 seconds)
                split_ranking_changed or    # When split ranking changes
                any(arrow != "" for arrow in score_changes.values())  # When any score changes
            )
            
            if should_save:
                save_reason = []
                if save_counter >= 3: save_reason.append("interval")
                if split_ranking_changed and not is_resumed: save_reason.append("split_ranking_changed") 
                if any(arrow != "" for arrow in score_changes.values()): save_reason.append("score_changes")
                
                save_runtime_state()
                save_counter = 0
                logger.debug(f"Saved runtime state for chat {chat_id}: {', '.join(save_reason) if save_reason else 'unknown'}")
            
            # Clear the first poll flag after the first successful poll
            if is_resumed:
                FIRST_POLL_AFTER_RESUME[chat_id] = False
                is_resumed = False
                logger.debug(f"Cleared first poll flag for chat {chat_id}")
                
        except PermissionError as e:
            logger.error(f"Auth error for chat {chat_id}: {e}")
            await bot.send_message(chat_id, f"🔐 {e}")
            break
        except Exception as e:
            logger.error(f"Watch error for chat {chat_id}: {e}")
            await bot.send_message(chat_id, f"❌ Watch error: {e}")
        
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_SECS)
        except asyncio.TimeoutError:
            pass
    
    # Save state when loop stops and clean up tracking data
    cleanup_chat_data(chat_id)
    # Remove from watchers dict if still present
    WATCHERS.pop(chat_id, None)
    save_runtime_state()  # Force save immediately after cleanup
    logger.info(f"Watch loop stopped for chat {chat_id}")

async def get_split_ranking(session: aiohttp.ClientSession, league_slug: str, round_id: str) -> List[Tuple[int, str, str, float]]:
    """Get split ranking with split scores directly from the API."""
    ranking = await get_league_ranking(session, league_slug, round_id)
    
    rows = []
    for item in ranking:
        rank = item.get("rank", 0)
        team = item["userTeam"]["name"]
        owner = item["userTeam"].get("ownerName") or "—"
        split_score = item.get("score", 0.0)
        rows.append((rank, team, owner, float(split_score)))
    
    # Sort by split score descending, then by rank ascending
    rows.sort(key=lambda r: (-r[3], r[0]))
    return rows

async def get_round_scores(session: aiohttp.ClientSession, league_slug: str, round_id: str) -> List[Tuple[int, str, str, float]]:
    """Get current round scores from individual team rosters."""
    ranking = await get_league_ranking(session, league_slug, round_id)
    
    async def get_team_round_score(item: Dict[str, Any]) -> Tuple[int, str, str, float]:
        rank = item.get("rank", 0)
        team = item["userTeam"]["name"]
        owner = item["userTeam"].get("ownerName") or "—"
        team_id = item["userTeam"]["id"]
        roster = await get_team_round_roster(session, round_id, team_id)
        rr = (roster.get("roundRoster") or {})
        pts = rr.get("pointsPartial")
        if pts is None:
            pts = rr.get("points") or 0.0
        return (rank, team, owner, float(pts))

    rows = []
    if ranking:
        rows = await asyncio.gather(*[get_team_round_score(it) for it in ranking])
        rows.sort(key=lambda r: (-r[3], r[0]))
    
    return rows

async def get_structured_scores(league: str):
    """Get structured round score data for live tracking. Returns None for current_round if no active round."""
    async with make_session() as session:
        rounds = await get_rounds(session, league)
        if not rounds:
            return {}, [], [], None
            
        current_round = pick_current_round(rounds)  # Strict: only in_progress
        if not current_round:
            # No active round - this means the round we were watching completed
            # Return the latest round info for status checking
            latest_round = pick_latest_round(rounds)
            return {}, [], [], latest_round
            
        round_id = current_round["id"]
        
        # Get round scores for live tracking
        teams_data = await get_round_scores(session, league, round_id)
        
        if not teams_data:
            return {}, [], [], current_round
        
        current_scores = {}
        current_ranking = []
        
        for rank, team_name, owner_name, pts in teams_data:
            current_scores[team_name] = pts
            current_ranking.append(team_name)
        
        return current_scores, current_ranking, teams_data, current_round

async def get_structured_split_ranking(league: str, round_id: str):
    """Get structured split ranking data for change detection."""
    async with make_session() as session:
        teams_data = await get_split_ranking(session, league, round_id)
        
        split_ranking = [team_name for rank, team_name, owner_name, score in teams_data]
        return split_ranking, teams_data

def calculate_score_changes(chat_id: int, current_scores: Dict[str, float]) -> Dict[str, str]:
    """Calculate score change arrows for each team."""
    score_changes = {}
    
    for team_name, current_score in current_scores.items():
        if chat_id in LAST_SCORES and team_name in LAST_SCORES[chat_id]:
            previous_score = LAST_SCORES[chat_id][team_name]
            if current_score > previous_score:
                score_changes[team_name] = "⬆️"
            elif current_score < previous_score:
                score_changes[team_name] = "⬇️"
            else:
                score_changes[team_name] = ""
        else:
            score_changes[team_name] = ""
    
    return score_changes

def check_ranking_changed(chat_id: int, current_ranking: List[str]) -> bool:
    """Check if team ranking has changed, but not on first poll after resume."""
    # Don't report ranking changes on the first poll after resume
    if FIRST_POLL_AFTER_RESUME.get(chat_id, False):
        return False
    return chat_id not in LAST_RANKINGS or LAST_RANKINGS[chat_id] != current_ranking

def check_split_ranking_changed(chat_id: int, current_split_ranking: List[str]) -> bool:
    """Check if split team ranking has changed, but not on first poll after resume."""
    # Don't report ranking changes on the first poll after resume
    if FIRST_POLL_AFTER_RESUME.get(chat_id, False):
        return False
    return chat_id not in LAST_SPLIT_RANKINGS or LAST_SPLIT_RANKINGS[chat_id] != current_split_ranking

async def send_ranking_change_notification(bot, chat_id: int, league: str, current_round, teams_data):
    """Send a ranking change notification."""
    ranking_msg = "🔄 <b>RANKING CHANGED!</b>\n\n"
    ranking_msg += fmt_standings(league, current_round, teams_data)
    
    await bot.send_message(chat_id, ranking_msg, parse_mode="HTML")
    logger.info(f"Sent ranking change notification to chat {chat_id}")

async def send_split_ranking_change_notification(bot, chat_id: int, league: str, current_round, split_teams_data):
    """Send a split ranking change notification."""
    ranking_msg = "🔄 <b>SPLIT RANKING CHANGED!</b>\n\n"
    ranking_msg += fmt_standings(league, current_round, split_teams_data, score_type="Split")
    
    await bot.send_message(chat_id, ranking_msg, parse_mode="HTML")
    logger.info(f"Sent split ranking change notification to chat {chat_id}")

async def send_or_edit_message(bot, chat_id: int, message: str, force_new: bool, poll_count: int):
    """Always try to edit existing message first for seamless experience, send new only if editing fails."""
    
    # Try to edit existing message first (seamless experience)
    if chat_id in WATCH_MESSAGE_IDS and not force_new:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=WATCH_MESSAGE_IDS[chat_id],
                text=message,
                parse_mode="HTML"
            )
            logger.debug(f"Seamlessly updated scores message in chat {chat_id} (poll #{poll_count})")
            return
        except Exception as edit_error:
            logger.debug(f"Edit failed (expected after restart), sending new message: {edit_error}")
    
    # Send new message if editing failed or was forced
    try:
        sent_message = await bot.send_message(chat_id, message, parse_mode="HTML")
        WATCH_MESSAGE_IDS[chat_id] = sent_message.message_id
        action = "new" if force_new else "replacement"
        logger.info(f"Sent {action} scores message to chat {chat_id} (poll #{poll_count})")
    except Exception as send_error:
        logger.error(f"Failed to send message to chat {chat_id}: {send_error}")

def update_tracking_data(chat_id: int, current_scores: Dict[str, float], 
                        current_ranking: List[str], current_split_ranking: List[str], message: str):
    """Update all tracking dictionaries."""
    LAST_SCORES[chat_id] = current_scores.copy()
    LAST_RANKINGS[chat_id] = current_ranking.copy()
    LAST_SPLIT_RANKINGS[chat_id] = current_split_ranking.copy()
    LAST_SENT_HASH[chat_id] = hash_payload(message)

def cleanup_chat_data(chat_id: int):
    """Clean up tracking data for a chat."""
    LAST_SCORES.pop(chat_id, None)
    LAST_RANKINGS.pop(chat_id, None)
    LAST_SPLIT_RANKINGS.pop(chat_id, None)
    WATCH_MESSAGE_IDS.pop(chat_id, None)
    FIRST_POLL_AFTER_RESUME.pop(chat_id, None)

# Legacy watch command for private chats
async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context): return
    
    chat = update.effective_chat
    if chat.type != "private":
        await update.message.reply_text("❌ Use <code>/startwatch</code> in groups.", parse_mode="HTML")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /watch <league_slug>")
        return
    league = context.args[0].strip()
    chat_id = chat.id

    if chat_id in WATCHERS:
        WATCHERS[chat_id].cancel()
        del WATCHERS[chat_id]

    # Check if there's an active round to watch
    try:
        async with make_session() as session:
            rounds = await get_rounds(session, league)
            if not rounds:
                await update.message.reply_text(f"❌ No rounds found for league <code>{league}</code>.", parse_mode="HTML")
                return
            
            active_round = pick_current_round(rounds)  # Strict: only in_progress
            if not active_round:
                # No active round - show status of latest round with helpful messaging
                latest_round = pick_latest_round(rounds)
                if latest_round:
                    status = latest_round.get('status', 'unknown')
                    round_name = latest_round.get('name', 'Unknown Round')
                    market_closes_at = latest_round.get('marketClosesAt', '')
                    
                    # Get current standings for this round
                    try:
                        current_msg, _ = await gather_live_scores(league)
                        
                        # Parse market close date to provide better messaging
                        message = current_msg + f"\n\n❌ <b>No active round to watch</b>\n"
                        
                        if status == 'completed':
                            message += f"🏁 <code>{round_name}</code> has completed.\nWaiting for next round to start."
                        else:
                            message += f"📅 <code>{round_name}</code> status: <code>{status}</code>\nWaiting for next round to start."
                            
                        if market_closes_at:
                            try:
                                from datetime import datetime
                                market_date = datetime.fromisoformat(market_closes_at.replace("Z", "+00:00"))
                                current_date = datetime.now(market_date.tzinfo)
                                
                                if market_date > current_date:
                                    time_str = market_date.strftime("%Y-%m-%d %H:%M UTC")
                                    message += f"\n⏰ Next round likely starts around: {time_str}"
                            except Exception:
                                pass  # Ignore date parsing errors
                                
                        await update.message.reply_text(message, parse_mode="HTML")
                        return
                    except Exception as e:
                        await update.message.reply_text(
                            f"❌ No active round in progress for <code>{league}</code>.\n"
                            f"🏁 Latest round (<code>{round_name}</code>) status: <code>{status}</code>\n"
                            f"Error fetching scores: {e}", 
                            parse_mode="HTML"
                        )
                        return
                else:
                    await update.message.reply_text(
                        f"❌ No rounds found for league <code>{league}</code>.",
                        parse_mode="HTML"
                    )
                    return
                
    except Exception as e:
        await update.message.reply_text(f"❌ Could not check league status: {e}")
        return

    stop_event = asyncio.Event()
    async def runner():
        await watch_loop(chat_id, league, context.bot, stop_event)
    WATCHERS[chat_id] = asyncio.create_task(runner())
    
    await update.message.reply_text(f"👀 Watching <code>{league}</code> every {POLL_SECS}s. Use /unwatch to stop.", parse_mode="HTML")

async def startwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context): return
    
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text("❌ Use <code>/watch &lt;league_slug&gt;</code> in private chats.", parse_mode="HTML")
        return
    
    logger.info(f"Startwatch command from user {user.id} in group {chat.id}")
    
    league = get_group_league(chat.id)
    if not league:
        await update.message.reply_text("❌ No league attached to this group. Use <code>/setleague &lt;league_slug&gt;</code> first.", parse_mode="HTML")
        return
    
    chat_id = chat.id
    if chat_id in WATCHERS:
        await update.message.reply_text(f"✅ Already watching <code>{league}</code>!", parse_mode="HTML")
        return

    # Check if there's an active round to watch
    try:
        async with make_session() as session:
            rounds = await get_rounds(session, league)
            if not rounds:
                await update.message.reply_text(f"❌ No rounds found for league <code>{league}</code>.", parse_mode="HTML")
                return
            
            active_round = pick_current_round(rounds)  # Strict: only in_progress
            if not active_round:
                # No active round - show status of latest round with helpful messaging
                latest_round = pick_latest_round(rounds)
                if latest_round:
                    status = latest_round.get('status', 'unknown')
                    round_name = latest_round.get('name', 'Unknown Round')
                    market_closes_at = latest_round.get('marketClosesAt', '')
                    
                    # Get current standings for this round
                    try:
                        current_msg, _ = await gather_live_scores(league)
                        
                        # Parse market close date to provide better messaging
                        message = current_msg + f"\n\n❌ <b>No active round to watch</b>\n"
                        
                        if status == 'completed':
                            message += f"🏁 <code>{round_name}</code> has completed.\nWaiting for next round to start."
                        else:
                            message += f"📅 <code>{round_name}</code> status: <code>{status}</code>\nWaiting for next round to start."
                            
                        if market_closes_at:
                            try:
                                from datetime import datetime
                                market_date = datetime.fromisoformat(market_closes_at.replace("Z", "+00:00"))
                                current_date = datetime.now(market_date.tzinfo)
                                
                                if market_date > current_date:
                                    time_str = market_date.strftime("%Y-%m-%d %H:%M UTC")
                                    message += f"\n⏰ Next round likely starts around: {time_str}"
                            except Exception:
                                pass  # Ignore date parsing errors
                                
                        await update.message.reply_text(message, parse_mode="HTML")
                        return
                    except Exception as e:
                        await update.message.reply_text(
                            f"❌ No active round in progress for <code>{league}</code>.\n"
                            f"🏁 Latest round (<code>{round_name}</code>) status: <code>{status}</code>\n"
                            f"Error fetching scores: {e}", 
                            parse_mode="HTML"
                        )
                        return
                else:
                    await update.message.reply_text(
                        f"❌ No rounds found for league <code>{league}</code>.",
                        parse_mode="HTML"
                    )
                    return
                
    except Exception as e:
        await update.message.reply_text(f"❌ Could not check league status: {e}")
        return

    stop_event = asyncio.Event()
    async def runner():
        await watch_loop(chat_id, league, context.bot, stop_event)
    WATCHERS[chat_id] = asyncio.create_task(runner())
    
    logger.info(f"Started watching '{league}' for group {chat_id}")
    await update.message.reply_text(f"👀 Started watching <code>{league}</code> every {POLL_SECS}s!\nUse /stopwatch to stop.", parse_mode="HTML")

async def stopwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context): return
    
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id
    
    logger.info(f"Stopwatch command from user {user.id} in chat {chat_id}")
    
    if chat_id in WATCHERS:
        WATCHERS[chat_id].cancel()
        del WATCHERS[chat_id]
        
        # Clean up tracking data and save the updated state (no longer actively watching)
        cleanup_chat_data(chat_id)
        save_runtime_state()
        
        logger.info(f"Stopped watching for chat {chat_id}")
        await update.message.reply_text("🛑 Stopped watching.")
    else:
        await update.message.reply_text("❓ Not currently watching anything.")

# Legacy unwatch for private chats
async def unwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context): return
    await stopwatch_cmd(update, context)

async def auth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context): return
    
    user = update.effective_user
    logger.info(f"Auth command from user {user.id}")
    
    if not context.args:
        await update.message.reply_text("Usage: /auth <x-session-token>")
        return
    token = context.args[0].strip()
    CURRENT_TOKEN["x_session_token"] = token
    logger.info(f"Session token updated by user {user.id}")
    await update.message.reply_text("Token updated in memory. Try /scores again.")

async def team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_read(update, context): return
    
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"Team command from user {user.id} in chat {chat.id}")
    
    # Get league and search term
    if chat.type == "private":
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /team <league_slug> <team_name>")
            return
        league = context.args[0].strip()
        search_term = " ".join(context.args[1:]).strip()
    else:
        if not context.args:
            await update.message.reply_text("Usage: /team <team_name>")
            return
        league = get_group_league(chat.id)
        if not league:
            await update.message.reply_text("❌ No league attached to this group. Use <code>/setleague &lt;league_slug&gt;</code> first.", parse_mode="HTML")
            return
        search_term = " ".join(context.args).strip()
    
    try:
        async with make_session() as session:
            result = await find_team_by_name_or_owner(session, league, search_term, "team")
            if not result:
                await update.message.reply_text(f"❌ Team '<code>{search_term}</code>' not found in league '<code>{league}</code>'.", parse_mode="HTML")
                return
            
            team_info = result["team_info"]
            round_obj = result["round_obj"]
            round_id = result["round_id"]
            team_id = team_info["userTeam"]["id"]
            
            roster_data = await get_team_round_roster(session, round_id, team_id)
            message = fmt_team_details(team_info, round_obj, roster_data)
            
            await update.message.reply_text(message, parse_mode="HTML")
    except PermissionError as e:
        await update.message.reply_text(f"🔐 {e}")
    except Exception as e:
        logger.error(f"Error in team command: {e}")
        await update.message.reply_text(f"❌ Error: {e}")

async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_read(update, context): return
    
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"Owner command from user {user.id} in chat {chat.id}")
    
    # Get league and search term  
    if chat.type == "private":
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /owner <league_slug> <owner_name>")
            return
        league = context.args[0].strip()
        search_term = " ".join(context.args[1:]).strip()
    else:
        if not context.args:
            await update.message.reply_text("Usage: /owner <owner_name>")
            return
        league = get_group_league(chat.id)
        if not league:
            await update.message.reply_text("❌ No league attached to this group. Use <code>/setleague &lt;league_slug&gt;</code> first.", parse_mode="HTML")
            return
        search_term = " ".join(context.args).strip()
    
    try:
        async with make_session() as session:
            result = await find_team_by_name_or_owner(session, league, search_term, "owner")
            if not result:
                await update.message.reply_text(f"❌ Owner '<code>{search_term}</code>' not found in league '<code>{league}</code>'.", parse_mode="HTML")
                return
            
            team_info = result["team_info"]
            round_obj = result["round_obj"]
            round_id = result["round_id"]
            team_id = team_info["userTeam"]["id"]
            
            roster_data = await get_team_round_roster(session, round_id, team_id)
            message = fmt_team_details(team_info, round_obj, roster_data)
            
            await update.message.reply_text(message, parse_mode="HTML")
    except PermissionError as e:
        await update.message.reply_text(f"🔐 {e}")
    except Exception as e:
        logger.error(f"Error in owner command: {e}")
        await update.message.reply_text(f"❌ Error: {e}")

async def startup_health_check():
    """Perform health check on bot startup"""
    logger.info("🏥 Running startup health check...")
    
    try:
        # Test LTA Fantasy authentication
        session = make_session()
        try:
            user_data = await fetch_json(session, f'{BASE}/users/me')
            
            if user_data and 'data' in user_data:
                user_info = user_data['data']
                display_name = user_info.get('riotGameName', 'Unknown')
                tag_line = user_info.get('riotTagLine', 'Unknown')
                
                logger.info(f"✅ Authenticated as: {display_name}#{tag_line}")
                logger.info("✅ LTA Fantasy API authentication successful")
                return True
            else:
                logger.error("❌ Invalid response from /users/me endpoint")
                return False
                
        except Exception as e:
            error_msg = str(e)
            if '401' in error_msg or 'Unauthorized' in error_msg:
                logger.error("❌ LTA Authentication failed - Session token invalid or expired")
                logger.error("Use /auth <token> command to update your session token")
            elif '404' in error_msg:
                logger.error("❌ /users/me endpoint not found - Check worker configuration")
            else:
                logger.error(f"❌ LTA API health check failed: {error_msg}")
            return False
        finally:
            await session.close()
            
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return False

def main():
    # Load persistent storage
    load_group_settings()
    load_runtime_state()
    
    # Validate required environment variables
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN not set. Check your .env file.")
    if not ALLOWED_USER_ID:
        raise SystemExit("❌ ALLOWED_USER_ID not set. Check your .env file.")
    if not X_SESSION_TOKEN:
        logger.warning("X_SESSION_TOKEN not set. Use /auth command to set it.")
    else:
        logger.info("Session token configured, will run health check after bot initialization.")
    
    logger.info("Starting LTA Fantasy Bot...")
    app = Application.builder().token(BOT_TOKEN).build()

    # Set up command menus for users (shows when they type "/")
    private_commands = [
        BotCommand("start", "Show help and available commands"),
        BotCommand("scores", "Get standings for a specific league"),
        BotCommand("team", "Get detailed team information"),
        BotCommand("owner", "Find team by owner name"),
        BotCommand("watch", "Monitor a specific league for updates"),
        BotCommand("unwatch", "Stop monitoring"),
        BotCommand("auth", "Update session token"),
    ]
    
    group_commands = [
        BotCommand("start", "Show help and available commands"),
        BotCommand("scores", "Get standings for group's league"),
        BotCommand("team", "Get detailed team information"),
        BotCommand("owner", "Find team by owner name"), 
        BotCommand("setleague", "Attach a league to this group"),
        BotCommand("getleague", "Show current attached league"),
        BotCommand("startwatch", "Start monitoring group's league"),
        BotCommand("stopwatch", "Stop monitoring"),
    ]
    
    # Auto-resume functionality
    async def resume_watchers(application: Application) -> None:
        """Resume watching for chats that were being monitored before restart"""
        chats_to_resume = get_active_chats_to_resume()
        if not chats_to_resume:
            logger.info("No chats to resume watching")
            return
        
        logger.info(f"Attempting to resume watching for {len(chats_to_resume)} chats")
        resumed_count = 0
        
        for chat_id in chats_to_resume:
            try:
                # Get the league for this chat
                league = get_group_league(chat_id)
                if not league:
                    logger.warning(f"No league found for chat {chat_id}, skipping resume")
                    continue
                
                # Always try to resume - let the watch loop handle completion detection
                # This ensures users get the "ROUND COMPLETED!" message if round finished while bot was down
                stop_event = asyncio.Event()
                async def runner():
                    await watch_loop(chat_id, league, application.bot, stop_event)
                
                # Mark this chat as resuming so first poll doesn't trigger false change notifications
                FIRST_POLL_AFTER_RESUME[chat_id] = True
                
                WATCHERS[chat_id] = asyncio.create_task(runner())
                resumed_count += 1
                logger.info(f"Resumed watching '{league}' for chat {chat_id} - will check round status")
                    
            except Exception as e:
                logger.error(f"Failed to resume watching for chat {chat_id}: {e}")
        
        if resumed_count > 0:
            logger.info(f"Successfully resumed watching for {resumed_count}/{len(chats_to_resume)} chats")
        else:
            logger.warning("Could not resume watching for any chats")
            
        # Save state after resume operations (cleanup may have occurred)
        save_runtime_state()
    
    # Set commands for the bot
    async def post_init(application: Application) -> None:
        logger.info("Setting up command menus...")
        # Set default commands (will show in groups)
        await application.bot.set_my_commands(group_commands)
        
        # Set private chat specific commands  
        await application.bot.set_my_commands(
            private_commands,
            scope=BotCommandScopeAllPrivateChats()
        )
        logger.info("Command menus configured")
        
        # Run health check if session token is available
        if X_SESSION_TOKEN:
            try:
                health_result = await startup_health_check()
                if not health_result:
                    logger.warning("⚠️ Health check failed but continuing startup...")
            except Exception as e:
                logger.warning(f"⚠️ Could not run health check: {e}")
        
        # Resume watchers after a short delay to ensure bot is fully initialized
        await asyncio.sleep(2)
        await resume_watchers(application)
    
    app.post_init = post_init

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("scores", scores_cmd))
    
    # Team lookup commands
    app.add_handler(CommandHandler("team", team_cmd))
    app.add_handler(CommandHandler("owner", owner_cmd))
    
    # Group-specific commands
    app.add_handler(CommandHandler("setleague", setleague_cmd))
    app.add_handler(CommandHandler("getleague", getleague_cmd))
    app.add_handler(CommandHandler("startwatch", startwatch_cmd))
    app.add_handler(CommandHandler("stopwatch", stopwatch_cmd))
    
    # Legacy private chat commands
    app.add_handler(CommandHandler("watch", watch_cmd))
    app.add_handler(CommandHandler("unwatch", unwatch_cmd))
    app.add_handler(CommandHandler("auth", auth_cmd))
    
    # No fallback handler - let other bots handle their own commands
    
    logger.info("Bot handlers registered, starting polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
