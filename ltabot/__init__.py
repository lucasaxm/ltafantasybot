"""LTA Fantasy Bot modular package.

This package splits the legacy monolithic bot.py into cohesive modules:
- config: environment and constants
- http: session and request helpers
- api: LTA API surface
- formatting: message building utilities
- storage: persistence of settings and runtime state
- auth: access control helpers
- watchers: watch loop & tracking utilities
- commands: telegram command handlers
- app: application bootstrap and wiring

Public facade (re-export) for backward compatibility with tests and callers.
"""

from .config import Config, BASE, BOT_TOKEN, ALLOWED_USER_ID, X_SESSION_TOKEN, POLL_SECS
from .http import make_session, fetch_json, build_headers
from .api import (
    get_rounds,
    pick_current_round,
    pick_latest_round,
    get_league_ranking,
    get_team_round_roster,
    find_team_by_name_or_owner,
)
from .formatting import (
    fmt_standings,
    fmt_team_details,
    format_player_section,
    format_games_details,
    hash_payload,
)
from .storage import (
    load_group_settings,
    save_group_settings,
    load_runtime_state,
    save_runtime_state,
    get_active_chats_to_resume,
    get_group_league,
    set_group_league,
    GROUP_SETTINGS,
)
from .watchers import (
    gather_live_scores,
    get_split_ranking,
    get_round_scores,
    get_structured_scores,
    get_structured_split_ranking,
    calculate_score_changes,
    check_ranking_changed,
    check_split_ranking_changed,
    send_ranking_change_notification,
    send_split_ranking_change_notification,
    send_or_edit_message,
    update_tracking_data,
    cleanup_chat_data,
    WATCHERS,
    LAST_SCORES,
    LAST_RANKINGS,
    LAST_SPLIT_RANKINGS,
    WATCH_MESSAGE_IDS,
    LAST_SENT_HASH,
    FIRST_POLL_AFTER_RESUME,
)
from .auth import (
    is_group_member,
    is_group_admin,
    is_authorized_admin,
    is_authorized_read,
    guard_admin,
    guard_read,
)
from .commands import (
    start_cmd,
    scores_cmd,
    setleague_cmd,
    getleague_cmd,
    watch_cmd,
    startwatch_cmd,
    stopwatch_cmd,
    unwatch_cmd,
    auth_cmd,
    team_cmd,
    owner_cmd,
)
from .app import main, startup_health_check

__all__ = [
    # Config / HTTP
    "Config", "BASE", "BOT_TOKEN", "ALLOWED_USER_ID", "X_SESSION_TOKEN", "POLL_SECS",
    "make_session", "fetch_json", "build_headers",
    # API
    "get_rounds", "pick_current_round", "pick_latest_round", "get_league_ranking", "get_team_round_roster", "find_team_by_name_or_owner",
    # Formatting
    "fmt_standings", "fmt_team_details", "format_player_section", "format_games_details", "hash_payload",
    # Storage
    "load_group_settings", "save_group_settings", "load_runtime_state", "save_runtime_state", "get_active_chats_to_resume",
    "get_group_league", "set_group_league", "GROUP_SETTINGS",
    # Watchers
    "gather_live_scores", "get_split_ranking", "get_round_scores", "get_structured_scores", "get_structured_split_ranking",
    "calculate_score_changes", "check_ranking_changed", "check_split_ranking_changed",
    "send_ranking_change_notification", "send_split_ranking_change_notification", "send_or_edit_message",
    "update_tracking_data", "cleanup_chat_data",
    "WATCHERS", "LAST_SCORES", "LAST_RANKINGS", "LAST_SPLIT_RANKINGS", "WATCH_MESSAGE_IDS", "LAST_SENT_HASH", "FIRST_POLL_AFTER_RESUME",
    # Auth / Commands / App
    "is_group_member", "is_group_admin", "is_authorized_admin", "is_authorized_read", "guard_admin", "guard_read",
    "start_cmd", "scores_cmd", "setleague_cmd", "getleague_cmd", "watch_cmd", "startwatch_cmd", "stopwatch_cmd", "unwatch_cmd",
    "auth_cmd", "team_cmd", "owner_cmd",
    "main", "startup_health_check",
]
