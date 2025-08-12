from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import aiohttp

from .config import POLL_SECS, logger
from .http import make_session, CURRENT_TOKEN
from .api import (
    get_rounds,
    get_league_ranking,
    get_team_round_roster,
    pick_latest_round,
    pick_current_round,
)
from .formatting import fmt_standings, hash_payload
from .state import (
    WATCHERS,
    LAST_SENT_HASH,
    WATCH_MESSAGE_IDS,
    LAST_SCORES,
    LAST_RANKINGS,
    LAST_SPLIT_RANKINGS,
    FIRST_POLL_AFTER_RESUME,
)
from .storage import write_runtime_state


async def gather_live_scores(league_slug: str) -> Tuple[str, Dict[str, Any]]:
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
    async with make_session() as session:
        teams_data = await get_split_ranking(session, league, round_id)
        split_ranking = [team_name for rank, team_name, owner_name, score in teams_data]
        return split_ranking, teams_data


def calculate_score_changes(chat_id: int, current_scores: Dict[str, float]) -> Dict[str, str]:
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
    if FIRST_POLL_AFTER_RESUME.get(chat_id, False):
        return False
    return chat_id not in LAST_RANKINGS or LAST_RANKINGS[chat_id] != current_ranking


def check_split_ranking_changed(chat_id: int, current_split_ranking: List[str]) -> bool:
    if FIRST_POLL_AFTER_RESUME.get(chat_id, False):
        return False
    return chat_id not in LAST_SPLIT_RANKINGS or LAST_SPLIT_RANKINGS[chat_id] != current_split_ranking


async def send_ranking_change_notification(bot, chat_id: int, league: str, current_round, teams_data):
    ranking_msg = "🔄 <b>RANKING CHANGED!</b>\n\n"
    ranking_msg += fmt_standings(league, current_round, teams_data)
    await bot.send_message(chat_id, ranking_msg, parse_mode="HTML")


async def send_split_ranking_change_notification(bot, chat_id: int, league: str, current_round, split_teams_data):
    ranking_msg = "🔄 <b>SPLIT RANKING CHANGED!</b>\n\n"
    ranking_msg += fmt_standings(league, current_round, split_teams_data, score_type="Split")
    await bot.send_message(chat_id, ranking_msg, parse_mode="HTML")


async def send_or_edit_message(bot, chat_id: int, message: str, force_new: bool):
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


def update_tracking_data(chat_id: int, current_scores: Dict[str, float], current_ranking: List[str], current_split_ranking: List[str], message: str):
    LAST_SCORES[chat_id] = current_scores.copy()
    LAST_RANKINGS[chat_id] = current_ranking.copy()
    LAST_SPLIT_RANKINGS[chat_id] = current_split_ranking.copy()
    LAST_SENT_HASH[chat_id] = hash_payload(message)


def cleanup_chat_data(chat_id: int):
    LAST_SCORES.pop(chat_id, None)
    LAST_RANKINGS.pop(chat_id, None)
    LAST_SPLIT_RANKINGS.pop(chat_id, None)
    WATCH_MESSAGE_IDS.pop(chat_id, None)
    FIRST_POLL_AFTER_RESUME.pop(chat_id, None)

async def watch_loop(chat_id: int, league: str, bot, stop_event: asyncio.Event):
    logger.info(f"Started watch loop for chat {chat_id}, league '{league}'")
    save_counter = 0

    is_resumed = FIRST_POLL_AFTER_RESUME.get(chat_id, False)

    while not stop_event.is_set():
        try:
            save_counter += 1

            current_scores, current_ranking, teams_data, current_round = await get_structured_scores(league)

            if current_round is None:
                await bot.send_message(chat_id, f"❌ <b>Error:</b> No rounds found for league <code>{league}</code>.\nStopped watching.", parse_mode="HTML")
                break
            elif not teams_data:
                round_status = current_round.get('status', 'unknown')
                round_name = current_round.get('name', 'Unknown Round')

                if round_status == 'completed':
                    if chat_id in WATCH_MESSAGE_IDS:
                        try:
                            await bot.delete_message(chat_id=chat_id, message_id=WATCH_MESSAGE_IDS[chat_id])
                        except Exception:
                            pass
                    try:
                        final_msg, _ = await gather_live_scores(league)
                        final_msg += "\n\n🏁 <b>ROUND COMPLETED!</b>\n<i>Final scores above. Stopped watching.</i>"
                        await bot.send_message(chat_id, final_msg, parse_mode="HTML")
                    except Exception as e:
                        await bot.send_message(chat_id, f"🏁 <b>Round completed!</b> Stopped watching.\n❌ Could not fetch final scores: {e}", parse_mode="HTML")
                    break
                else:
                    await bot.send_message(chat_id, f"❌ <b>Unknown round state:</b> <code>{round_name}</code> status is <code>{round_status}</code> (not in_progress).\nStopped watching.", parse_mode="HTML")
                    break

            round_id = current_round["id"]
            current_split_ranking, split_teams_data = await get_structured_split_ranking(league, round_id)

            score_changes = calculate_score_changes(chat_id, current_scores) if not is_resumed else {}
            split_ranking_changed = check_split_ranking_changed(chat_id, current_split_ranking)

            message = fmt_standings(league, current_round, teams_data, score_changes, include_timestamp=True, score_type="Round")

            if split_ranking_changed and chat_id in LAST_SPLIT_RANKINGS and not is_resumed:
                await send_split_ranking_change_notification(bot, chat_id, league, current_round, split_teams_data)

            await send_or_edit_message(bot, chat_id, message, split_ranking_changed and not is_resumed)

            update_tracking_data(chat_id, current_scores, current_ranking, current_split_ranking, message)

            should_save = (
                save_counter >= 3 or
                split_ranking_changed or
                any(arrow != "" for arrow in score_changes.values())
            )
            if should_save:
                active_chats = list(WATCHERS.keys())
                write_runtime_state(active_chats)
                save_counter = 0

            if is_resumed:
                FIRST_POLL_AFTER_RESUME[chat_id] = False
                is_resumed = False

        except PermissionError as e:
            await bot.send_message(chat_id, f"🔐 {e}")
            break
        except Exception as e:
            await bot.send_message(chat_id, f"❌ Watch error: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_SECS)
        except asyncio.TimeoutError:
            pass

    # Cleanup on exit
    LAST_SCORES.pop(chat_id, None)
    LAST_RANKINGS.pop(chat_id, None)
    LAST_SPLIT_RANKINGS.pop(chat_id, None)
    WATCH_MESSAGE_IDS.pop(chat_id, None)
    FIRST_POLL_AFTER_RESUME.pop(chat_id, None)
    WATCHERS.pop(chat_id, None)
    write_runtime_state(list(WATCHERS.keys()))
    logger.info(f"Watch loop stopped for chat {chat_id}")

