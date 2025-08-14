from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple, Optional

import aiohttp

from .config import (
    POLL_SECS,
    MAX_STALE_POLLS,
    BACKOFF_MULTIPLIER,
    MAX_POLL_SECS,
    logger,
)
from .http import make_session
from .api import (
    get_rounds,
    get_league_ranking,
    get_team_round_roster,
    pick_latest_round,
    pick_current_round,
    pick_previous_round,
    determine_phase_from_round,
    get_market_close_time,
)
from .formatting import (
    fmt_standings, 
    fmt_market_open_notification,
    fmt_manual_split_ranking,
    hash_payload,
)
from .state import (
    WATCHERS,
    LAST_SENT_HASH,
    WATCH_MESSAGE_IDS,
    LAST_SCORES,
    LAST_RANKINGS,
    LAST_SPLIT_RANKINGS,
    FIRST_POLL_AFTER_RESUME,
    WATCHER_PHASES,
    SCHEDULED_TASKS,
    REMINDER_SCHEDULES,
    STALE_COUNTERS,
    CURRENT_BACKOFF,
    PHASE_CHANGE_EVENTS,
    WatcherPhase,
)
from .storage import write_runtime_state


async def gather_live_scores(league_slug: str) -> Tuple[str, Dict[str, Any]]:
    """Gather live scores for the league - legacy compatibility function."""
    logger.debug(f"Gathering split scores for league: {league_slug}")
    async with make_session() as session:
        rounds = await get_rounds(session, league_slug)
        if not rounds:
            logger.warning(f"No rounds found for league: {league_slug}")
            raise RuntimeError("No rounds. Check league slug or token.")
        round_obj = pick_latest_round(rounds)
        if not round_obj:
            logger.warning(f"No current round found for league: {league_slug}")
            raise RuntimeError("Could not select a round.")
        round_id = round_obj["id"]
        ranking = await get_league_ranking(session, league_slug, round_id)

        rows: List[Tuple[int, str, str, float]] = []
        if ranking:
            for item in ranking:
                rank = item.get("rank", 0)
                team = item["userTeam"]["name"]
                owner = item["userTeam"].get("ownerName") or "—"
                split_score = item.get("score", 0.0)
                rows.append((rank, team, owner, float(split_score)))
            rows.sort(key=lambda r: (-r[3], r[0]))

        msg = fmt_standings(league_slug, round_obj, rows, score_type="Split")
        logger.info(f"Generated split standings for {league_slug}: {len(rows)} teams")
        return msg, round_obj


async def get_split_ranking(session: aiohttp.ClientSession, league_slug: str, round_id: str) -> List[Tuple[int, str, str, float]]:
    """Get split ranking for a specific round."""
    ranking = await get_league_ranking(session, league_slug, round_id)
    rows: List[Tuple[int, str, str, float]] = []
    for item in ranking:
        rank = item.get("rank", 0)
        team = item["userTeam"]["name"]
        owner = item["userTeam"].get("ownerName") or "—"
        split_score = item.get("score", 0.0)
        rows.append((rank, team, owner, float(split_score)))
    rows.sort(key=lambda r: (-r[3], r[0]))
    return rows


async def get_round_scores(session: aiohttp.ClientSession, league_slug: str, round_id: str) -> List[Tuple[int, str, str, float]]:
    """Get round scores for a specific round."""
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

    rows: List[Tuple[int, str, str, float]] = []
    if ranking:
        rows = await asyncio.gather(*[get_team_round_score(it) for it in ranking])
        rows.sort(key=lambda r: (-r[3], r[0]))

    return rows


async def get_structured_scores(league: str):
    """Get structured scores for live tracking - legacy compatibility."""
    async with make_session() as session:
        rounds = await get_rounds(session, league)
        if not rounds:
            return {}, [], [], None

        current_round = pick_current_round(rounds)
        if not current_round:
            latest_round = pick_latest_round(rounds)
            return {}, [], [], latest_round

        round_id = current_round["id"]
        teams_data = await get_round_scores(session, league, round_id)
        if not teams_data:
            return {}, [], [], current_round

        current_scores: Dict[str, float] = {}
        current_ranking: List[str] = []
        for rank, team_name, owner_name, pts in teams_data:
            current_scores[team_name] = pts
            current_ranking.append(team_name)

        return current_scores, current_ranking, teams_data, current_round


async def get_structured_split_ranking(league: str, round_id: str):
    """Get structured split ranking data."""
    async with make_session() as session:
        teams_data = await get_split_ranking(session, league, round_id)
        split_ranking = [team_name for rank, team_name, owner_name, score in teams_data]
        return split_ranking, teams_data


def calculate_score_changes(chat_id: int, current_scores: Dict[str, float]) -> Dict[str, str]:
    """Calculate score changes between polls."""
    score_changes: Dict[str, str] = {}
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
    """Check if ranking has changed since last poll."""
    if FIRST_POLL_AFTER_RESUME.get(chat_id, False):
        return False
    return chat_id not in LAST_RANKINGS or LAST_RANKINGS[chat_id] != current_ranking


def check_split_ranking_changed(chat_id: int, current_split_ranking: List[str]) -> bool:
    """Check if split ranking has changed since last poll."""
    if FIRST_POLL_AFTER_RESUME.get(chat_id, False):
        return False
    return chat_id not in LAST_SPLIT_RANKINGS or LAST_SPLIT_RANKINGS[chat_id] != current_split_ranking


