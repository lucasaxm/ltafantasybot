from __future__ import annotations

import asyncio
from telegram import BotCommand, BotCommandScopeAllPrivateChats
from telegram.ext import Application, CommandHandler

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
    # Defer detailed health check to legacy bot for simplicity; export stub here
    return True


def main():
    load_group_settings()
    load_runtime_state()

    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN not set. Check your .env file.")

    app = Application.builder().token(BOT_TOKEN).build()

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
        await application.bot.set_my_commands(group_commands)
        await application.bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
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
