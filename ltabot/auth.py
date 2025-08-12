from __future__ import annotations

from telegram import Update, ChatMember
from telegram.ext import ContextTypes

from .config import ALLOWED_USER_ID


async def is_group_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False


async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False


async def is_authorized_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_user or not update.effective_chat:
        return False
    user_id = update.effective_user.id
    chat = update.effective_chat
    if chat.type == "private":
        return user_id == ALLOWED_USER_ID
    if chat.type in ["group", "supergroup"]:
        return await is_group_admin(update, context)
    return False


async def is_authorized_read(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_user or not update.effective_chat:
        return False
    user_id = update.effective_user.id
    chat = update.effective_chat
    if chat.type == "private":
        return user_id == ALLOWED_USER_ID
    if chat.type in ["group", "supergroup"]:
        return await is_group_member(update, context)
    return False


async def guard_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not await is_authorized_admin(update, context):
        if update.effective_chat and update.effective_chat.type == "private":
            await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")
        return False
    return True


async def guard_read(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not await is_authorized_read(update, context):
        if update.effective_chat and update.effective_chat.type == "private":
            await context.bot.send_message(update.effective_chat.id, "❌ Not authorized.")
        return False
    return True