async def send_ranking_change_notification(bot, chat_id: int, league: str, current_round, teams_data):
    """Send ranking change notification."""
    ranking_msg = "🔄 <b>RANKING CHANGED!</b>\n\n"
    ranking_msg += fmt_standings(league, current_round, teams_data)
    await bot.send_message(chat_id, ranking_msg, parse_mode="HTML")


async def send_split_ranking_change_notification(bot, chat_id: int, league: str, current_round, split_teams_data):
    """Send split ranking change notification."""
    ranking_msg = "🔄 <b>SPLIT RANKING CHANGED!</b>\n\n"
    ranking_msg += fmt_standings(league, current_round, split_teams_data, score_type="Split")
    await bot.send_message(chat_id, ranking_msg, parse_mode="HTML")


async def send_or_edit_message(bot, chat_id: int, message: str, force_new: bool):
    """Send new message or edit existing watch message."""
    if chat_id in WATCH_MESSAGE_IDS and not force_new:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=WATCH_MESSAGE_IDS[chat_id], text=message, parse_mode="HTML")
            return
        except Exception:
            pass
    try:
        sent_message = await bot.send_message(chat_id, message, parse_mode="HTML")
        WATCH_MESSAGE_IDS[chat_id] = sent_message.message_id
    except Exception:
        pass


def update_tracking_data(chat_id: int, current_scores: Dict[str, float], current_ranking: List[str], 
                        current_split_ranking: List[str], message: str):
    """Update tracking data for change detection."""
    LAST_SCORES[chat_id] = current_scores.copy()
    LAST_RANKINGS[chat_id] = current_ranking.copy()
    LAST_SPLIT_RANKINGS[chat_id] = current_split_ranking.copy()
    LAST_SENT_HASH[chat_id] = hash_payload(message)


def cleanup_chat_data(chat_id: int):
    """Clean up chat-specific tracking data."""
    LAST_SCORES.pop(chat_id, None)
    LAST_RANKINGS.pop(chat_id, None)
    LAST_SPLIT_RANKINGS.pop(chat_id, None)
    WATCH_MESSAGE_IDS.pop(chat_id, None)
    FIRST_POLL_AFTER_RESUME.pop(chat_id, None)
    WATCHER_PHASES.pop(chat_id, None)
    STALE_COUNTERS.pop(chat_id, None)
    CURRENT_BACKOFF.pop(chat_id, None)
    REMINDER_SCHEDULES.pop(chat_id, None)
    PHASE_CHANGE_EVENTS.pop(chat_id, None)
    
    # Cancel any scheduled tasks for this chat
    if chat_id in SCHEDULED_TASKS:
        for task in SCHEDULED_TASKS[chat_id]:
            if not task.done():
                task.cancel()
        del SCHEDULED_TASKS[chat_id]


def initialize_phase_state(chat_id: int, phase: WatcherPhase):
    """Initialize the phase state for a chat."""
    logger.debug(f"initialize_phase_state called for chat {chat_id} with phase {phase.value}")
    WATCHER_PHASES[chat_id] = phase
    STALE_COUNTERS[chat_id] = 0
    CURRENT_BACKOFF[chat_id] = 1.0
    if chat_id not in REMINDER_SCHEDULES:
        REMINDER_SCHEDULES[chat_id] = {}
    if chat_id not in SCHEDULED_TASKS:
        SCHEDULED_TASKS[chat_id] = []
    
    # Initialize or trigger phase change event
    if chat_id not in PHASE_CHANGE_EVENTS:
        PHASE_CHANGE_EVENTS[chat_id] = asyncio.Event()
    else:
        # Trigger the event to wake up the main loop
        PHASE_CHANGE_EVENTS[chat_id].set()
        # Reset for next phase change
        PHASE_CHANGE_EVENTS[chat_id] = asyncio.Event()
    
    logger.debug(f"After initialization - WATCHER_PHASES: {WATCHER_PHASES}")
    logger.debug(f"After initialization - REMINDER_SCHEDULES: {REMINDER_SCHEDULES}")
    logger.debug(f"After initialization - STALE_COUNTERS: {STALE_COUNTERS}")
    # Persist immediately so external monitoring sees phase change
    try:
        write_runtime_state(list(WATCHERS.keys()))
    except Exception:
        pass


def get_phase_poll_interval(phase: WatcherPhase, chat_id: int) -> Optional[float]:
    """Get the appropriate polling interval for the current phase. Returns None for event-driven phases."""
    if phase == WatcherPhase.MARKET_OPEN:
        # MARKET_OPEN is event-driven (scheduled reminders), no polling except during market close detection
        return None
        
    # Use universal POLL_SECS as base interval for all polling phases
    base_interval = POLL_SECS
    
    # Apply backoff multiplier for all phases based on stale counter
    if chat_id in CURRENT_BACKOFF and CURRENT_BACKOFF[chat_id] > 1.0:
        backoff = CURRENT_BACKOFF[chat_id]
        interval = min(base_interval * backoff, MAX_POLL_SECS)
        logger.debug(f"Applying backoff {backoff}x to {phase.value}: {interval}s (max: {MAX_POLL_SECS}s)")
        return interval
    
    return float(base_interval)


