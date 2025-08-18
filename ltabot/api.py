from __future__ import annotations

from typing import Any, Dict, List, Optional

import aiohttp

from .config import BASE, cached_api_call
from .http import fetch_json


@cached_api_call(lambda session, league_slug: f"rounds:{league_slug}")
async def get_rounds(session: aiohttp.ClientSession, league_slug: str) -> List[Dict[str, Any]]:
    data = await fetch_json(session, f"{BASE}/leagues/{league_slug}/rounds")
    return data.get("data", [])


def pick_current_round(rounds: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    inprog = [r for r in rounds if r.get("status") == "in_progress"]
    if inprog:
        inprog.sort(key=lambda r: r.get("indexInSplit", -1), reverse=True)
        return inprog[0]
    return None


def pick_latest_round(rounds: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    inprog = [r for r in rounds if r.get("status") == "in_progress"]
    if inprog:
        inprog.sort(key=lambda r: r.get("indexInSplit", -1), reverse=True)
        return inprog[0]

    def ts(r: Dict[str, Any]) -> float:
        s = r.get("marketClosesAt") or ""
        try:
            from datetime import datetime
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    return sorted(rounds, key=ts, reverse=True)[0] if rounds else None


@cached_api_call(lambda session, league_slug, round_id: f"ranking:{league_slug}:{round_id}")
async def get_league_ranking(session: aiohttp.ClientSession, league_slug: str, round_id: str) -> List[Dict[str, Any]]:
    data = await fetch_json(session, f"{BASE}/leagues/{league_slug}/ranking", params={"roundId": round_id, "orderBy": "split_score"})
    return data.get("data", [])


@cached_api_call(lambda session, round_id, team_id: f"roster:{round_id}:{team_id}")
async def get_team_round_roster(session: aiohttp.ClientSession, round_id: str, team_id: str) -> Dict[str, Any]:
    data = await fetch_json(session, f"{BASE}/rosters/per-round/{round_id}/{team_id}")
    return data.get("data", {})


@cached_api_call(lambda session, user_team_id: f"user_team_stats:{user_team_id}")
async def get_user_team_round_stats(session: aiohttp.ClientSession, user_team_id: str) -> List[Dict[str, Any]]:
    """Get all round statistics for a specific user team using the efficient new endpoint."""
    data = await fetch_json(session, f"{BASE}/user-teams/{user_team_id}/round-stats")
    return data.get("data", [])


@cached_api_call(lambda session, league_slug, search_term, search_type: f"find_team:{league_slug}:{search_term}:{search_type}")
async def find_team_by_name_or_owner(session: aiohttp.ClientSession, league_slug: str, search_term: str, search_type: str) -> Optional[Dict[str, Any]]:
    rounds = await get_rounds(session, league_slug)
    if not rounds:
        return None

    round_obj = pick_latest_round(rounds)
    if not round_obj:
        return None

    round_id = round_obj["id"]
    ranking = await get_league_ranking(session, league_slug, round_id)

    search_term_lower = search_term.lower()

    for item in ranking:
        team_name = item["userTeam"]["name"].lower()
        owner_name = (item["userTeam"].get("ownerName") or "").lower()

        if ((search_type == "team" and search_term_lower in team_name) or 
            (search_type == "owner" and search_term_lower in owner_name)):
            return {"team_info": item, "round_obj": round_obj, "round_id": round_id}

    return None


def pick_previous_round(rounds: List[Dict[str, Any]], current_round: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick the previous round relative to the current round."""
    current_index = current_round.get("indexInSplit", -1)
    if current_index <= 1:  # No previous round if we're at index 1 or invalid
        return None
    
    # Look for round with indexInSplit = current_index - 1
    for round_obj in rounds:
        if round_obj.get("indexInSplit") == current_index - 1:
            return round_obj
    
    return None


def determine_phase_from_round(latest_round: Optional[Dict[str, Any]]) -> str:
    """Determine the appropriate watcher phase based on the latest round status.

    Returns lowercase enum values matching WatcherPhase.value to avoid mismatches.
    Fallback to 'pre_market' if unknown.
    """
    if not latest_round:
        return "pre_market"

    status = latest_round.get("status", "unknown")

    if status == "in_progress":
        return "live"
    if status == "market_open":
        return "market_open"
    # completed, upcoming, or any other status
    return "pre_market"


def get_market_close_time(latest_round: Optional[Dict[str, Any]]) -> Optional[str]:
    """Get the market close time from the round object."""
    if not latest_round:
        return None
    return latest_round.get("marketClosesAt")
