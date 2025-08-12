from __future__ import annotations

import asyncio
from telegram import BotCommand, BotCommandScopeAllPrivateChats
from telegram.ext import Application, CommandHandler
from telegram.request import HTTPXRequest

from .config import BOT_TOKEN, X_SESSION_TOKEN, logger
from .storage import (
    load_group_settings,
    load_runtime_state,
    get_active_chats_to_resume,
    get_group_league,
)
from .watchers import WATCHERS, watch_loop, FIRST_POLL_AFTER_RESUME
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


async def startup_health_check():
    """Perform health check on bot startup"""
    from .config import BASE, X_SESSION_TOKEN, logger
    from .http import make_session, fetch_json
    
    logger.info("🏥 Running startup health check...")
    
    try:
        # Test LTA Fantasy authentication
        async with make_session() as session:
            user_data = await fetch_json(session, f'{BASE}/users/me')
            
            if user_data and 'data' in user_data:
                user_info = user_data['data']
                display_name = user_info.get('riotGameName', 'Unknown')
                tag_line = user_info.get('riotTagLine', 'Unknown')
                
                logger.info(f"✅ Authenticated as: {display_name}#{tag_line}")
                logger.info("✅ LTA Fantasy API authentication successful")
                return True
            else:
                logger.error("❌ Invalid response from /users/me endpoint")
                return False
                
    except Exception as e:
        error_msg = str(e)
        if '401' in error_msg or 'Unauthorized' in error_msg:
            logger.error("❌ LTA Authentication failed - Session token invalid or expired")
            logger.error("Use /auth <token> command to update your session token")
        elif '404' in error_msg:
            logger.error("❌ /users/me endpoint not found - Check worker configuration")
        else:
            logger.error(f"❌ LTA API health check failed: {error_msg}")
        return False


def main():
    load_group_settings()
    load_runtime_state()

    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN not set. Check your .env file.")

    # Configure request with longer timeout to prevent startup failures
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    
    app = Application.builder().token(BOT_TOKEN).request(request).build()

    private_commands = [
        BotCommand("start", "Show help and available commands"),
        BotCommand("scores", "Get standings for a specific league"),
        BotCommand("team", "Get detailed team information"),
        BotCommand("owner", "Find team by owner name"),
        BotCommand("watch", "Monitor a specific league for updates"),
        BotCommand("unwatch", "Stop monitoring"),
        BotCommand("auth", "Update session token"),
    ]

    group_commands = [
        BotCommand("start", "Show help and available commands"),
        BotCommand("scores", "Get standings for group's league"),
        BotCommand("team", "Get detailed team information"),
        BotCommand("owner", "Find team by owner name"),
        BotCommand("setleague", "Attach a league to this group"),
        BotCommand("getleague", "Show current attached league"),
        BotCommand("startwatch", "Start monitoring group's league"),
        BotCommand("stopwatch", "Stop monitoring"),
    ]

    async def resume_watchers(application: Application) -> None:
        chats_to_resume = get_active_chats_to_resume()
        if not chats_to_resume:
            return
        for chat_id in chats_to_resume:
            league = get_group_league(chat_id)
            if not league:
                continue
            stop_event = asyncio.Event()
            async def runner():
                await watch_loop(chat_id, league, application.bot, stop_event)
            FIRST_POLL_AFTER_RESUME[chat_id] = True
            WATCHERS[chat_id] = asyncio.create_task(runner())

    async def post_init(application: Application) -> None:
        try:
            logger.info("🔧 Setting up bot commands...")
            await application.bot.set_my_commands(group_commands)
            await application.bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
            logger.info("✅ Bot commands configured successfully")
        except Exception as e:
            logger.error(f"❌ Failed to set bot commands: {e}")
            logger.warning("⚠️ Bot will continue but commands may not be visible in Telegram")
        
        await asyncio.sleep(2)
        await resume_watchers(application)

    app.post_init = post_init

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("scores", scores_cmd))
    app.add_handler(CommandHandler("team", team_cmd))
    app.add_handler(CommandHandler("owner", owner_cmd))
    app.add_handler(CommandHandler("setleague", setleague_cmd))
    app.add_handler(CommandHandler("getleague", getleague_cmd))
    app.add_handler(CommandHandler("startwatch", startwatch_cmd))
    app.add_handler(CommandHandler("stopwatch", stopwatch_cmd))
    app.add_handler(CommandHandler("watch", watch_cmd))
    app.add_handler(CommandHandler("unwatch", unwatch_cmd))
    app.add_handler(CommandHandler("auth", auth_cmd))

    app.run_polling(drop_pending_updates=True)