def update_stale_counter(chat_id: int, has_changes: bool):
    """Update stale counter and backoff for all polling phases."""
    if has_changes:
        # Reset stale counter and backoff when changes are detected
        STALE_COUNTERS[chat_id] = 0
        CURRENT_BACKOFF[chat_id] = 1.0
    else:
        # Increment stale counter and apply backoff
        STALE_COUNTERS[chat_id] = STALE_COUNTERS.get(chat_id, 0) + 1
        
        if STALE_COUNTERS[chat_id] >= MAX_STALE_POLLS:
            # Calculate max backoff based on universal polling settings
            max_backoff = MAX_POLL_SECS / POLL_SECS
            new_backoff = min(
                CURRENT_BACKOFF.get(chat_id, 1.0) * BACKOFF_MULTIPLIER,
                max_backoff
            )
            CURRENT_BACKOFF[chat_id] = new_backoff
            logger.debug(f"Applied backoff {new_backoff:.1f}x for chat {chat_id}")
            STALE_COUNTERS[chat_id] = 0  # Reset counter after applying backoff


def _create_reminder_task(delay: float, callback_func, chat_id: int, description: str = "reminder"):
    """Create a scheduled reminder task."""
    async def scheduled_task():
        try:
            if delay <= 0:
                # Time has passed, send immediately
                logger.info(f"Sending overdue {description} immediately for chat {chat_id} (was {delay:.0f}s late)")
            else:
                # Schedule for future
                logger.debug(f"Scheduling {description} for chat {chat_id} in {delay:.0f}s")
                await asyncio.sleep(delay)
            
            # Execute the callback
            await callback_func()
            write_runtime_state(list(WATCHERS.keys()))
            logger.info(f"Sent {description} for chat {chat_id}")
        except asyncio.CancelledError:
            logger.debug(f"Cancelled {description} task for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send {description} to chat {chat_id}: {e}")
    
    return asyncio.create_task(scheduled_task())


