from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import logger
from .state import (
    GROUP_SETTINGS,
    GROUP_SETTINGS_FILE,
    RUNTIME_STATE_FILE,
    WatcherPhase,
)


def load_group_settings() -> None:
    """Load group settings from JSON file."""
    global GROUP_SETTINGS
    try:
        if os.path.exists(GROUP_SETTINGS_FILE):
            with open(GROUP_SETTINGS_FILE, "r") as f:
                GROUP_SETTINGS = json.load(f)
            logger.info(f"Loaded settings for {len(GROUP_SETTINGS)} groups")
        else:
            logger.info("No existing group settings file found")
    except Exception as e:
        logger.error(f"Could not load group settings: {e}")
        GROUP_SETTINGS = {}


def save_group_settings() -> None:
    try:
        with open(GROUP_SETTINGS_FILE, "w") as f:
            json.dump(GROUP_SETTINGS, f, indent=2)
        logger.debug("Group settings saved to file")
    except Exception as e:
        logger.error(f"Could not save group settings: {e}")


def load_runtime_state() -> None:
    try:
        if os.path.exists(RUNTIME_STATE_FILE):
            with open(RUNTIME_STATE_FILE, "r") as f:
                state = json.load(f)
            
            # Use function-level imports to avoid module isolation issues
            from .watchers import (
                LAST_SCORES, LAST_RANKINGS, LAST_SPLIT_RANKINGS, WATCH_MESSAGE_IDS,
                WATCHER_PHASES, REMINDER_FLAGS, STALE_COUNTERS, CURRENT_BACKOFF, WatcherPhase
            )
            
            # Clear and update the actual state variables
            LAST_SCORES.clear()
            LAST_SCORES.update({int(k): v for k, v in state.get("last_scores", {}).items()})
            
            LAST_RANKINGS.clear()
            LAST_RANKINGS.update({int(k): v for k, v in state.get("last_rankings", {}).items()})
            
            LAST_SPLIT_RANKINGS.clear()
            LAST_SPLIT_RANKINGS.update({int(k): v for k, v in state.get("last_split_rankings", {}).items()})
            
            WATCH_MESSAGE_IDS.clear()
            WATCH_MESSAGE_IDS.update({int(k): v for k, v in state.get("watch_message_ids", {}).items()})
            
            # Load phase-based state
            phases_data = state.get("watcher_phases", {})
            WATCHER_PHASES.clear()
            WATCHER_PHASES.update({int(k): WatcherPhase(v) for k, v in phases_data.items()})
            
            REMINDER_FLAGS.clear()
            REMINDER_FLAGS.update({int(k): v for k, v in state.get("reminder_flags", {}).items()})
            
            STALE_COUNTERS.clear()
            STALE_COUNTERS.update({int(k): v for k, v in state.get("stale_counters", {}).items()})
            
            CURRENT_BACKOFF.clear()
            CURRENT_BACKOFF.update({int(k): v for k, v in state.get("current_backoff", {}).items()})
            
            active_chats_count = len(state.get("active_chats", []))
            logger.info(f"Loaded runtime state for {active_chats_count} chats")
            logger.debug(f"Loaded WATCHER_PHASES: {WATCHER_PHASES}")
            logger.debug(f"Loaded REMINDER_FLAGS: {REMINDER_FLAGS}")
        else:
            logger.info("No existing runtime state file found")
    except Exception as e:
        logger.error(f"Could not load runtime state: {e}")
        logger.debug(f"Load error details: {type(e).__name__}: {str(e)}")


