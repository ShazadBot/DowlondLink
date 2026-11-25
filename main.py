
import os
import re
import time
import sqlite3
import logging
import asyncio
import tempfile
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError

import yt_dlp
from telethon import TelegramClient
from telethon.sessions import StringSession


# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")

CHANNEL_1 = "@Shblood_IT"
CHANNEL_2 = "@PS4K2rdish"

CHANNEL_1_URL = "https://t.me/Shblood_IT"
CHANNEL_2_URL = "https://t.me/PS4K2rdish"

MAX_SIZE = 49 * 1024 * 1024

DB_NAME = "shblood_users.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("ShbloodDownloader")


# ================= DATABASE =================

def init_db():
    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        """)


def add_user(user_id):
    with sqlite3.connect(DB_NAME) as db:
        db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,)
        )


def get_users():
    with sqlite3.connect(DB_NAME) as db:
        return [
            row[0]
            for row in db.execute("SELECT user_id FROM users").fetchall()
        ]


# ================= KEYBOARDS =================

def join_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Channel 1",
                url=CHANNEL_1_URL
            )
        ],
        [
            InlineKeyboardButton(
                "Channel 2",
                url=CHANNEL_2_URL
            )
        ],
        [
            InlineKeyboardButton(
                "پشکنینەوە",
                callback_data="check_join"
            )
        ]
    ])


# ================= MEMBERSHIP =================

async def check_user(bot, user_id):
    for channel in (CHANNEL_1, CHANNEL_2):
        try:
            member = await bot.get_chat_member(
                chat_id=channel,
                user_id=user_id
            )

            if member.status in (
                ChatMemberStatus.LEFT,
                ChatMemberStatus.BANNED
            ):
                return False

            if (
                member.status == ChatMemberStatus.RESTRICTED
                and not getattr(member, "is_member", False)
            ):
                return False

        except TelegramError:
            logger.exception(
                "Membership check failed for %s",
                channel
            )
            return None

    return True


async def require_join(update, context):
    user_id = update.effective_user.id

    result = await check_user(
        context.bot,
        user_id
    )

    if result is True:
        add_user(user_id)
        return True

    if update.callback_query:
        await update.callback_query.edit_message_text(
            "تکایە سەردانی هەردوو چەناڵ بکە و پاشان پشکنینەوە بکە:",
            reply_markup=join_keyboard()
        )
    else:
        await update.effective_message.reply_text(
            "تکایە جۆینی هەردوو چەناڵ بکە:",
            reply_markup=join_keyboard()
        )

    return False


# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update, context):
        return

    await update.message.reply_text(
        "سڵاو! بەخێربێیت بۆ Shblood Downloader.\n\n"
        "تکایە لینکی ڤیدیۆی سۆشیاڵ میدیا بنێرە."
    )


# ================= RECHECK =================

async def check_join_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    result = await check_user(
        context.bot,
        query.from_user.id
    )

    if result is True:
        add_user(query.from_user.id)

        await query.edit_message_text(
            "جۆینەکەت پشتڕاست کرایەوە!\n\n"
            "ئێستا لینکی ڤیدیۆکە بنێرە."
        )
    else:
        await query.edit_message_text(
            "تکایە جۆینی هەردوو چەناڵ بکە:",
            reply_markup=join_keyboard()
        )


# ================= DOWNLOAD =================

def is_valid_url(url):
    return bool(
        re.match(
            r"^https?://",
            url.strip(),
            re.IGNORECASE
        )
    )


def download_with_ytdlp(url, folder):
    output = os.path.join(folder, "%(title).80s.%(ext)s")

    options = {
        "format": "best[ext=mp4]/best",
        "outtmpl": output,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_SIZE,
        "merge_output_format": "mp4",
        "socket_timeout": 30,
        "retries": 2,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)

        if not os.path.exists(file_path):
            mp4_path = os.path.splitext(file_path)[0] + ".mp4"
            if os.path.exists(mp4_path):
                file_path = mp4_path

        if not os.path.exists(file_path):
            raise Exception("Downloaded file not found")

        if os.path.getsize(file_path) > MAX_SIZE:
            raise Exception("File is too large")

        return file_path, info.get("title", "Video")


# ================= TELEGRAM DOWNLOAD =================

async def download_telegram_video(url, folder):
    if not all([API_ID, API_HASH, SESSION_STRING]):
        raise Exception(
            "Telegram API settings are missing"
        )

    client = TelegramClient(
        StringSession(SESSION_STRING),
        API_ID,
        API_HASH
    )

    await client.connect()

    try:
        match = re.search(
            r"t\.me/(?:c/)?([^/?]+)/(\d+)",
            url
        )

        if not match:
            raise Exception("Invalid Telegram post link")

        channel_name = match.group(1)
        message_id = int(match.group(2))

        if channel_name.isdigit():
            channel_name = int("-100" + channel_name)

        entity = await client.get_entity(channel_name)
        message = await client.get_messages(
            entity,
            ids=message_id
        )

        if not message or not message.media:
            raise Exception("No media found")

        file_path = os.path.join(folder, "telegram_video.mp4")

        await client.download_media(
            message,
            file=file_path
        )

        if not os.path.exists(file_path):
            raise Exception("Download failed")

        if os.path.getsize(file_path) > MAX_SIZE:
            raise Exception("File is too large")

        return file_path, "Telegram Video"

    finally:
        await client.disconnect()


# ================= VIDEO HANDLER =================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await require_join(update, context):
        return

    url = update.message.text.strip()

    if not is_valid_url(url):
        await update.message.reply_text(
            "تکایە لینکێکی دروست بنێرە."
        )
        return

    status = await update.message.reply_text(
        "چاوەڕێبە... ڤیدیۆکە پشکنین و داگیراوە."
    )

    folder = tempfile.mkdtemp(prefix="shblood_")

    try:
        await asyncio.sleep(3)

        if "t.me/" in url:
            file_path, title = await download_telegram_video(
                url,
                folder
            )
        else:
            file_path, title = await asyncio.to_thread(
                download_with_ytdlp,
                url,
                folder
            )

        await status.edit_text(
            "ڤیدیۆ ئامادەیە!"
        )

        with open(file_path, "rb") as video:
            await update.message.reply_video(
                video=video,
                caption=(
                    f"{title[:700]}\n\n"
                    "ڤیدیۆ هات بەبێ لۆگۆ\n"
                    "ShbloodTeam"
                ),
                supports_streaming=True
            )

        await status.delete()

    except Exception as error:
        logger.exception("Download failed")

        await status.edit_text(
            "داگرتنی ڤیدیۆکە سەرکەوتوو نەبوو.\n"
            "تکایە لینکێکی تر تاقی بکەرەوە."
        )

    finally:
        for file in Path(folder).glob("*"):
            try:
                file.unlink()
            except OSError:
                pass

        try:
            Path(folder).rmdir()
        except OSError:
            pass


# ================= ADMIN =================

def is_admin(user_id):
    return user_id == ADMIN_ID and ADMIN_ID != 0


async def stats(update, context):
    if not is_admin(update.effective_user.id):
        return

    users = get_users()

    await update.message.reply_text(
        f"ئاماری Shblood Downloader\n\n"
        f"کۆی بەکارهێنەران: {len(users)}"
    )


async def broadcast(update, context):
    if not is_admin(update.effective_user.id):
        return

    message = " ".join(context.args)

    if not message:
        await update.message.reply_text(
            "بەکارهێنان:\n/broadcast پەیامەکەت"
        )
        return

    users = get_users()
    success = 0
    failed = 0

    status = await update.message.reply_text(
        "ناردنی پەیامەکان دەستی پێکرد..."
    )

    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message
            )
            success += 1
        except TelegramError:
            failed += 1

        await asyncio.sleep(0.05)

    await status.edit_text(
        f"تەواو بوو!\n\n"
        f"سەرکەوتوو: {success}\n"
        f"سەرنەکەوتوو: {failed}"
    )


async def update_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    message = " ".join(context.args)

    if not message:
        await update.message.reply_text(
            "بەکارهێنان:\n/update پەیامی نوێ"
        )
        return

    users = get_users()

    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "ئاگادارکردنەوەی نوێی Shblood\n\n"
                    + message
                )
            )
        except TelegramError:
            pass

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        "ئاگادارکردنەوەکە نێردرا."
    )


# ================= ERRORS =================

async def error_handler(update, context):
    logger.exception(
        "Bot error:",
        exc_info=context.error
    )


# ================= MAIN =================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing"
        )

    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("update", update_command))

    app.add_handler(
        CallbackQueryHandler(
            check_join_callback,
            pattern="^check_join$"
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    app.add_error_handler(error_handler)

    logger.info("Shblood Downloader started")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
