"""
Helper functions for managing reminder schedules in runtime state.

This module provides utilities to properly handle reminder scheduling
that survives bot restarts by persisting timestamps instead of just flags.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from .config import logger


# Constants
UTC_SUFFIX = '+00:00'


def create_reminder_schedule(
    round_id: str,
    league_slug: str,  
    market_closes_at: str
) -> Dict[str, Any]:
    """
    Create a complete reminder schedule for a round.
    
    Args:
        round_id: The round ID
        league_slug: The league slug
        market_closes_at: ISO format UTC datetime string when market closes
        
    Returns:
        Dictionary with complete schedule including calculated reminder times
    """
    try:
        close_time = datetime.fromisoformat(market_closes_at.replace('Z', UTC_SUFFIX))
        
        return {
            "round_id": round_id,
            "league_slug": league_slug,
            "market_closes_at": market_closes_at,
            "reminder_24h_at": (close_time - timedelta(hours=24)).isoformat(),
            "reminder_1h_at": (close_time - timedelta(hours=1)).isoformat(),
            "flags": {
                "market_open_sent": False,
                "reminder_24h_sent": False,
                "reminder_1h_sent": False,
                "closed_transition_triggered": False
            }
        }
    except Exception as e:
        logger.error(f"Failed to create reminder schedule for {round_id}: {e}")
        return {}


def get_pending_reminders(reminder_schedule: Dict[str, Any], current_time: datetime) -> Dict[str, bool]:
    """
    Determine which reminders should be sent now based on current time.
    
    Args:
        reminder_schedule: The schedule dict for a specific round
        current_time: Current UTC datetime
        
    Returns:
        Dict with keys like "reminder_24h_due", "reminder_1h_due", "market_close_due"
    """
    if not reminder_schedule:
        return {}
        
    try:
        flags = reminder_schedule.get("flags", {})
        
        reminder_24h_time = datetime.fromisoformat(reminder_schedule["reminder_24h_at"])
        reminder_1h_time = datetime.fromisoformat(reminder_schedule["reminder_1h_at"])
        market_close_time = datetime.fromisoformat(reminder_schedule["market_closes_at"].replace('Z', UTC_SUFFIX))
        
        return {
            "reminder_24h_due": (
                current_time >= reminder_24h_time and 
                not flags.get("reminder_24h_sent", False)
            ),
            "reminder_1h_due": (
                current_time >= reminder_1h_time and 
                not flags.get("reminder_1h_sent", False)
            ),
            "market_close_due": (
                current_time >= market_close_time and 
                not flags.get("closed_transition_triggered", False)
            )
        }
    except Exception as e:
        logger.error(f"Failed to check pending reminders: {e}")
        return {}


def mark_reminder_sent(reminder_schedule: Dict[str, Any], reminder_type: str) -> None:
    """
    Mark a specific reminder as sent.
    
    Args:
        reminder_schedule: The schedule dict to update
        reminder_type: One of "market_open", "reminder_24h", "reminder_1h", "closed_transition"
    """
    if "flags" not in reminder_schedule:
        reminder_schedule["flags"] = {}
        
    flag_key = f"{reminder_type}_sent" if reminder_type != "closed_transition" else "closed_transition_triggered"
    reminder_schedule["flags"][flag_key] = True
    
    logger.debug(f"Marked {reminder_type} as sent for round {reminder_schedule.get('round_id', 'unknown')}")


def get_next_reminder_time(reminder_schedule: Dict[str, Any]) -> Optional[datetime]:
    """
    Get the next reminder time that hasn't been sent yet.
    
    Args:
        reminder_schedule: The schedule dict
        
    Returns:
        Next datetime to schedule a task for, or None if no pending reminders
    """
    if not reminder_schedule:
        return None
        
    try:
        flags = reminder_schedule.get("flags", {})
        
        # Check reminders in chronological order
        if not flags.get("reminder_24h_sent", False):
            return datetime.fromisoformat(reminder_schedule["reminder_24h_at"])
        elif not flags.get("reminder_1h_sent", False):
            return datetime.fromisoformat(reminder_schedule["reminder_1h_at"])
        elif not flags.get("closed_transition_triggered", False):
            return datetime.fromisoformat(reminder_schedule["market_closes_at"].replace('Z', UTC_SUFFIX))
            
        return None
    except Exception as e:
        logger.error(f"Failed to get next reminder time: {e}")
        return None


def should_cleanup_schedule(reminder_schedule: Dict[str, Any], current_time: datetime) -> bool:
    """
    Determine if a reminder schedule can be cleaned up (all reminders sent and market closed).
    
    Args:
        reminder_schedule: The schedule dict
        current_time: Current UTC datetime
        
    Returns:
        True if the schedule can be cleaned up
    """
    if not reminder_schedule:
        return True
        
    try:
        flags = reminder_schedule.get("flags", {})
        market_close_time = datetime.fromisoformat(reminder_schedule["market_closes_at"].replace('Z', UTC_SUFFIX))
        
        # Can cleanup if market has closed and all reminders were sent
        return (
            current_time > market_close_time and
            flags.get("market_open_sent", False) and
            flags.get("reminder_24h_sent", False) and
            flags.get("reminder_1h_sent", False) and
            flags.get("closed_transition_triggered", False)
        )
    except Exception as e:
        logger.error(f"Failed to check cleanup status: {e}")
        return False