def save_runtime_state() -> None:
    try:
        # Use function-level imports to avoid module isolation issues
        from .watchers import (
            LAST_SCORES, LAST_RANKINGS, LAST_SPLIT_RANKINGS, WATCH_MESSAGE_IDS,
            WATCHER_PHASES, REMINDER_FLAGS, STALE_COUNTERS, CURRENT_BACKOFF
        )
        
        # WATCHERS list is maintained in watchers module; defer active_chats collection there
        state = {
            "last_scores": {str(k): v for k, v in LAST_SCORES.items()},
            "last_rankings": {str(k): v for k, v in LAST_RANKINGS.items()},
            "last_split_rankings": {str(k): v for k, v in LAST_SPLIT_RANKINGS.items()},
            "watch_message_ids": {str(k): v for k, v in WATCH_MESSAGE_IDS.items()},
            "watcher_phases": {str(k): v.value for k, v in WATCHER_PHASES.items()},
            "reminder_flags": {str(k): v for k, v in REMINDER_FLAGS.items()},
            "stale_counters": {str(k): v for k, v in STALE_COUNTERS.items()},
            "current_backoff": {str(k): v for k, v in CURRENT_BACKOFF.items()},
            "last_updated": datetime.now().isoformat(),
        }
        with open(RUNTIME_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        logger.debug("Runtime state saved")
    except Exception as e:
        logger.error(f"Could not save runtime state: {e}")


def write_runtime_state(active_chats: List[int]) -> None:
    # Import state variables at function level to ensure we get the current module's copies
    from .watchers import (
        LAST_SCORES, LAST_RANKINGS, LAST_SPLIT_RANKINGS, WATCH_MESSAGE_IDS,
        WATCHER_PHASES, REMINDER_FLAGS, STALE_COUNTERS, CURRENT_BACKOFF
    )
    
    try:
        # Debug logging to see what state variables contain
        logger.debug(f"write_runtime_state called with active_chats: {active_chats}")
        logger.debug(f"WATCHER_PHASES content: {WATCHER_PHASES}")
        logger.debug(f"REMINDER_FLAGS content: {REMINDER_FLAGS}")
        logger.debug(f"STALE_COUNTERS content: {STALE_COUNTERS}")
        logger.debug(f"CURRENT_BACKOFF content: {CURRENT_BACKOFF}")
        
        state = {
            "active_chats": list(active_chats),
            "last_scores": {str(k): v for k, v in LAST_SCORES.items()},
            "last_rankings": {str(k): v for k, v in LAST_RANKINGS.items()},
            "last_split_rankings": {str(k): v for k, v in LAST_SPLIT_RANKINGS.items()},
            "watch_message_ids": {str(k): v for k, v in WATCH_MESSAGE_IDS.items()},
            "watcher_phases": {str(k): v.value for k, v in WATCHER_PHASES.items()},
            "reminder_flags": {str(k): v for k, v in REMINDER_FLAGS.items()},
            "stale_counters": {str(k): v for k, v in STALE_COUNTERS.items()},
            "current_backoff": {str(k): v for k, v in CURRENT_BACKOFF.items()},
            "last_updated": datetime.now().isoformat(),
        }
        with open(RUNTIME_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        logger.debug(f"Runtime state saved successfully with watcher_phases: {state['watcher_phases']}")
    except Exception as e:
        logger.error(f"Could not save runtime state: {e}")


def get_active_chats_to_resume() -> List[int]:
    try:
        if os.path.exists(RUNTIME_STATE_FILE):
            with open(RUNTIME_STATE_FILE, "r") as f:
                state = json.load(f)
            return [int(chat_id) for chat_id in state.get("active_chats", [])]
    except Exception as e:
        logger.error(f"Could not load active chats list: {e}")
    return []


def get_group_league(chat_id: int) -> Optional[str]:
    return GROUP_SETTINGS.get(str(chat_id), {}).get("league")


def set_group_league(chat_id: int, league_slug: str) -> None:
    chat_key = str(chat_id)
    if chat_key not in GROUP_SETTINGS:
        GROUP_SETTINGS[chat_key] = {}
    GROUP_SETTINGS[chat_key]["league"] = league_slug
    save_group_settings()
    logger.info(f"Group {chat_id} attached to league '{league_slug}'")
