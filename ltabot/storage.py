from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import logger
from .state import (
    GROUP_SETTINGS,
    GROUP_SETTINGS_FILE,
    RUNTIME_STATE_FILE,
    WatcherPhase,
)
from .state import LAST_SCORE_CHANGE_AT, IS_STALE


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
                WATCHER_PHASES, REMINDER_SCHEDULES, STALE_COUNTERS, CURRENT_BACKOFF, WatcherPhase
            )
            from .state import LAST_SCORE_CHANGE_AT, IS_STALE, NO_CHANGE_POLLS, LAST_PARTIAL_RANKINGS, COMPLETED_ROUND_CACHE
            
            # Clear and update the actual state variables
            LAST_SCORES.clear()
            LAST_SCORES.update({int(k): v for k, v in state.get("last_scores", {}).items()})
            
            LAST_RANKINGS.clear()
            LAST_RANKINGS.update({int(k): v for k, v in state.get("last_rankings", {}).items()})
            
            LAST_SPLIT_RANKINGS.clear()
            LAST_SPLIT_RANKINGS.update({int(k): v for k, v in state.get("last_split_rankings", {}).items()})
            
            LAST_PARTIAL_RANKINGS.clear()
            LAST_PARTIAL_RANKINGS.update({int(k): v for k, v in state.get("last_partial_rankings", {}).items()})
            
            WATCH_MESSAGE_IDS.clear()
            WATCH_MESSAGE_IDS.update({int(k): v for k, v in state.get("watch_message_ids", {}).items()})
            
            # Load phase-based state
            phases_data = state.get("watcher_phases", {})
            WATCHER_PHASES.clear()
            WATCHER_PHASES.update({int(k): WatcherPhase(v) for k, v in phases_data.items()})
            
            REMINDER_SCHEDULES.clear()
            REMINDER_SCHEDULES.update({int(k): v for k, v in state.get("reminder_schedules", {}).items()})
            
            STALE_COUNTERS.clear()
            STALE_COUNTERS.update({int(k): v for k, v in state.get("stale_counters", {}).items()})
            
            CURRENT_BACKOFF.clear()
            CURRENT_BACKOFF.update({int(k): v for k, v in state.get("current_backoff", {}).items()})
            
            LAST_SCORE_CHANGE_AT.clear()
            LAST_SCORE_CHANGE_AT.update({int(k): v for k, v in state.get("last_score_change_at", {}).items()})

            IS_STALE.clear()
            IS_STALE.update({int(k): v for k, v in state.get("is_stale", {}).items()})

            NO_CHANGE_POLLS.clear()
            NO_CHANGE_POLLS.update({int(k): v for k, v in state.get("no_change_polls", {}).items()})
            
            COMPLETED_ROUND_CACHE.clear()
            COMPLETED_ROUND_CACHE.update(state.get("completed_round_cache", {}))

            active_chats_count = len(state.get("active_chats", []))
            logger.info(f"Loaded runtime state for {active_chats_count} chats")
            logger.debug(f"Loaded WATCHER_PHASES: {WATCHER_PHASES}")
            logger.debug(f"Loaded REMINDER_SCHEDULES: {REMINDER_SCHEDULES}")
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
            WATCHER_PHASES, REMINDER_SCHEDULES, STALE_COUNTERS, CURRENT_BACKOFF
        )
        from .state import LAST_SCORE_CHANGE_AT, IS_STALE, NO_CHANGE_POLLS, LAST_PARTIAL_RANKINGS, COMPLETED_ROUND_CACHE
        
        # WATCHERS list is maintained in watchers module; defer active_chats collection there
        state = {
            "last_scores": {str(k): v for k, v in LAST_SCORES.items()},
            "last_rankings": {str(k): v for k, v in LAST_RANKINGS.items()},
            "last_split_rankings": {str(k): v for k, v in LAST_SPLIT_RANKINGS.items()},
            "last_partial_rankings": {str(k): v for k, v in LAST_PARTIAL_RANKINGS.items()},
            "watch_message_ids": {str(k): v for k, v in WATCH_MESSAGE_IDS.items()},
            "watcher_phases": {str(k): v.value for k, v in WATCHER_PHASES.items()},
            "reminder_schedules": {str(k): v for k, v in REMINDER_SCHEDULES.items()},
            "stale_counters": {str(k): v for k, v in STALE_COUNTERS.items()},
            "current_backoff": {str(k): v for k, v in CURRENT_BACKOFF.items()},
            "last_score_change_at": {str(k): v for k, v in LAST_SCORE_CHANGE_AT.items()},
            "is_stale": {str(k): v for k, v in IS_STALE.items()},
            "completed_round_cache": COMPLETED_ROUND_CACHE,
            "last_updated": datetime.now(timezone.utc).isoformat(),
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
        WATCHER_PHASES, REMINDER_SCHEDULES, STALE_COUNTERS, CURRENT_BACKOFF
    )
    from .state import LAST_SCORE_CHANGE_AT, IS_STALE, NO_CHANGE_POLLS, LAST_PARTIAL_RANKINGS, COMPLETED_ROUND_CACHE
    
    try:
        # Debug logging to see what state variables contain
        logger.debug(f"write_runtime_state called with active_chats: {active_chats}")
        logger.debug(f"WATCHER_PHASES content: {WATCHER_PHASES}")
        logger.debug(f"REMINDER_SCHEDULES content: {REMINDER_SCHEDULES}")
        logger.debug(f"STALE_COUNTERS content: {STALE_COUNTERS}")
        logger.debug(f"CURRENT_BACKOFF content: {CURRENT_BACKOFF}")
        
        state = {
            "active_chats": list(active_chats),
            "last_scores": {str(k): v for k, v in LAST_SCORES.items()},
            "last_rankings": {str(k): v for k, v in LAST_RANKINGS.items()},
            "last_split_rankings": {str(k): v for k, v in LAST_SPLIT_RANKINGS.items()},
            "last_partial_rankings": {str(k): v for k, v in LAST_PARTIAL_RANKINGS.items()},
            "watch_message_ids": {str(k): v for k, v in WATCH_MESSAGE_IDS.items()},
            "watcher_phases": {str(k): v.value for k, v in WATCHER_PHASES.items()},
            "reminder_schedules": {str(k): v for k, v in REMINDER_SCHEDULES.items()},
            "stale_counters": {str(k): v for k, v in STALE_COUNTERS.items()},
            "current_backoff": {str(k): v for k, v in CURRENT_BACKOFF.items()},
            "last_score_change_at": {str(k): v for k, v in LAST_SCORE_CHANGE_AT.items()},
            "is_stale": {str(k): v for k, v in IS_STALE.items()},
            "no_change_polls": {str(k): v for k, v in NO_CHANGE_POLLS.items()},
            "completed_round_cache": COMPLETED_ROUND_CACHE,
            "last_updated": datetime.now(timezone.utc).isoformat(),
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


def get_group_league(chat_id: int) -> tuple[Optional[str], Optional[int]]:
    """Returns tuple (league_slug, message_thread_id)"""
    chat_settings = GROUP_SETTINGS.get(str(chat_id), {})
    league = chat_settings.get("league")
    thread_id = chat_settings.get("message_thread_id")
    return (league, thread_id)


def get_group_thread_id(chat_id: int) -> Optional[int]:
    """Helper to get just the message_thread_id for a group"""
    return GROUP_SETTINGS.get(str(chat_id), {}).get("message_thread_id")


def set_group_league(chat_id: int, league_slug: str, message_thread_id: Optional[int] = None) -> None:
    chat_key = str(chat_id)
    if chat_key not in GROUP_SETTINGS:
        GROUP_SETTINGS[chat_key] = {}
    GROUP_SETTINGS[chat_key]["league"] = league_slug
    if message_thread_id is not None:
        GROUP_SETTINGS[chat_key]["message_thread_id"] = message_thread_id
        logger.info(f"Group {chat_id} attached to league '{league_slug}' in topic {message_thread_id}")
    else:
        logger.info(f"Group {chat_id} attached to league '{league_slug}'")
    save_group_settings()
