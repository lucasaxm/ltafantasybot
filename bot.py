import asyncio
import os
import hashlib
from typing import Dict, Any, List, Optional, Tuple

import aiohttp
from telegram import Update
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

# ====== Config ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
X_SESSION_TOKEN = os.getenv("X_SESSION_TOKEN", "").strip()
POLL_SECS = int(os.getenv("POLL_SECS", "30"))

BASE = "https://api.ltafantasy.com"

# runtime state
WATCHERS: Dict[int, asyncio.Task] = {}
LAST_SENT_HASH: Dict[int, str] = {}
CURRENT_TOKEN: Dict[str, str] = {"x_session_token": X_SESSION_TOKEN}  # mutable store


# ====== Access control ======
def is_authorized(update: Update) -> bool:
    user_ok = update.effective_user and update.effective_user.id == ALLOWED_USER_ID
    chat_ok = update.effective_chat and update.effective_chat.type == "private"
    return bool(user_ok and chat_ok)

async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_authorized(update):
        if update.effective_chat and update.effective_chat.type == "private":
            await context.bot.send_message(update.effective_chat.id, "Not allowed.")
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
    async with session.get(url, params=params) as r:
        if r.status in (401, 403):
            txt = await r.text()
            raise PermissionError(f"Auth failed ({r.status}). Update token with /auth <token>. Body: {txt[:180]}")
        if r.status != 200:
            txt = await r.text()
            raise RuntimeError(f"HTTP {r.status} for {url} :: {txt[:300]}")
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
def fmt_standings(league_slug: str, round_obj: Dict[str, Any], rows: List[Tuple[int, str, str, float]]) -> str:
    title = f"🏆 {league_slug}\n🧭 {round_obj.get('name')} ({round_obj.get('status')})"
    def medal(n: int) -> str:
        if n == 1:
            return "🥇"
        if n == 2:
            return "🥈"
        if n == 3:
            return "🥉"
        return f"{n:>2}."
    lines = [f"{medal(r)} {t} — {o} · {p:.2f}" for r, t, o, p in rows]
    return f"{title}\n\n" + ("\n".join(lines) if lines else "_No teams_")

def hash_payload(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ====== Core aggregation ======
async def gather_live_scores(league_slug: str) -> Tuple[str, Dict[str, Any]]:
    async with make_session() as session:
        rounds = await get_rounds(session, league_slug)
        if not rounds:
            raise RuntimeError("No rounds. Check league slug or token.")
        round_obj = pick_current_round(rounds)
        if not round_obj:
            raise RuntimeError("Could not select a round.")
        round_id = round_obj["id"]
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
        return msg, round_obj


# ====== Commands ======
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    await update.message.reply_text(
        "Commands:\n"
        "/scores <league_slug>\n"
        "/watch <league_slug>\n"
        "/unwatch\n"
        "/auth <x-session-token>  (atualiza o token em runtime)"
    )

async def scores_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    if not context.args:
        await update.message.reply_text("Usage: /scores <league_slug>")
        return
    league = context.args[0].strip()
    try:
        msg, _ = await gather_live_scores(league)
        await update.message.reply_text(msg)
    except PermissionError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def watch_loop(chat_id: int, league: str, bot, stop_event: asyncio.Event):
    while not stop_event.is_set():
        try:
            msg, _ = await gather_live_scores(league)
            h = hash_payload(msg)
            if LAST_SENT_HASH.get(chat_id) != h:
                LAST_SENT_HASH[chat_id] = h
                await bot.send_message(chat_id, msg)
        except PermissionError as e:
            await bot.send_message(chat_id, f"{e}")
            break  # stop watching until token is refreshed
        except Exception as e:
            await bot.send_message(chat_id, f"Watch error: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_SECS)
        except asyncio.TimeoutError:
            pass

async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    if not context.args:
        await update.message.reply_text("Usage: /watch <league_slug>")
        return
    league = context.args[0].strip()
    chat_id = update.effective_chat.id

    if chat_id in WATCHERS:
        WATCHERS[chat_id].cancel()
        del WATCHERS[chat_id]

    stop_event = asyncio.Event()
    async def runner():
        await watch_loop(chat_id, league, context.bot, stop_event)
    WATCHERS[chat_id] = asyncio.create_task(runner())
    await update.message.reply_text(f"Watching '{league}' every {POLL_SECS}s. Use /unwatch to stop.")

async def unwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    chat_id = update.effective_chat.id
    if chat_id in WATCHERS:
        WATCHERS[chat_id].cancel()
        del WATCHERS[chat_id]
        await update.message.reply_text("Stopped.")
    else:
        await update.message.reply_text("Nothing to stop.")

async def auth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    if not context.args:
        await update.message.reply_text("Usage: /auth <x-session-token>")
        return
    token = context.args[0].strip()
    CURRENT_TOKEN["x_session_token"] = token
    await update.message.reply_text("Token updated in memory. Try /scores again.")

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context): return
    await update.message.reply_text("Try /scores <league_slug> or /watch <league_slug>.")

def main():
    # Validate required environment variables
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN not set. Check your .env file.")
    if not ALLOWED_USER_ID:
        raise SystemExit("❌ ALLOWED_USER_ID not set. Check your .env file.")
    if not X_SESSION_TOKEN:
        print("⚠️  Warning: X_SESSION_TOKEN not set. Use /auth command to set it.")
    
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("scores", scores_cmd))
    app.add_handler(CommandHandler("watch", watch_cmd))
    app.add_handler(CommandHandler("unwatch", unwatch_cmd))
    app.add_handler(CommandHandler("auth", auth_cmd))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), fallback))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
