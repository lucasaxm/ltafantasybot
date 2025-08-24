"""
Champion ID to Name mapping module using Riot Data Dragon API.

This module provides functionality to map League of Legends champion IDs 
to their human-readable names using Riot's official Data Dragon API.
"""

import aiohttp
import logging
import os
from typing import Dict, Optional
from functools import wraps
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Champion Configuration
CHAMPION_API_URL = os.getenv("CHAMPION_API_URL", "https://ddragon.leagueoflegends.com/cdn/15.16.1/data/en_US/champion.json")
CHAMPION_CACHE_TTL = int(os.getenv("CHAMPION_CACHE_TTL", "86400"))  # 24 hours default
CHAMPION_API_TIMEOUT = int(os.getenv("CHAMPION_API_TIMEOUT", "10"))  # 10 seconds default

# Champion-specific cache with long TTL (follows same pattern as config.py but with longer TTL)
champion_cache = TTLCache(maxsize=10, ttl=CHAMPION_CACHE_TTL)

def cached_champion_call(cache_key_func):
    """
    Decorator for caching champion API calls with long TTL.
    Follows the same pattern as the LTA API caching but with longer TTL for champion data.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            key = cache_key_func(*args, **kwargs)
            
            # Check cache first
            if key in champion_cache:
                logger.debug(f"Champion cache hit for: {key}")
                return champion_cache[key]
            
            # Call original function
            logger.debug(f"Champion cache miss, calling API for: {key}")
            result = await func(*args, **kwargs)
            
            # Store in cache
            champion_cache[key] = result
            logger.debug(f"Cached champion result for: {key}")
            return result
        return wrapper
    return decorator

@cached_champion_call(lambda: "champion_data")
async def load_champion_data() -> Dict[str, str]:
    """
    Load champion data from Riot Data Dragon API with long TTL caching.
    
    Returns:
        Dict mapping champion IDs (as strings) to champion names
    """
    try:
        timeout = aiohttp.ClientTimeout(total=CHAMPION_API_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            logger.debug(f"Fetching champion data from: {CHAMPION_API_URL}")
            async with session.get(CHAMPION_API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Build mapping from champion ID to name
                    champion_mapping = {}
                    for champion_key, champion_info in data['data'].items():
                        champion_id = str(champion_info['key'])  # Convert to string for consistency
                        champion_name = champion_info['name']
                        champion_mapping[champion_id] = champion_name
                    
                    logger.info(f"✅ Loaded {len(champion_mapping)} champions from Riot Data Dragon (cached for {CHAMPION_CACHE_TTL//3600}h)")
                    return champion_mapping
                else:
                    logger.error(f"Failed to fetch champion data: HTTP {response.status}")
                    return {}
                    
    except Exception as e:
        logger.error(f"Error loading champion data: {e}")
        return {}

async def get_champion_name(champion_id: int) -> str:
    """
    Get champion name by ID.
    
    Args:
        champion_id: The champion ID to lookup
        
    Returns:
        Champion name or "Champion {id}" if not found
    """
    champion_data = await load_champion_data()
    
    if not champion_data:
        return f"Champion {champion_id}"
    
    champion_id_str = str(champion_id)
    return champion_data.get(champion_id_str, f"Champion {champion_id}")

async def ensure_champion_data_loaded() -> bool:
    """
    Ensure champion data is loaded. Called by commands that need champion names.
    
    Returns:
        True if data is loaded successfully, False otherwise
    """
    champion_data = await load_champion_data()
    return champion_data is not None and len(champion_data) > 0
