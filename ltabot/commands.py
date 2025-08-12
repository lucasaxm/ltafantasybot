from __future__ import annotations

import asyncio
from telegram import Update
from telegram.ext import ContextTypes

from .auth import guard_admin, guard_read
from .watchers import (
    WATCHERS,
    get_structured_scores,
    gather_live_scores,
    watch_loop,
)
from .http import make_session
from .api import get_rounds
from .storage import get_group_league, set_group_league
from .config import POLL_SECS

# Constants for common messages
NO_LEAGUE_ATTACHED_MSG = "❌ No league attached to this group. Use <code>/setleague &lt;league_slug&gt;</code> first."


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_read(update, context):
        return

    chat = update.effective_chat
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
            parse_mode="HTML",
        )
    else:
        league = get_group_league(chat.id)
        status = f"📊 Current league: <code>{league}</code>" if league else "❓ No league attached"
        await update.message.reply_text(
            f"🤖 <b>LTA Fantasy Bot</b> (Group Mode)\n\n{status}\n\n"
            "<b>Commands for All Members:</b>\n"
            "/scores - Show current standings\n"
            "/team &lt;name&gt; - Get detailed team info\n"
            "/owner &lt;name&gt; - Find team by owner name\n"
            "/getleague - Show current league\n\n"
            "<b>Admin Only Commands:</b>\n"
            "/setleague &lt;slug&gt; - Attach league to group\n"
            "/startwatch - Start live monitoring\n"
            "/stopwatch - Stop monitoring",
            parse_mode="HTML",
        )


async def scores_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_read(update, context):
        return

    chat = update.effective_chat

    if chat.type == "private":
        if not context.args:
            await update.message.reply_text("Usage: /scores <league_slug>")
            return
        league = context.args[0].strip()
    else:
        league = get_group_league(chat.id)
        if not league:
            await update.message.reply_text(
                NO_LEAGUE_ATTACHED_MSG,
                parse_mode="HTML",
            )
            return

    try:
        msg, _ = await gather_live_scores(league)
        await update.message.reply_text(msg, parse_mode="HTML")
    except PermissionError as e:
        await update.message.reply_text(f"🔐 {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def setleague_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context):
        return

    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text("❌ This command only works in groups.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setleague <league_slug>")
        return

    league_slug = context.args[0].strip()

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
    if not await guard_read(update, context):
        return

    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text("❌ This command only works in groups.")
        return

    league = get_group_league(chat.id)
    if league:
        await update.message.reply_text(f"📊 Current league: <code>{league}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text(
            "❓ No league attached to this group. Use <code>/setleague &lt;league_slug&gt;</code> to set one.",
            parse_mode="HTML",
        )


async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context):
        return

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

    try:
        async with make_session() as session:
            rounds = await get_rounds(session, league)
            if not rounds:
                await update.message.reply_text(
                    f"❌ No rounds found for league <code>{league}</code>.", parse_mode="HTML"
                )
                return
    except Exception as e:
        await update.message.reply_text(f"❌ Could not check league status: {e}")
        return

    stop_event = asyncio.Event()
    async def runner():
        await watch_loop(chat_id, league, context.bot, stop_event)
    WATCHERS[chat_id] = asyncio.create_task(runner())
    await update.message.reply_text(
        f"👀 Watching <code>{league}</code> every {POLL_SECS}s. Use /unwatch to stop.", parse_mode="HTML"
    )


async def startwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context):
        return

    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text("❌ Use <code>/watch &lt;league_slug&gt;</code> in private chats.", parse_mode="HTML")
        return

    league = get_group_league(chat.id)
    if not league:
        await update.message.reply_text(
            NO_LEAGUE_ATTACHED_MSG,
            parse_mode="HTML",
        )
        return

    chat_id = chat.id
    if chat_id in WATCHERS:
        await update.message.reply_text(f"✅ Already watching <code>{league}</code>!", parse_mode="HTML")
        return

    stop_event = asyncio.Event()
    async def runner():
        await watch_loop(chat_id, league, context.bot, stop_event)
    WATCHERS[chat_id] = asyncio.create_task(runner())

    await update.message.reply_text(
        f"👀 Started watching <code>{league}</code> every {POLL_SECS}s!\nUse /stopwatch to stop.",
        parse_mode="HTML",
    )


async def stopwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context):
        return

    chat = update.effective_chat
    chat_id = chat.id

    if chat_id in WATCHERS:
        WATCHERS[chat_id].cancel()
        del WATCHERS[chat_id]
        await update.message.reply_text("🛑 Stopped watching.")
    else:
        await update.message.reply_text("❓ Not currently watching anything.")


async def unwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context):
        return
    await stopwatch_cmd(update, context)


async def auth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /auth <x-session-token>")
        return

    from .http import CURRENT_TOKEN
    token = context.args[0].strip()
    CURRENT_TOKEN["x_session_token"] = token
    await update.message.reply_text("✅ Token updated in memory. Try /scores again.")


async def team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_read(update, context):
        return

    chat = update.effective_chat

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
            await update.message.reply_text(
                NO_LEAGUE_ATTACHED_MSG,
                parse_mode="HTML",
            )
            return
        search_term = " ".join(context.args).strip()

    try:
        from .api import find_team_by_name_or_owner, get_team_round_roster
        from .formatting import fmt_team_details

        async with make_session() as session:
            result = await find_team_by_name_or_owner(session, league, search_term, "team")
            if not result:
                await update.message.reply_text(
                    f"❌ Team '<code>{search_term}</code>' not found in league '<code>{league}</code>'.",
                    parse_mode="HTML",
                )
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
        await update.message.reply_text(f"❌ Error: {e}")


async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_read(update, context):
        return

    chat = update.effective_chat

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
            await update.message.reply_text(
                NO_LEAGUE_ATTACHED_MSG,
                parse_mode="HTML",
            )
            return
        search_term = " ".join(context.args).strip()

    try:
        from .api import find_team_by_name_or_owner, get_team_round_roster
        from .formatting import fmt_team_details

        async with make_session() as session:
            result = await find_team_by_name_or_owner(session, league, search_term, "owner")
            if not result:
                await update.message.reply_text(
                    f"❌ Owner '<code>{search_term}</code>' not found in league '<code>{league}</code>'.",
                    parse_mode="HTML",
                )
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
        await update.message.reply_text(f"❌ Error: {e}")
