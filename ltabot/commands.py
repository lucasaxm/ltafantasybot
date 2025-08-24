from __future__ import annotations

from typing import Optional, Tuple
from telegram import Update
from telegram.ext import ContextTypes

from .auth import guard_admin, guard_read
from .watchers import (
    WATCHERS,
    get_structured_scores,
    gather_live_scores,
    start_watcher,
)
from .http import make_session
from .api import get_rounds
from .storage import get_group_league, set_group_league
from .config import logger

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
        await _send_scores_response(update, league)
    except PermissionError as e:
        await update.message.reply_text(f"🔐 {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def _send_scores_response(update: Update, league: str):
    """Send scores response with chart visualization and text data as caption."""
    from .watchers import gather_live_scores, calculate_partial_ranking
    from .api import get_rounds, pick_latest_round, determine_phase_from_round
    from .http import make_session
    from .charts import generate_race_chart, get_all_teams_round_stats
    
    # Use a single session for all API calls to avoid duplicates
    async with make_session() as session:
        # Get current phase and prepare text data (single API call)
        rounds = await get_rounds(session, league)
        latest_round = pick_latest_round(rounds) if rounds else None
        phase_name = determine_phase_from_round(latest_round)
        
        # For live, pre_market, and market_open phases, use calculated partial ranking only
        if phase_name.lower() in ["live", "pre_market", "market_open"]:
            try:
                # Calculate partial ranking (will make optimized API calls)
                _, partial_teams_data = await calculate_partial_ranking(league)
                if partial_teams_data:
                    from .formatting import fmt_standings
                    # Create a fake round object for formatting
                    fake_round = {"name": "Ranking Parcial", "status": phase_name.lower()}
                    caption_text = fmt_standings(league, fake_round, partial_teams_data, score_type="Parcial")
                    
                    # Add warning prefix only for live phase
                    if phase_name.lower() == "live":
                        warning_prefix = "⚠️ <i>Live tournament - scores updating in real time</i>\n\n"
                        caption_text = warning_prefix + caption_text
                        
                    # For chart data, reuse the same teams data if available
                    # Get teams_data for chart generation (reuse session)
                    teams_data = await get_all_teams_round_stats(session, league)
                else:
                    # Fallback to API ranking
                    msg, _ = await gather_live_scores(league)
                    caption_text = msg
                    teams_data = await get_all_teams_round_stats(session, league)
            except Exception as e:
                # If there's an error calculating partial ranking, use API ranking
                logger.warning(f"Failed to calculate partial ranking for /scores: {e}")
                msg, _ = await gather_live_scores(league)
                caption_text = msg
                teams_data = await get_all_teams_round_stats(session, league)
        else:
            # For other phases, use the standard API ranking
            msg, _ = await gather_live_scores(league)
            caption_text = msg
            teams_data = await get_all_teams_round_stats(session, league)
        
        # Try to generate and send chart with text as caption
        try:
            if teams_data:
                chart_buffer = generate_race_chart(teams_data)
                if chart_buffer:
                    await update.message.reply_photo(
                        photo=chart_buffer,
                        caption=caption_text,
                        parse_mode="HTML"
                    )
                    return
                else:
                    logger.warning("Chart generation failed, falling back to text only")
            else:
                logger.warning("No chart data available, falling back to text only")
        except Exception as e:
            logger.warning(f"Chart generation failed: {e}, falling back to text only")
    
    # Fallback to text-only response if chart fails
    await update.message.reply_text(caption_text, parse_mode="HTML")


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

    start_watcher(chat_id, league, context.bot)
    await update.message.reply_text(
        f"👀 Watching <code>{league}</code> with dynamic intervals by phase. Use /unwatch to stop.", parse_mode="HTML"
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

    start_watcher(chat_id, league, context.bot)

    await update.message.reply_text(
        f"👀 Started watching <code>{league}</code> with dynamic intervals by phase!\nUse /stopwatch to stop.",
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
        try:
            from .storage import write_runtime_state
            write_runtime_state(list(WATCHERS.keys()))
        except Exception:
            pass
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


async def _handle_market_open_roster_fallback(session, league, search_term, search_type, update):
    """Handle roster fetch during market_open by falling back to previous round."""
    from .api import find_team_by_name_or_owner, get_team_round_roster, pick_previous_round, get_rounds
    from .formatting import fmt_team_details
    
    rounds = await get_rounds(session, league)
    latest_round = [r for r in rounds if r.get("status") == "market_open"]
    
    if latest_round:
        latest_round = latest_round[0]
        previous_round = pick_previous_round(rounds, latest_round)
        
        if previous_round:
            # Try with previous round
            result = await find_team_by_name_or_owner(session, league, search_term, search_type)
            if result:
                team_info = result["team_info"]
                team_id = team_info["userTeam"]["id"]
                
                try:
                    roster_data = await get_team_round_roster(session, previous_round["id"], team_id)
                    message = await fmt_team_details(team_info, previous_round, roster_data)
                    message = "⚠️ <b>Mercado está aberto</b>; mostrando roster da rodada anterior e preços.\n\n" + message
                    await update.message.reply_text(message, parse_mode="HTML")
                    return True
                except Exception:
                    pass  # Fall through to normal error handling
    
    return False


async def _get_team_command_params(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[Tuple[str, str]]:
    """Get league and search_term for team command. Returns None if validation fails."""
    chat = update.effective_chat

    if chat.type == "private":
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /team <league_slug> <team_name>")
            return None
        return context.args[0].strip(), " ".join(context.args[1:]).strip()
    else:
        if not context.args:
            await update.message.reply_text("Usage: /team <team_name>")
            return None
        league = get_group_league(chat.id)
        if not league:
            await update.message.reply_text(NO_LEAGUE_ATTACHED_MSG, parse_mode="HTML")
            return None
        return league, " ".join(context.args).strip()


async def team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Delegate to generic lookup (mode=team)
    await _generic_team_lookup(update, context, mode="team")


async def _generic_team_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    """Unified handler for /team and /owner commands with market_open fallback."""
    if not await guard_read(update, context):
        return
    league, search_term = await _parse_lookup_params(update, context, mode)
    if not league:
        return
    await _perform_lookup_and_reply(update, league, search_term, mode)


async def _parse_lookup_params(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> Tuple[Optional[str], Optional[str]]:
    chat = update.effective_chat
    if chat.type == "private":
        if len(context.args) < 2:
            await update.message.reply_text(f"Usage: /{mode} <league_slug> <{mode}_name>")
            return None, None
        return context.args[0].strip(), " ".join(context.args[1:]).strip()
    if not context.args:
        await update.message.reply_text(f"Usage: /{mode} <{mode}_name>")
        return None, None
    league = get_group_league(chat.id)
    if not league:
        await update.message.reply_text(NO_LEAGUE_ATTACHED_MSG, parse_mode="HTML")
        return None, None
    return league, " ".join(context.args).strip()


async def _perform_lookup_and_reply(update: Update, league: str, search_term: str, mode: str):
    from .api import find_team_by_name_or_owner, get_team_round_roster
    from .formatting import fmt_team_details
    from .api import get_rounds, pick_previous_round
    from .champions import ensure_champion_data_loaded
    
    # Ensure champion data is loaded for proper champion names
    await ensure_champion_data_loaded()
    
    try:
        async with make_session() as session:
            result = await find_team_by_name_or_owner(session, league, search_term, mode)
            if not result:
                noun = "Team" if mode == "team" else "Owner"
                await update.message.reply_text(
                    f"❌ {noun} '<code>{search_term}</code>' not found in league '<code>{league}</code>'.",
                    parse_mode="HTML",
                )
                return
            team_info = result["team_info"]
            base_round_obj = result["round_obj"]
            team_id = team_info["userTeam"]["id"]

            # Proactive previous-round selection during market_open before any roster fetch
            use_round_obj = base_round_obj
            proactive_note = ""
            if base_round_obj.get("status") == "market_open":
                try:
                    rounds = await get_rounds(session, league)
                    previous_round = pick_previous_round(rounds, base_round_obj)
                    if previous_round:
                        use_round_obj = previous_round
                        proactive_note = "⚠️ <b>Mercado aberto</b>; mostrando roster da rodada anterior.\n\n"
                except Exception:
                    pass  # Fall back silently

            round_id = use_round_obj["id"]

            try:
                roster_data = await get_team_round_roster(session, round_id, team_id)
                message = await fmt_team_details(team_info, use_round_obj, roster_data)
                if proactive_note:
                    message = proactive_note + message
                await update.message.reply_text(message, parse_mode="HTML")
            except PermissionError:
                # As a safety net, attempt legacy fallback path
                if await _handle_market_open_roster_fallback(session, league, search_term, mode, update):
                    return
                raise
    except PermissionError as e:
        await update.message.reply_text(f"🔐 {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _generic_team_lookup(update, context, mode="owner")


async def watchstatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Diagnostic command to report current watch state for this chat."""
    chat = update.effective_chat
    chat_id = chat.id
    from .state import WATCHER_PHASES, STALE_COUNTERS, CURRENT_BACKOFF, REMINDER_SCHEDULES
    if chat_id not in WATCHER_PHASES:
        await update.message.reply_text("ℹ️ Não há watcher ativo neste chat.")
        return
    phase = WATCHER_PHASES.get(chat_id)
    stale = STALE_COUNTERS.get(chat_id, 0)
    backoff = CURRENT_BACKOFF.get(chat_id, 1.0)
    # Pick the most recent reminder key if any
    reminder_summary = "—"
    schedules_dict = REMINDER_SCHEDULES.get(chat_id, {})
    if schedules_dict:
        try:
            # Use max by lexical which includes round id; acceptable heuristic
            latest_key = sorted(schedules_dict.keys())[-1]
            flags = schedules_dict[latest_key].get("flags", {})
            reminder_summary = ", ".join(f"{k}:{'✅' if v else '❌'}" for k, v in flags.items())
        except Exception:
            pass
    msg = (
        f"🔍 <b>Status do Watcher</b>\n"
        f"Fase: <b>{phase.value}</b>\n"
        f"Stale polls: {stale}\n"
        f"Backoff: {backoff:.2f}x\n"
        f"Reminders: {reminder_summary}"
    )
    await update.message.reply_text(msg, parse_mode="HTML")
