from __future__ import annotations

import asyncio
from typing import Any, Dict, List

# Runtime state stores (module-level singletons)
WATCHERS: Dict[int, asyncio.Task] = {}
LAST_SENT_HASH: Dict[int, str] = {}
WATCH_MESSAGE_IDS: Dict[int, int] = {}
LAST_SCORES: Dict[int, Dict[str, float]] = {}
LAST_RANKINGS: Dict[int, List[str]] = {}
LAST_SPLIT_RANKINGS: Dict[int, List[str]] = {}
FIRST_POLL_AFTER_RESUME: Dict[int, bool] = {}

# Persistent files
GROUP_SETTINGS_FILE = "group_settings.json"
RUNTIME_STATE_FILE = "runtime_state.json"

# In-memory
GROUP_SETTINGS: Dict[str, Dict[str, Any]] = {}
