from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_standings(
    league_slug: str,
    round_obj: Dict[str, Any],
    rows: List[Tuple[int, str, str, float]],
    score_changes: Dict[str, str] | None = None,
    include_timestamp: bool = False,
    score_type: str = "Round",
) -> str:
    title = (
        f"🏆 <b>{_escape_html(league_slug)}</b>\n"
        f"🧭 <b>{_escape_html(round_obj.get('name', ''))}</b> ({_escape_html(round_obj.get('status', ''))})\n"
        f"📊 <i>{score_type} Scores</i>"
    )

    def medal(n: int) -> str:
        if n == 1:
            return "🥇"
        elif n == 2:
            return "🥈"
        elif n == 3:
            return "🥉"
        else:
            return f"{n:>2}."

    lines: List[str] = []
    for r, t, o, p in rows:
        arrow = (score_changes or {}).get(t, "")
        safe_team = _escape_html(t)
        safe_owner = _escape_html(o)
        lines.append(f"{medal(r)} <b>{safe_team}</b> — {safe_owner} · <code>{p:.2f}</code> {arrow}")

    message = f"{title}\n\n" + ("\n".join(lines) if lines else "<i>No teams</i>")

    if include_timestamp:
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message += f"\n\n🕒 <i>Updated at {current_time}</i>"

    return message