def _start_market_close_polling(chat_id: int, league: str, bot):
    """
    Start continuous polling for API status change from 'market_open' to 'in_progress'.
    Uses universal polling system with backoff. No timeout - keeps polling until state changes.
    Returns immediately, polling runs in background task.
    """
    logger.info(f"Starting market close polling for {league} chat {chat_id}")
    
    async def poll_for_status_change():
        try:
            poll_count = 0
            current_interval = POLL_SECS
            
            while True:
                try:
                    async with make_session() as session:
                        rounds = await get_rounds(session, league)
                        latest_round = pick_latest_round(rounds) if rounds else None
                        
                    if latest_round and latest_round.get("status") == "in_progress":
                        # Success! API shows the round is now in progress
                        initialize_phase_state(chat_id, WatcherPhase.LIVE)
                        logger.info(f"✅ API confirmed round in_progress, transitioned to LIVE for chat {chat_id}")
                        return
                    
                    # Status not changed yet, apply universal backoff logic
                    poll_count += 1
                    if poll_count >= MAX_STALE_POLLS:
                        # Apply backoff
                        max_backoff = MAX_POLL_SECS / POLL_SECS
                        backoff_factor = min(BACKOFF_MULTIPLIER ** (poll_count // MAX_STALE_POLLS), max_backoff)
                        current_interval = POLL_SECS * backoff_factor
                        logger.debug(f"Market close polling backoff {backoff_factor:.1f}x -> {current_interval}s for chat {chat_id}")
                    
                    if poll_count % 10 == 0:  # Log every 10 polls
                        round_status = latest_round.get('status', 'unknown') if latest_round else 'no_round'
                        logger.info(f"⏳ Still waiting for round status change (currently: {round_status}) for chat {chat_id} [poll #{poll_count}]")
                    
                    await asyncio.sleep(current_interval)
                    
                except Exception as e:
                    logger.warning(f"Error during market close polling for chat {chat_id}: {e}")
                    await asyncio.sleep(current_interval)
            
        except Exception as e:
            logger.error(f"Failed market close polling for chat {chat_id}: {e}")
            # Emergency fallback - still transition to avoid getting stuck
            initialize_phase_state(chat_id, WatcherPhase.LIVE)
    
    # Start the polling task (non-blocking)
    task = asyncio.create_task(poll_for_status_change())
    SCHEDULED_TASKS[chat_id].append(task)
    logger.info(f"Started market close polling task for {league} chat {chat_id}")


def schedule_market_reminders(chat_id: int, league: str, round_obj: Dict[str, Any], bot):
    """Schedule market close reminders based on marketClosesAt."""
    try:
        from datetime import datetime
        from .reminder_utils import create_reminder_schedule, get_pending_reminders, mark_reminder_sent
        
        round_id = round_obj["id"]
        reminder_key = f"{league}_{round_id}"
        
        # Ensure chat_id has a REMINDER_SCHEDULES entry
        if chat_id not in REMINDER_SCHEDULES:
            REMINDER_SCHEDULES[chat_id] = {}
        
        # Create or update the reminder schedule for this round
        if reminder_key not in REMINDER_SCHEDULES[chat_id]:
            market_closes_at = get_market_close_time(round_obj)
            if not market_closes_at:
                return
            REMINDER_SCHEDULES[chat_id][reminder_key] = create_reminder_schedule(
                round_id, league, market_closes_at
            )
        
        schedule = REMINDER_SCHEDULES[chat_id][reminder_key]
        # Use the market_closes_at from the existing schedule, not from API
        market_closes_at = schedule["market_closes_at"]
        
        close_time = datetime.fromisoformat(market_closes_at.replace("Z", "+00:00"))
        current_time = datetime.now(timezone.utc)
        
        flags = schedule.get("flags", {})
        
        # Get pending reminders based on current time
        pending = get_pending_reminders(schedule, current_time)
        
        # Schedule 24h reminder if not sent and due in the future
        if not flags.get("reminder_24h_sent", False):
            reminder_24h_time = datetime.fromisoformat(schedule["reminder_24h_at"])
            time_to_24h = (reminder_24h_time - current_time).total_seconds()
            
            if pending.get("reminder_24h_due", False):
                # Send immediately if overdue
                async def send_24h_reminder():
                    await bot.send_message(
                        chat_id,
                        "⏰ Lembrete: o mercado fecha em 24 horas ({})\n⚠️ Últimas 24h para fazer alterações no seu time!".format(
                            close_time.strftime("%Y-%m-%d %H:%M UTC")
                        ),
                        parse_mode="HTML"
                    )
                    mark_reminder_sent(schedule, "reminder_24h")
                
                # Schedule immediate execution
                task = asyncio.create_task(send_24h_reminder())
                SCHEDULED_TASKS[chat_id].append(task)
                logger.info(f"Sending overdue 24h reminder for {league} chat {chat_id}")
            elif time_to_24h > 0:
                # Schedule for future
                async def send_24h_reminder():
                    await bot.send_message(
                        chat_id,
                        "⏰ Lembrete: o mercado fecha em 24 horas ({})\n⚠️ Últimas 24h para fazer alterações no seu time!".format(
                            close_time.strftime("%Y-%m-%d %H:%M UTC")
                        ),
                        parse_mode="HTML"
                    )
                    mark_reminder_sent(schedule, "reminder_24h")
                
                task = _create_reminder_task(time_to_24h, send_24h_reminder, chat_id, "24h reminder")
                if task:
                    SCHEDULED_TASKS[chat_id].append(task)
                    logger.info(f"Scheduled 24h reminder for {league} chat {chat_id} in {time_to_24h:.0f}s")
        
        # Schedule 1h reminder if not sent and due in the future
        if not flags.get("reminder_1h_sent", False):
            reminder_1h_time = datetime.fromisoformat(schedule["reminder_1h_at"])
            time_to_1h = (reminder_1h_time - current_time).total_seconds()
            
            if pending.get("reminder_1h_due", False):
                # Send immediately if overdue
                async def send_1h_reminder():
                    await bot.send_message(
                        chat_id,
                        "⏰ Lembrete: o mercado fecha em 1 hora!\n🏃‍♂️ Última chance para fazer alterações no seu time!",
                        parse_mode="HTML"
                    )
                    mark_reminder_sent(schedule, "reminder_1h")
                
                # Schedule immediate execution
                task = asyncio.create_task(send_1h_reminder())
                SCHEDULED_TASKS[chat_id].append(task)
                logger.info(f"Sending overdue 1h reminder for {league} chat {chat_id}")
            elif time_to_1h > 0:
                # Schedule for future
                async def send_1h_reminder():
                    await bot.send_message(
                        chat_id,
                        "⏰ Lembrete: o mercado fecha em 1 hora!\n🏃‍♂️ Última chance para fazer alterações no seu time!",
                        parse_mode="HTML"
                    )
                    mark_reminder_sent(schedule, "reminder_1h")
                
                task = _create_reminder_task(time_to_1h, send_1h_reminder, chat_id, "1h reminder")
                if task:
                    SCHEDULED_TASKS[chat_id].append(task)
                    logger.info(f"Scheduled 1h reminder for {league} chat {chat_id} in {time_to_1h:.0f}s")
        
        # Schedule market close transition
        if not flags.get("closed_transition_triggered", False):
            market_close_time = datetime.fromisoformat(market_closes_at.replace("Z", "+00:00"))
            time_to_close = (market_close_time - current_time).total_seconds()
            
            if pending.get("market_close_due", False):
                # Trigger immediately if overdue
                async def trigger_close_transition():
                    await bot.send_message(
                        chat_id,
                        "▶️ Mercado fechado. Começamos a acompanhar os jogos ao vivo!",
                        parse_mode="HTML"
                    )
                    mark_reminder_sent(schedule, "closed_transition")
                    # Start polling for actual API status change (non-blocking)
                    _start_market_close_polling(chat_id, league, bot)
                
                # Schedule immediate execution
                task = asyncio.create_task(trigger_close_transition())
                SCHEDULED_TASKS[chat_id].append(task)
                logger.info(f"Triggering overdue market close for {league} chat {chat_id}")
            elif time_to_close > 0:
                # Schedule for future
                async def trigger_close_transition():
                    await bot.send_message(
                        chat_id,
                        "▶️ Mercado fechado. Começamos a acompanhar os jogos ao vivo!",
                        parse_mode="HTML"
                    )
                    mark_reminder_sent(schedule, "closed_transition")
                    # Start polling for actual API status change (non-blocking)
                    _start_market_close_polling(chat_id, league, bot)
                
                task = _create_reminder_task(time_to_close, trigger_close_transition, chat_id, "market close")
                if task:
                    SCHEDULED_TASKS[chat_id].append(task)
                    logger.info(f"Scheduled market close for {league} chat {chat_id} in {time_to_close:.0f}s")
            
    except Exception as e:
        logger.error(f"Failed to schedule market reminders for chat {chat_id}: {e}")


async def _collect_team_budget_data(session: aiohttp.ClientSession, league: str, round_obj: Dict[str, Any], rounds: List[Dict[str, Any]]) -> List:
    """Collect team budget and price data for market open notification."""
    round_id = round_obj["id"]
    ranking = await get_league_ranking(session, league, round_id)
    previous_round = pick_previous_round(rounds, round_obj)
    
    team_budget_data = []
    for item in ranking:
        team_id = item["userTeam"]["id"]
        team_name = item["userTeam"]["name"]
        owner_name = item["userTeam"].get("ownerName", "Unknown")
        
        # Get previous round roster for budget and price info
        if previous_round:
            try:
                prev_roster = await get_team_round_roster(session, previous_round["id"], team_id)
                prev_round_roster = prev_roster.get("roundRoster", {})
                
                pre_budget = prev_round_roster.get("preRoundBudget", 0)
                post_budget = prev_round_roster.get("postRoundBudget", 0)
                
                # Get player price changes
                player_changes = []
                roster_players = prev_roster.get("rosterPlayers", [])
                for player in roster_players:
                    role = player.get("role", "unknown")
                    esp = player.get("roundEsportsPlayer", {})
                    pro_player = esp.get("proPlayer", {})
                    player_name = pro_player.get("name", "Unknown")
                    pre_price = esp.get("preRoundPrice", 0)
                    post_price = esp.get("postRoundPrice", 0)
                    
                    if pre_price != post_price:  # Only include players with price changes
                        player_changes.append((role, player_name, pre_price, post_price))
                
                team_budget_data.append((team_name, owner_name, pre_budget, post_budget, player_changes))
                
            except Exception as e:
                logger.warning(f"Could not get previous round data for team {team_name}: {e}")
                team_budget_data.append((team_name, owner_name, 0, 0, []))
        else:
            team_budget_data.append((team_name, owner_name, 0, 0, []))
    
    return team_budget_data


async def send_market_open_notification(chat_id: int, league: str, round_obj: Dict[str, Any], bot):
    """Send market open notification with budget and price deltas."""
    try:
        async with make_session() as session:
            rounds = await get_rounds(session, league)
            team_budget_data = await _collect_team_budget_data(session, league, round_obj, rounds)
            
            # Format and send the market open notification
            message = fmt_market_open_notification(round_obj, team_budget_data)
            await bot.send_message(chat_id, message, parse_mode="HTML")
            
            logger.info(f"Sent market open notification for {league} to chat {chat_id}")
            
    except Exception as e:
        logger.error(f"Failed to send market open notification to chat {chat_id}: {e}")
        # Send a simpler fallback notification
        try:
            round_name = round_obj.get('name', 'Unknown Round')
            await bot.send_message(
                chat_id,
                f"📣 <b>Mercado ABERTO!</b>\n🧭 Rodada: <b>{round_name}</b>\n\n💰 Boa sorte a todos os participantes!",
                parse_mode="HTML"
            )
        except Exception:
            pass


async def compute_and_send_split_ranking(chat_id: int, league: str, completed_round: Dict[str, Any], bot):
    """Compute and send manual split ranking after round completion."""
    try:
        async with make_session() as session:
            rounds = await get_rounds(session, league)
            if not rounds:
                return
            
            # Get all rounds up to and including the completed round
            completed_index = completed_round.get("indexInSplit", 0)
            split_rounds = [r for r in rounds if r.get("indexInSplit", 0) <= completed_index and r.get("indexInSplit", 0) > 0]
            split_rounds.sort(key=lambda r: r.get("indexInSplit", 0))
            
            # Aggregate scores per team across all split rounds
            team_totals: Dict[str, Tuple[str, float]] = {}  # team_name -> (owner_name, total_score)
            
            for round_obj in split_rounds:
                round_id = round_obj["id"]
                try:
                    round_teams = await get_round_scores(session, league, round_id)
                    for _, team_name, owner_name, round_score in round_teams:
                        if team_name in team_totals:
                            # Add to existing total
                            existing_owner, existing_total = team_totals[team_name]
                            team_totals[team_name] = (existing_owner, existing_total + round_score)
                        else:
                            # First time seeing this team
                            team_totals[team_name] = (owner_name, round_score)
                except Exception as e:
                    logger.warning(f"Could not get scores for round {round_id}: {e}")
                    continue
            
            # Convert to sorted list for formatting
            split_totals = [(team_name, owner_name, total_score) for team_name, (owner_name, total_score) in team_totals.items()]
            split_totals.sort(key=lambda x: x[2], reverse=True)  # Sort by total score desc
            
            # Format and send split ranking
            if split_totals:
                split_message = fmt_manual_split_ranking(league, completed_round, split_totals)
                await bot.send_message(chat_id, split_message, parse_mode="HTML")
                logger.info(f"Sent manual split ranking for {league} to chat {chat_id}")
            
    except Exception as e:
        logger.error(f"Failed to compute split ranking for chat {chat_id}: {e}")


async def handle_round_completion(chat_id: int, league: str, completed_round: Dict[str, Any], bot):
    """Handle round completion notifications and cleanup."""
    round_name = completed_round.get('name', 'unknown')
    round_id = completed_round.get('id', 'unknown')
    logger.info(f"🏁 HANDLE_ROUND_COMPLETION called for chat {chat_id}, round {round_name}")
    
    # Check if we already handled completion for this round to avoid duplicates
    completion_flag_key = f"completion_{league}_{round_id}"
    if chat_id in REMINDER_SCHEDULES and completion_flag_key in REMINDER_SCHEDULES[chat_id]:
        logger.debug(f"Completion already handled for round {round_name} in chat {chat_id}")
        return
    
    # Mark this round's completion as handled
    if chat_id not in REMINDER_SCHEDULES:
        REMINDER_SCHEDULES[chat_id] = {}
    REMINDER_SCHEDULES[chat_id][completion_flag_key] = {"completed": True}
    
    if chat_id in WATCH_MESSAGE_IDS:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=WATCH_MESSAGE_IDS[chat_id])
        except Exception:
            pass

    try:
        # Send final round scores
        final_msg, _ = await gather_live_scores(league)
        final_msg += "\n\n🏁 <b>ROUND COMPLETED!</b>\n<i>Final scores above.</i>"
        await bot.send_message(chat_id, final_msg, parse_mode="HTML")
        
        # Compute and send split ranking
        await compute_and_send_split_ranking(chat_id, league, completed_round, bot)
        
    except Exception as e:
        await bot.send_message(chat_id, f"🏁 <b>Round completed!</b> Stopped watching.\n❌ Could not fetch final scores: {e}", parse_mode="HTML")
async def process_score_and_ranking_changes(chat_id: int, league: str, current_round, current_scores, 
                                          current_split_ranking, split_teams_data, teams_data, 
                                          is_resumed: bool, bot):
    """Process score changes and split ranking changes, send notifications."""
    score_changes = calculate_score_changes(chat_id, current_scores) if not is_resumed else {}
    split_ranking_changed = check_split_ranking_changed(chat_id, current_split_ranking)
    
    message = fmt_standings(league, current_round, teams_data, score_changes, include_timestamp=True, score_type="Round")
    
    if split_ranking_changed and chat_id in LAST_SPLIT_RANKINGS and not is_resumed:
        await send_split_ranking_change_notification(bot, chat_id, league, current_round, split_teams_data)
    
    await send_or_edit_message(bot, chat_id, message, split_ranking_changed and not is_resumed)
    
    return score_changes, split_ranking_changed


def should_save_state(save_counter: int, split_ranking_changed: bool, score_changes: dict) -> bool:
    """Determine if state should be saved based on conditions."""
    return (
        save_counter >= 3 or
        split_ranking_changed or
        any(arrow != "" for arrow in score_changes.values())
    )


def cleanup_watch_session(chat_id: int):
    """Clean up all tracking data for a watch session."""
    cleanup_chat_data(chat_id)
    WATCHERS.pop(chat_id, None)
    write_runtime_state(list(WATCHERS.keys()))


async def _handle_pre_market_phase(chat_id: int, league: str, bot) -> Optional[WatcherPhase]:
    """Handle PRE_MARKET phase logic. Returns new phase if transition occurs."""
    async with make_session() as session:
        rounds = await get_rounds(session, league)
        latest_round = pick_latest_round(rounds) if rounds else None
        
    if latest_round and latest_round.get("status") == "market_open":
        # Transition to MARKET_OPEN
        initialize_phase_state(chat_id, WatcherPhase.MARKET_OPEN)
        
        # Send market open notification
        round_id = latest_round["id"]
        reminder_key = f"{league}_{round_id}"
        
        # Check if market open notification was already sent using the new structure
        schedule = REMINDER_SCHEDULES[chat_id].get(reminder_key, {})
        flags = schedule.get("flags", {})
        
        if not flags.get("market_open_sent", False):
            await send_market_open_notification(chat_id, league, latest_round, bot)
            # Mark as sent in the schedule
            if reminder_key not in REMINDER_SCHEDULES[chat_id]:
                from .reminder_utils import create_reminder_schedule
                market_closes_at = get_market_close_time(latest_round)
                if market_closes_at:
                    REMINDER_SCHEDULES[chat_id][reminder_key] = create_reminder_schedule(
                        round_id, league, market_closes_at
                    )
            
            if reminder_key in REMINDER_SCHEDULES[chat_id]:
                # Ensure flags dict exists
                if "flags" not in REMINDER_SCHEDULES[chat_id][reminder_key]:
                    REMINDER_SCHEDULES[chat_id][reminder_key]["flags"] = {
                        "market_open_sent": False,
                        "reminder_1h_sent": False, 
                        "reminder_24h_sent": False
                    }
                REMINDER_SCHEDULES[chat_id][reminder_key]["flags"]["market_open_sent"] = True
        
        # Schedule reminders
        schedule_market_reminders(chat_id, league, latest_round, bot)
        
        logger.info(f"Transitioned to MARKET_OPEN for chat {chat_id}")
        try:
            write_runtime_state(list(WATCHERS.keys()))
        except Exception:
            pass
        return WatcherPhase.MARKET_OPEN
    
    return None


def _handle_market_open_phase() -> Optional[WatcherPhase]:
    """Handle MARKET_OPEN phase logic. No polling needed - uses datetime-based scheduling only."""
    # No polling needed in MARKET_OPEN phase - all transitions are handled by scheduled tasks
    # The scheduled market close task will trigger the transition to LIVE when needed
    return None


async def _handle_live_phase(chat_id: int, league: str, bot, is_resumed: bool, save_counter: int) -> Tuple[Optional[WatcherPhase], int]:
    """Handle LIVE phase logic. Returns new phase if transition occurs and updated save counter."""
    current_scores, current_ranking, teams_data, current_round = await get_structured_scores(league)
    
    # Check for transition to completed FIRST - before other checks
    if current_round and current_round.get("status") == "completed":
        logger.info(f"🔄 COMPLETION DETECTED: Round {current_round.get('name', 'unknown')} status is completed for chat {chat_id}")
        await handle_round_completion(chat_id, league, current_round, bot)
        # Transition back to PRE_MARKET
        initialize_phase_state(chat_id, WatcherPhase.PRE_MARKET)
        logger.info(f"Round completed, transitioned to PRE_MARKET for chat {chat_id}")
        try:
            write_runtime_state(list(WATCHERS.keys()))
        except Exception:
            pass
        return WatcherPhase.PRE_MARKET, save_counter
    
    # Check for other round status issues (but not completion, which we handled above)
    if not current_round or (current_round.get("status") != "in_progress" and current_round.get("status") != "completed"):
        round_status = current_round.get('status', 'unknown') if current_round else 'no_round'
        round_name = current_round.get('name', 'Unknown Round') if current_round else 'No Round'
        await bot.send_message(chat_id, f"❌ <b>Unknown round state:</b> <code>{round_name}</code> status is <code>{round_status}</code> (not in_progress).\nStopped watching.", parse_mode="HTML")
        return None, save_counter  # Error, exit watch loop
    
    # Check if we have no teams data but round is in progress (shouldn't happen normally)
    if not teams_data:
        logger.warning(f"No teams data for in_progress round {current_round.get('name', 'unknown')}")
        # Don't exit, just continue to next poll
        return None, save_counter + 1
    
    if current_round:
        round_id = current_round["id"]
        current_split_ranking, split_teams_data = await get_structured_split_ranking(league, round_id)

        # Process changes and send notifications
        score_changes, split_ranking_changed = await process_score_and_ranking_changes(
            chat_id, league, current_round, current_scores, current_split_ranking,
            split_teams_data, teams_data, is_resumed, bot
        )

        # Update tracking data
        update_tracking_data(chat_id, current_scores, current_ranking, current_split_ranking, 
                           fmt_standings(league, current_round, teams_data, score_changes, 
                                       include_timestamp=True, score_type="Round"))

        # Update stale counter and backoff
        has_changes = split_ranking_changed or any(arrow != "" for arrow in score_changes.values())
        update_stale_counter(chat_id, has_changes)

        # Save state if needed
        if should_save_state(save_counter, split_ranking_changed, score_changes):
            write_runtime_state(list(WATCHERS.keys()))
            save_counter = 0
    
    return None, save_counter


async def _execute_phase_logic(current_phase: WatcherPhase, chat_id: int, league: str, bot, 
                              is_resumed: bool, save_counter: int) -> Tuple[Optional[WatcherPhase], int]:
    """Execute phase-specific logic. Returns new phase (if changed) and save counter."""
    if current_phase == WatcherPhase.PRE_MARKET:
        new_phase = await _handle_pre_market_phase(chat_id, league, bot)
        return new_phase, save_counter
        
    elif current_phase == WatcherPhase.MARKET_OPEN:
        new_phase = _handle_market_open_phase()
        return new_phase, save_counter
        
    elif current_phase == WatcherPhase.LIVE:
        return await _handle_live_phase(chat_id, league, bot, is_resumed, save_counter)
    
    return None, save_counter


async def _main_loop_iteration(current_phase: WatcherPhase, chat_id: int, league: str, bot, 
                              is_resumed: bool, save_counter: int) -> Tuple[Optional[WatcherPhase], int, bool]:
    """Execute one iteration of the main loop. Returns (new_phase, save_counter, should_break)."""
    logger.debug(f"🔄 Main loop iteration: chat {chat_id}, phase {current_phase.value}, save_counter {save_counter}")
    
    # Execute phase-specific logic
    new_phase, save_counter = await _execute_phase_logic(
        current_phase, chat_id, league, bot, is_resumed, save_counter
    )
    
    if new_phase == None and save_counter == -1:  # Error condition
        return None, save_counter, True
    
    if new_phase:
        logger.info(f"🔄 PHASE TRANSITION: chat {chat_id} from {current_phase.value} to {new_phase.value}")
        current_phase = new_phase
        if new_phase == WatcherPhase.PRE_MARKET:
            return current_phase, save_counter, False  # Skip wait for immediate re-poll
    
    return current_phase, save_counter, False


async def watch_loop(chat_id: int, league: str, bot, stop_event: asyncio.Event):
    """Main stateful watch loop with phase-based polling."""
    logger.info(f"Started stateful watch loop for chat {chat_id}, league '{league}'")
    save_counter = 0
    is_resumed = FIRST_POLL_AFTER_RESUME.get(chat_id, False)

    try:
        # Determine initial phase
        async with make_session() as session:
            rounds = await get_rounds(session, league)
            latest_round = pick_latest_round(rounds) if rounds else None
            
        phase_name = determine_phase_from_round(latest_round)
        try:
            current_phase = WatcherPhase(phase_name.lower())
        except ValueError:
            logger.warning(f"Unknown phase '{phase_name}' defaulting to PRE_MARKET")
            current_phase = WatcherPhase.PRE_MARKET
        initialize_phase_state(chat_id, current_phase)
        
        # Schedule reminders if starting directly in MARKET_OPEN phase
        if current_phase == WatcherPhase.MARKET_OPEN and latest_round:
            round_id = latest_round["id"]
            reminder_key = f"{league}_{round_id}"
            
            # Initialize full reminder schedule structure
            if reminder_key not in REMINDER_SCHEDULES[chat_id]:
                from .reminder_utils import create_reminder_schedule
                market_closes_at = get_market_close_time(latest_round)
                if market_closes_at:
                    REMINDER_SCHEDULES[chat_id][reminder_key] = create_reminder_schedule(
                        round_id, league, market_closes_at
                    )
                else:
                    # Fallback if no market close time
                    REMINDER_SCHEDULES[chat_id][reminder_key] = {
                        "flags": {
                            "market_open_sent": False,
                            "reminder_24h_sent": False,
                            "reminder_1h_sent": False,
                            "closed_transition_triggered": False,
                        }
                    }
            
            schedule = REMINDER_SCHEDULES[chat_id][reminder_key]
            flags = schedule.get("flags", {})
            
            if not flags.get("market_open_sent", False):
                await send_market_open_notification(chat_id, league, latest_round, bot)
                # Ensure the structure exists before setting the flag
                if "flags" not in REMINDER_SCHEDULES[chat_id][reminder_key]:
                    REMINDER_SCHEDULES[chat_id][reminder_key]["flags"] = {
                        "market_open_sent": False,
                        "reminder_24h_sent": False, 
                        "reminder_1h_sent": False,
                        "closed_transition_triggered": False,
                    }
                REMINDER_SCHEDULES[chat_id][reminder_key]["flags"]["market_open_sent"] = True
            
            # Schedule market reminders
            schedule_market_reminders(chat_id, league, latest_round, bot)
            try:
                write_runtime_state(list(WATCHERS.keys()))
            except Exception:
                pass
        
        logger.info(f"Initialized phase {current_phase.value} for chat {chat_id}")
        try:
            write_runtime_state(list(WATCHERS.keys()))
        except Exception:
            pass

        while not stop_event.is_set():
            try:
                save_counter += 1
                
                # Check if phase was changed by another task (e.g., market close polling)
                global_phase = WATCHER_PHASES.get(chat_id)
                if global_phase and global_phase != current_phase:
                    logger.info(f"🔄 PHASE SYNC: chat {chat_id} updated from {current_phase.value} to {global_phase.value} by external task")
                    current_phase = global_phase
                
                current_phase, save_counter, should_break = await _main_loop_iteration(
                    current_phase, chat_id, league, bot, is_resumed, save_counter
                )
                
                if should_break:
                    break
                
                # Reset resume flag after first poll
                if is_resumed:
                    FIRST_POLL_AFTER_RESUME[chat_id] = False
                    is_resumed = False

            except PermissionError as e:
                await bot.send_message(chat_id, f"🔐 {e}")
                break
            except Exception as e:
                logger.error(f"Watch error for chat {chat_id}: {e}")
                await bot.send_message(chat_id, f"❌ Watch error: {e}")

            # Wait for next poll or stop event
            poll_interval = get_phase_poll_interval(current_phase, chat_id)
            
            if poll_interval is None:
                # Event-driven phase (MARKET_OPEN) - wait for phase change event or stop event
                phase_change_event = PHASE_CHANGE_EVENTS.get(chat_id)
                if phase_change_event:
                    done, pending = await asyncio.wait(
                        [
                            asyncio.create_task(stop_event.wait()),
                            asyncio.create_task(phase_change_event.wait())
                        ],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    # Cancel pending tasks
                    for task in pending:
                        task.cancel()
                else:
                    # Fallback - just wait for stop event
                    await stop_event.wait()
            else:
                # Polling phase - wait for timeout or stop event
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass

    finally:
        # Always cleanup on exit
        cleanup_watch_session(chat_id)
        logger.info(f"Watch loop stopped for chat {chat_id}")


def start_watcher(chat_id: int, league: str, bot):
    """Start the stateful watcher for a chat/league."""
    if chat_id in WATCHERS:
        return  # Already running
        
    stop_event = asyncio.Event()
    
    async def runner():
        await watch_loop(chat_id, league, bot, stop_event)
    
    WATCHERS[chat_id] = asyncio.create_task(runner())
    logger.info(f"Started watcher for chat {chat_id}, league '{league}'")

