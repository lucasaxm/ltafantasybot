from __future__ import annotations

from typing import Any, Dict, List, Optional

import aiohttp

from .config import BASE
from .http import fetch_json


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


async def get_league_ranking(session: aiohttp.ClientSession, league_slug: str, round_id: str) -> List[Dict[str, Any]]:
    data = await fetch_json(session, f"{BASE}/leagues/{league_slug}/ranking", params={"roundId": round_id, "orderBy": "split_score"})
    return data.get("data", [])


async def get_team_round_roster(session: aiohttp.ClientSession, round_id: str, team_id: str) -> Dict[str, Any]:
    data = await fetch_json(session, f"{BASE}/rosters/per-round/{round_id}/{team_id}")
    return data.get("data", {})


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

        if search_type == "team" and search_term_lower in team_name:
            return {"team_info": item, "round_obj": round_obj, "round_id": round_id}
        elif search_type == "owner" and search_term_lower in owner_name:
            return {"team_info": item, "round_obj": round_obj, "round_id": round_id}

    return None