def format_score_details(details: List[Dict[str, Any]]) -> str:
    lines: List[str] = []

    detail_names = {
        "kills": "K",
        "asssits": "A",
        "deaths": "D",
        "cs": "CS",
        "gold_advantage_at_14": "Gold@14",
        "kp_70": "KP>70%",
        "damage_share_30": "DMG>30%",
        "victory": "Victory",
        "underdog_victory": "Underdog Win",
        "stomp": "Stomp",
        "perfect_scores": "Perfect Game",
        "triple_kills": "Triple Kill",
        "over_ten_kills": "10+ Kills",
        "jng_barons": "Baron",
        "jng_dragon_soul": "Dragon Soul",
        "jng_kp_over_75": "KP>75%",
        "sup_kp_over_75": "KP>75%",
        "sup_vision_score": "Vision",
        "top_damage_share": "DMG Share",
        "top_tank": "Tank",
        "top_solo_kills": "Solo Kill",
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
    team_name = _escape_html(team_info["userTeam"]["name"])
    owner_name = _escape_html(team_info["userTeam"].get("ownerName", "Unknown"))
    rank = team_info.get("rank", "?")

    round_roster = roster_data.get("roundRoster", {})
    points_partial = round_roster.get("pointsPartial", 0) or 0
    pre_budget = round_roster.get("preRoundBudget", 0)

    def get_rank_medal(r: int) -> str:
        if r == 1:
            return "🥇"
        elif r == 2:
            return "🥈"
        elif r == 3:
            return "🥉"
        else:
            return f"#{r}"

    rank_display = get_rank_medal(rank if isinstance(rank, int) else 0)

    message = f"🏆 <b>{team_name}</b>\n"
    message += f"👤 <b>{owner_name}</b> • {rank_display}\n"
    message += f"📊 <b>{points_partial:.2f}</b> pontos • 💰 {pre_budget:.1f}M budget\n\n"
    message += f"🧭 <b>{_escape_html(round_obj.get('name', ''))}</b> ({_escape_html(round_obj.get('status', ''))})\n\n"

    roster_players = roster_data.get("rosterPlayers", [])
    if not roster_players:
        message += "<i>No roster data available</i>"
        return message

    role_emojis = {"top": "⚔️", "jungle": "🌿", "mid": "🔮", "bottom": "🏹", "support": "🛡️"}
    role_order = ["top", "jungle", "mid", "bottom", "support"]
    roster_players.sort(key=lambda p: role_order.index(p.get("role", "support")) if p.get("role") in role_order else 999)

    for player in roster_players:
        message += format_player_section(player, role_emojis)

    return message.strip()


def format_player_section(player: Dict[str, Any], role_emojis: Dict[str, str]) -> str:
    role = player.get("role", "")
    role_emoji = role_emojis.get(role, "🎮")

    esports_player = player.get("roundEsportsPlayer", {})
    pro_player = esports_player.get("proPlayer", {})

    player_name = _escape_html(pro_player.get("name", "Unknown"))
    team_name_short = _escape_html(pro_player.get("team", {}).get("name", ""))
    price = esports_player.get("preRoundPrice", 0)
    player_points = player.get("pointsPartial") or 0

    section = f"{role_emoji} <b>{player_name}</b> ({team_name_short})\n"
    section += f"💰 {price}M • 📊 <b>{player_points:.2f}</b> pts\n"

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
    games_text = ""
    for i, game in enumerate(games, 1):
        opponent = game.get("opponentTeam", {})
        opponent_name = _escape_html(opponent.get("name", "Unknown"))
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


def format_brt_time(utc_time_str: str) -> str:
    """Convert UTC time string to BRT time string using America/Sao_Paulo timezone."""
    try:
        from datetime import datetime, timezone, timedelta
        
        # Try to use zoneinfo for proper DST handling
        try:
            from zoneinfo import ZoneInfo
            # Parse UTC time
            utc_time = datetime.fromisoformat(utc_time_str.replace("Z", "+00:00"))
            
            # Convert to America/Sao_Paulo timezone (handles DST automatically)
            sao_paulo_tz = ZoneInfo("America/Sao_Paulo")
            brt_time = utc_time.astimezone(sao_paulo_tz)
            
            return brt_time.strftime("%Y-%m-%d %H:%M BRT")
        except ImportError:
            # Fallback to fixed UTC-3 if zoneinfo is not available
            pass
        
        # Parse UTC time
        utc_time = datetime.fromisoformat(utc_time_str.replace("Z", "+00:00"))
        
        # Convert to BRT (UTC-3)
        brt_offset = timedelta(hours=-3)
        brt_tz = timezone(brt_offset)
        brt_time = utc_time.astimezone(brt_tz)
        
        return brt_time.strftime("%Y-%m-%d %H:%M BRT")
    except Exception:
        return utc_time_str  # Fallback to original


def _build_team_section(
    team_name: str,
    owner_name: str,
    pre_budget: float,
    post_budget: float,
    player_changes: List[Tuple[str, str, float, float]],
) -> str:
    """Build individual team section for market open notification."""

    def format_budget_delta(pre: float, post: float) -> str:
        delta = post - pre
        if delta == 0:
            return ""
        sign = "+" if delta > 0 else ""
        return f"({sign}{delta:.1f})"

    def format_player_change(role: str, player_name: str, pre_price: float, post_price: float) -> str:
        price_delta = post_price - pre_price
        if price_delta == 0:
            return f"{_escape_html(player_name)}: 0.0"
        sign = "+" if price_delta > 0 else ""
        emoji = get_price_change_emoji(price_delta)
        return f"{emoji} {_escape_html(player_name)}: {sign}{price_delta:.1f}"

    def get_price_change_emoji(price_delta):
        if price_delta > 0:
            emoji = "📈"
        elif price_delta < 0:
            emoji = "📉"
        else:
            emoji = "🟰"
        return emoji

    budget_delta_text = format_budget_delta(pre_budget, post_budget)
    section = (
        f"{get_price_change_emoji(post_budget - pre_budget)} <b>{_escape_html(team_name)}</b> ({_escape_html(owner_name)}): "
        f"{pre_budget:.1f} → {post_budget:.1f} {budget_delta_text}"
    )

    role_order = ["top", "jungle", "mid", "bottom", "support"]

    if player_changes:
        sorted_player_changes = sorted(
            player_changes,
            key=lambda p: role_order.index(p[0]) if p[0] in role_order else 999,
        )
        player_details = [
            format_player_change(role, player_name, pre_price, post_price)
            for role, player_name, pre_price, post_price in sorted_player_changes
        ]
        if player_details:
            section += f"<blockquote expandable>{chr(10).join(player_details)}\n</blockquote>"

    return section


def fmt_manual_split_ranking(league_slug: str, completed_round: Dict[str, Any], 
                            split_totals: List[Tuple[str, str, float]]) -> str:
    """Format the manual split ranking computed after round completion."""
    
    title = (
        f"🏆 <b>{_escape_html(league_slug)}</b>\n"
        f"📊 <b>Split (acumulado)</b> após {_escape_html(completed_round.get('name', ''))}\n"
    )

    def medal(n: int) -> str:
        if n == 1:
            return "🥇"
        elif n == 2:
            return "🥈"
        elif n == 3:
            return "🥉"
        else:
            return f"{n:>2}."

    lines: List[str] = []
    for i, (team_name, owner_name, total_score) in enumerate(split_totals, 1):
        safe_team = _escape_html(team_name)
        safe_owner = _escape_html(owner_name)
        lines.append(f"{medal(i)} <b>{safe_team}</b> — {safe_owner} · <code>{total_score:.2f}</code>")

    message = f"{title}\n\n" + ("\n".join(lines) if lines else "<i>No teams</i>")
    return message


def fmt_market_open_notification(round_obj: Dict[str, Any], 
                                team_budget_data: List[Tuple[str, str, float, float, List[Tuple[str, str, float, float]]]]) -> str:
    """Format the market open notification with budget and price changes."""
    
    round_name = round_obj.get('name', 'Unknown Round')
    round_status = round_obj.get('status', 'unknown')
    market_closes_at = round_obj.get('marketClosesAt', '')
    
    title = (
        f"📣 <b>Mercado ABERTO!</b>\n"
        f"🧭 Rodada: <b>{_escape_html(round_name)}</b> ({_escape_html(round_status)})\n"
    )
    
    if market_closes_at:
        brt_time = format_brt_time(market_closes_at)
        title += f"⏳ Fecha em: <b>{brt_time}</b>\n\n"
    else:
        title += "\n"
    
    title += "💼 <b>Orçamentos finais da rodada anterior:</b>\n"
    
    team_sections = []
    for team_name, owner_name, pre_budget, post_budget, player_changes in team_budget_data:
        section = _build_team_section(team_name, owner_name, pre_budget, post_budget, player_changes)
        team_sections.append(section)
    
    message = title + "\n".join(team_sections)
    return message
