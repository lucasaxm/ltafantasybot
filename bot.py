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

# ====== Config ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
X_SESSION_TOKEN = os.getenv("X_SESSION_TOKEN", "").strip()
POLL_SECS = int(os.getenv("POLL_SECS", "30"))

BASE = "https://api.ltafantasy.com"

# runtime state
WATCHERS: Dict[int, asyncio.Task] = {}
LAST_SENT_HASH: Dict[int, str] = {}
WATCH_MESSAGE_IDS: Dict[int, int] = {}  # chat_id -> message_id for editing
LAST_SCORES: Dict[int, Dict[str, float]] = {}  # chat_id -> {team_name: score}
LAST_RANKINGS: Dict[int, List[str]] = {}  # chat_id -> [team_names in rank order]
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
    global LAST_SCORES, LAST_RANKINGS, WATCH_MESSAGE_IDS
    try:
        if os.path.exists(RUNTIME_STATE_FILE):
            with open(RUNTIME_STATE_FILE, 'r') as f:
                state = json.load(f)
            
            # Convert string keys back to int for chat_ids
            LAST_SCORES = {int(k): v for k, v in state.get("last_scores", {}).items()}
            LAST_RANKINGS = {int(k): v for k, v in state.get("last_rankings", {}).items()}
            WATCH_MESSAGE_IDS = {int(k): v for k, v in state.get("watch_message_ids", {}).items()}
            
            logger.info(f"Loaded runtime state for {len(LAST_SCORES)} chats")
        else:
            logger.info("No existing runtime state file found")
    except Exception as e:
        logger.error(f"Could not load runtime state: {e}")
        # Initialize empty dictionaries on error
        LAST_SCORES = {}
        LAST_RANKINGS = {}
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

async def is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is authorized to use the bot"""
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

async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Guard function to check authorization"""
    if not await is_authorized(update, context):
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
    # set default headers on the session so redirects keep them
    return aiohttp.ClientSession(timeout=timeout, headers=build_headers())

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


