from __future__ import annotations

import asyncio
import aiohttp
from typing import Any, Dict
from .config import X_SESSION_TOKEN, logger


CURRENT_TOKEN: Dict[str, str] = {"x_session_token": X_SESSION_TOKEN}


def build_headers() -> Dict[str, str]:
    token = CURRENT_TOKEN.get("x_session_token") or ""
    h = {
        "accept": "*/*",
        "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        # Bruno's UA works around Cloudflare
        "user-agent": "bruno-runtime/2.9.0",
        "origin": "https://ltafantasy.com",
        "referer": "https://ltafantasy.com/",
        "pragma": "no-cache",
        "cache-control": "no-cache",
        "dnt": "1",
    }
    if token:
        h["x-session-token"] = token
    return h


def make_session() -> aiohttp.ClientSession:
    timeout = aiohttp.ClientTimeout(total=25)
    return aiohttp.ClientSession(
        timeout=timeout,
        headers=build_headers(),
        trust_env=True,
    )


async def fetch_json(session: aiohttp.ClientSession, url: str, params: Dict[str, str] | None = None) -> Any:
    """Fetch JSON from API with automatic retry on 5xx errors."""
    max_retries = 3
    base_delay = 1.0  # seconds
    
    for attempt in range(max_retries):
        try:
            logger.debug(f"API request: {url}" + (f" (attempt {attempt + 1}/{max_retries})" if attempt > 0 else ""))
            async with session.get(url, params=params) as r:
                if r.status in (401, 403):
                    txt = await r.text()
                    error_msg = f"Auth failed ({r.status}). Update token with /auth <token>. Body: {txt[:180]}"
                    logger.warning(f"API auth failure for {url}: {r.status}")
                    raise PermissionError(error_msg)
                
                if r.status >= 500:
                    # Server error - retry with exponential backoff
                    txt = await r.text()
                    error_msg = f"HTTP {r.status} for {url} :: {txt[:300]}"
                    
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                        logger.warning(f"API 5xx error for {url}: {r.status}, retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        # Last attempt failed
                        logger.error(f"API error for {url} after {max_retries} attempts: {r.status}")
                        raise RuntimeError(error_msg)
                
                if r.status != 200:
                    # 4xx errors (except auth) - don't retry
                    txt = await r.text()
                    error_msg = f"HTTP {r.status} for {url} :: {txt[:300]}"
                    logger.error(f"API error for {url}: {r.status}")
                    raise RuntimeError(error_msg)
                
                logger.debug(f"API success: {url}")
                return await r.json()
        
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # Network errors - retry
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Network error for {url}: {e}, retrying in {delay}s...")
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(f"Network error for {url} after {max_retries} attempts: {e}")
                raise RuntimeError(f"Network error for {url}: {e}")
    
    # Should never reach here, but just in case
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts")
