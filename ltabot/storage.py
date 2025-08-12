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
    LAST_SCORES,
    LAST_RANKINGS,
    LAST_SPLIT_RANKINGS,
    WATCH_MESSAGE_IDS,
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
    global LAST_SCORES, LAST_RANKINGS, LAST_SPLIT_RANKINGS, WATCH_MESSAGE_IDS
    try:
        if os.path.exists(RUNTIME_STATE_FILE):
            with open(RUNTIME_STATE_FILE, "r") as f:
                state = json.load(f)
            LAST_SCORES = {int(k): v for k, v in state.get("last_scores", {}).items()}
            LAST_RANKINGS = {int(k): v for k, v in state.get("last_rankings", {}).items()}
            LAST_SPLIT_RANKINGS = {int(k): v for k, v in state.get("last_split_rankings", {}).items()}
            WATCH_MESSAGE_IDS = {int(k): v for k, v in state.get("watch_message_ids", {}).items()}
            logger.info(f"Loaded runtime state for {len(LAST_SCORES)} chats")
        else:
            logger.info("No existing runtime state file found")
    except Exception as e:
        logger.error(f"Could not load runtime state: {e}")
        LAST_SCORES = {}
        LAST_RANKINGS = {}
        LAST_SPLIT_RANKINGS = {}
        WATCH_MESSAGE_IDS = {}


def save_runtime_state() -> None:
    try:
        # WATCHERS list is maintained in watchers module; defer active_chats collection there
        state = {
            "last_scores": {str(k): v for k, v in LAST_SCORES.items()},
            "last_rankings": {str(k): v for k, v in LAST_RANKINGS.items()},
            "last_split_rankings": {str(k): v for k, v in LAST_SPLIT_RANKINGS.items()},
            "watch_message_ids": {str(k): v for k, v in WATCH_MESSAGE_IDS.items()},
            "last_updated": datetime.now().isoformat(),
        }
        with open(RUNTIME_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        logger.debug("Runtime state saved")
    except Exception as e:
        logger.error(f"Could not save runtime state: {e}")


def write_runtime_state(active_chats: List[int]) -> None:
    try:
        state = {
            "active_chats": list(active_chats),
            "last_scores": {str(k): v for k, v in LAST_SCORES.items()},
            "last_rankings": {str(k): v for k, v in LAST_RANKINGS.items()},
            "last_split_rankings": {str(k): v for k, v in LAST_SPLIT_RANKINGS.items()},
            "watch_message_ids": {str(k): v for k, v in WATCH_MESSAGE_IDS.items()},
            "last_updated": datetime.now().isoformat(),
        }
        with open(RUNTIME_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
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