# ====== Formatting ======
def fmt_standings(league_slug: str, round_obj: Dict[str, Any], rows: List[Tuple[int, str, str, float]], 
                 score_changes: Dict[str, str] = None, include_timestamp: bool = False) -> str:
    # HTML escape function for text content
    def escape_html(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    title = f"🏆 <b>{escape_html(league_slug)}</b>\n🧭 <b>{escape_html(round_obj.get('name', ''))}</b> ({escape_html(round_obj.get('status', ''))})"
    
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

def hash_payload(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ====== Core aggregation ======
async def gather_live_scores(league_slug: str) -> Tuple[str, Dict[str, Any]]:
    logger.debug(f"Gathering scores for league: {league_slug}")
    async with make_session() as session:
        rounds = await get_rounds(session, league_slug)
        if not rounds:
            logger.warning(f"No rounds found for league: {league_slug}")
            raise RuntimeError("No rounds. Check league slug or token.")
        round_obj = pick_current_round(rounds)
        if not round_obj:
            logger.warning(f"No current round found for league: {league_slug}")
            raise RuntimeError("Could not select a round.")
        round_id = round_obj["id"]
        logger.debug(f"Using round: {round_obj.get('name', round_id)} ({round_obj.get('status')})")
        ranking = await get_league_ranking(session, league_slug, round_id)

        async def row(item: Dict[str, Any]) -> Tuple[int, str, str, float]:
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

        rows: List[Tuple[int, str, str, float]] = []
        if ranking:
            rows = await asyncio.gather(*[row(it) for it in ranking])
            rows.sort(key=lambda r: (-r[3], r[0]))
        msg = fmt_standings(league_slug, round_obj, rows)
        logger.info(f"Generated standings for {league_slug}: {len(rows)} teams")
        return msg, round_obj


# ====== Commands ======
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"Start command from user {user.id} in chat {chat.id} ({chat.type})")
    
    if chat.type == "private":
        await update.message.reply_text(
            "🤖 <b>LTA Fantasy Bot</b>\n\n"
            "<b>Private Chat Commands:</b>\n"
            "/scores &lt;league_slug&gt; - Get current standings\n"
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
            "<b>Admin Commands:</b>\n"
            "/setleague &lt;slug&gt; - Attach league to group\n"
            "/startwatch - Start live monitoring\n"
            "/stopwatch - Stop monitoring\n"
            "/getleague - Show current league",
            parse_mode="HTML"
        )

async def scores_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    
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
        await update.message.reply_text(msg)
    except PermissionError as e:
        await update.message.reply_text(f"🔐 {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def setleague_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    
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
    if not await guard(update, context): return
    
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
            
            # Get structured data for score tracking
            current_scores, current_ranking, teams_data, current_round = await get_structured_scores(league)
            if not teams_data:
                logger.warning(f"No teams data for league: {league}")
                await asyncio.sleep(POLL_SECS)
                continue
            
            # Calculate score changes (but not on first poll after resume to avoid false arrows)
            score_changes = calculate_score_changes(chat_id, current_scores) if not is_resumed else {}
            
            # Check if ranking changed (will return False on first poll after resume)
            ranking_changed = check_ranking_changed(chat_id, current_ranking)
            
            # Build message with changes and timestamp
            message = fmt_standings(league, current_round, teams_data, score_changes, include_timestamp=True)
            
            # Handle ranking change notification (only if not first poll after resume)
            if ranking_changed and chat_id in LAST_RANKINGS and not is_resumed:
                await send_ranking_change_notification(bot, chat_id, league, current_round, teams_data)
            
            # Send or edit the main message - always try to edit first for seamless experience
            await send_or_edit_message(bot, chat_id, message, ranking_changed and not is_resumed, poll_count)
            
            # Update tracking data
            update_tracking_data(chat_id, current_scores, current_ranking, message)
            
            # Save runtime state more frequently and when important changes happen
            should_save = (
                save_counter >= 3 or  # Every 3 polls (90 seconds)
                ranking_changed or    # When ranking changes
                any(arrow != "" for arrow in score_changes.values())  # When any score changes
            )
            
            if should_save:
                save_reason = []
                if save_counter >= 3: save_reason.append("interval")
                if ranking_changed and not is_resumed: save_reason.append("ranking_changed") 
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
    save_runtime_state()
    cleanup_chat_data(chat_id)
    logger.info(f"Watch loop stopped for chat {chat_id}")

async def get_structured_scores(league: str):
    """Get structured score data for tracking."""
    async with make_session() as session:
        rounds = await get_rounds(session, league)
        if not rounds:
            return {}, [], [], None
            
        current_round = pick_current_round(rounds)
        if not current_round:
            return {}, [], [], None
            
        round_id = current_round["id"]
        ranking = await get_league_ranking(session, league, round_id)
        
        if not ranking:
            return {}, [], [], current_round
        
        current_scores = {}
        teams_data = []
        
        for item in ranking:
            team_name = item["userTeam"]["name"]
            team_id = item["userTeam"]["id"]
            owner_name = item["userTeam"].get("ownerName") or "—"
            rank = item.get("rank", 0)
            
            roster = await get_team_round_roster(session, round_id, team_id)
            rr = (roster.get("roundRoster") or {})
            pts = rr.get("pointsPartial")
            if pts is None:
                pts = rr.get("points") or 0.0
            pts = float(pts)
            
            current_scores[team_name] = pts
            teams_data.append((rank, team_name, owner_name, pts))
        
        teams_data.sort(key=lambda r: (-r[3], r[0]))
        current_ranking = [team[1] for team in teams_data]
        
        return current_scores, current_ranking, teams_data, current_round

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

async def send_ranking_change_notification(bot, chat_id: int, league: str, current_round, teams_data):
    """Send a ranking change notification."""
    ranking_msg = "🔄 <b>RANKING CHANGED!</b>\n\n"
    ranking_msg += fmt_standings(league, current_round, teams_data)
    
    await bot.send_message(chat_id, ranking_msg, parse_mode="HTML")
    logger.info(f"Sent ranking change notification to chat {chat_id}")

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
                        current_ranking: List[str], message: str):
    """Update all tracking dictionaries."""
    LAST_SCORES[chat_id] = current_scores.copy()
    LAST_RANKINGS[chat_id] = current_ranking.copy()
    LAST_SENT_HASH[chat_id] = hash_payload(message)

def cleanup_chat_data(chat_id: int):
    """Clean up tracking data for a chat."""
    LAST_SCORES.pop(chat_id, None)
    LAST_RANKINGS.pop(chat_id, None)
    WATCH_MESSAGE_IDS.pop(chat_id, None)
    FIRST_POLL_AFTER_RESUME.pop(chat_id, None)

# Legacy watch command for private chats
async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    
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

    stop_event = asyncio.Event()
    async def runner():
        await watch_loop(chat_id, league, context.bot, stop_event)
    WATCHERS[chat_id] = asyncio.create_task(runner())
    
    await update.message.reply_text(f"👀 Watching <code>{league}</code> every {POLL_SECS}s. Use /unwatch to stop.", parse_mode="HTML")

async def startwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    
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

    stop_event = asyncio.Event()
    async def runner():
        await watch_loop(chat_id, league, context.bot, stop_event)
    WATCHERS[chat_id] = asyncio.create_task(runner())
    
    logger.info(f"Started watching '{league}' for group {chat_id}")
    await update.message.reply_text(f"👀 Started watching <code>{league}</code> every {POLL_SECS}s!\nUse /stopwatch to stop.", parse_mode="HTML")

async def stopwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    
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
    if not await guard(update, context): return
    await stopwatch_cmd(update, context)

async def auth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    
    user = update.effective_user
    logger.info(f"Auth command from user {user.id}")
    
    if not context.args:
        await update.message.reply_text("Usage: /auth <x-session-token>")
        return
    token = context.args[0].strip()
    CURRENT_TOKEN["x_session_token"] = token
    logger.info(f"Session token updated by user {user.id}")
    await update.message.reply_text("Token updated in memory. Try /scores again.")

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
    
    logger.info("Starting LTA Fantasy Bot...")
    app = Application.builder().token(BOT_TOKEN).build()

    # Set up command menus for users (shows when they type "/")
    private_commands = [
        BotCommand("start", "Show help and available commands"),
        BotCommand("scores", "Get standings for a specific league"),
        BotCommand("watch", "Monitor a specific league for updates"),
        BotCommand("unwatch", "Stop monitoring"),
        BotCommand("auth", "Update session token"),
    ]
    
    group_commands = [
        BotCommand("start", "Show help and available commands"),
        BotCommand("scores", "Get standings for group's league"),
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
                
                # Start watching again silently
                stop_event = asyncio.Event()
                async def runner():
                    await watch_loop(chat_id, league, application.bot, stop_event)
                
                # Mark this chat as resuming so first poll doesn't trigger false change notifications
                FIRST_POLL_AFTER_RESUME[chat_id] = True
                
                WATCHERS[chat_id] = asyncio.create_task(runner())
                resumed_count += 1
                logger.info(f"Silently resumed watching '{league}' for chat {chat_id}")
                    
            except Exception as e:
                logger.error(f"Failed to resume watching for chat {chat_id}: {e}")
        
        if resumed_count > 0:
            logger.info(f"Successfully resumed watching for {resumed_count}/{len(chats_to_resume)} chats")
        else:
            logger.warning("Could not resume watching for any chats")
    
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
        
        # Resume watchers after a short delay to ensure bot is fully initialized
        await asyncio.sleep(2)
        await resume_watchers(application)
    
    app.post_init = post_init

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("scores", scores_cmd))
    
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
