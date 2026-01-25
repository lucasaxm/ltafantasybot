from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Dict, List, Tuple


class WatcherPhase(Enum):
    """Watcher phase definitions for the state machine"""
    PRE_MARKET = "pre_market"
    MARKET_OPEN = "market_open"
    LIVE = "live"


# Runtime state stores (module-level singletons)
WATCHERS: Dict[int, asyncio.Task] = {}
LAST_SENT_HASH: Dict[int, str] = {}
WATCH_MESSAGE_IDS: Dict[int, int] = {}
LAST_SCORES: Dict[int, Dict[str, float]] = {}
LAST_RANKINGS: Dict[int, List[str]] = {}
LAST_SPLIT_RANKINGS: Dict[int, List[str]] = {}
LAST_PARTIAL_RANKINGS: Dict[int, List[str]] = {}  # For calculated partial ranking
CACHED_PARTIAL_RANKINGS: Dict[int, Tuple[List[str], List[Tuple[int, str, str, float]]]] = {}  # Cache for expensive partial ranking calculation
COMPLETED_ROUND_CACHE: Dict[str, Dict[str, float]] = {}  # Cache completed round results: round_id -> {team_id -> score}
FIRST_POLL_AFTER_RESUME: Dict[int, bool] = {}

# Phase-based state tracking
WATCHER_PHASES: Dict[int, WatcherPhase] = {}
SCHEDULED_TASKS: Dict[int, List[asyncio.Task]] = {}
REMINDER_SCHEDULES: Dict[int, Dict[str, Dict[str, Any]]] = {}
STALE_COUNTERS: Dict[int, int] = {}
CURRENT_BACKOFF: Dict[int, float] = {}
LAST_SCORE_CHANGE_AT: Dict[int, str] = {}
IS_STALE: Dict[int, bool] = {}
NO_CHANGE_POLLS: Dict[int, int] = {}

# Error tracking to prevent spam
ERROR_COUNTS: Dict[int, int] = {}  # chat_id -> consecutive error count
LAST_ERROR_NOTIFICATION: Dict[int, float] = {}  # chat_id -> timestamp of last error message sent

# Phase change events to wake up main loops from scheduled tasks
PHASE_CHANGE_EVENTS: Dict[int, asyncio.Event] = {}

# Persistent files
GROUP_SETTINGS_FILE = "group_settings.json"
RUNTIME_STATE_FILE = "runtime_state.json"

# In-memory
GROUP_SETTINGS: Dict[str, Dict[str, Any]] = {}
