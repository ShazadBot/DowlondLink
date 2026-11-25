
import os
import re
import time
import sqlite3
import asyncio
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from telethon import TelegramClient
from telethon.sessions import StringSession

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# =====================================
# CONFIGURATION
# =====================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

CHANNEL_1 = "@Shblood_IT"
CHANNEL_2 = "@PS4K2rdish"

CHANNEL_1_URL = "https://t.me/Shblood_IT"
CHANNEL_2_URL = "https://t.me/PS4K2rdish"

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION = os.getenv("SESSION_STRING", "")

MAX_SIZE = 49 * 1024 * 1024
DB = "shblood.db"

user_client = None

# =====================================
# DATABASE
# =====================================

def init_db():
    with sqlite3.connect(DB) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

def save_user(user_id):
    with sqlite3.connect(DB) as db:
        db.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES (?)",
            (user_id,)
        )

def get_users():
    with sqlite3.connect(DB) as db:
        return [
            row[0] for row in
            db.execute("SELECT user_id FROM users")
        ]

# =====================================
# CHANNEL BUTTONS
# =====================================

def join_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 Join Shblood IT",
                url=CHANNEL_1_URL
            )
        ],
        [
            InlineKeyboardButton(
                "📢 Join PS4K2rdish",
                url=CHANNEL_2_URL
            )
        ],
        [
            InlineKeyboardButton(
                "✅ پشکنینەوە",
                callback_data="check_join"
            )
        ]
    ])

# =====================================
# CHANNEL VERIFICATION
# =====================================

async def check_user(bot, user_id):

    channels = [
        CHANNEL_1,
        CHANNEL_2
    ]

    for channel in channels:
        try:
            member = await bot.get_chat_member(
                chat_id=channel,
                user_id=user_id
            )

            status = member.status

            is_joined = (
                status in (
                    "member",
                    "administrator",
                    "creator"
                )
                or (
                    status == "restricted"
                    and getattr(member, "is_member", False)
                )
            )

            if not is_joined:
                return False, None

        except Exception as error:
            print(
                f"CHANNEL CHECK ERROR {channel}: {error}"
            )
            return None, channel

    return True, None

# =====================================
# START
# =====================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    save_user(user.id)

    joined, error = await check_user(
        context.bot,
        user.id
    )

    if error:
        await update.message.reply_text(
            "⚠️ کێشە لە پشکنینی چەناڵەکان هەیە.\n\n"
            "بەڕێوەبەری بۆت دەبێت بۆتەکە Admin بکات "
            "لە هەردوو چەناڵەکە."
        )
        return

    if not joined:
        context.user_data["waiting"] = False

        await update.message.reply_text(
            "👋 بەخێربێیت بۆ Shblood Downloader!\n\n"
            "بۆ بەکارهێنانی بۆتەکە تکایە "
            "جۆینی هەردوو چەناڵەکە بکە:",
            reply_markup=join_keyboard()
        )
        return

    context.user_data["waiting"] = True

    await update.message.reply_text(
        "🔥 بەخێربێیت!\n\n"
        "تکایە لینکی ڤیدیۆی خۆت بنووسە:"
    )

# =====================================
# RECHECK
# =====================================

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    joined, error = await check_user(
        context.bot,
        query.from_user.id
    )

    if error:
        await query.edit_message_text(
            "⚠️ بۆت ناتوانێت ئەندامێتی بپشکنێت.\n\n"
            f"کێشە لە چەناڵ: {error}\n"
            "تکایە Admin ـی بۆتەکە بپشکنە."
        )
        return

    if joined:

        context.user_data["waiting"] = True

        await query.edit_message_text(
            "✅ جۆینەکەت پشتڕاستکرایەوە!\n\n"
            "ئێستا لینکی ڤیدیۆ بنێرە."
        )

    else:

        context.user_data["waiting"] = False

        await query.edit_message_text(
            "❌ هێشتا جۆینی هەردوو چەناڵەکەت نەکردووە.\n"
            "جۆین بکە و دووبارە پشکنینەوە بکە.",
            reply_markup=join_keyboard()
        )

# =====================================
# URL VALIDATION
# =====================================

ALLOWED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "twitter.com",
    "x.com",
    "t.me",
    "telegram.me"
)

def valid_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()

        return (
            parsed.scheme in ("http", "https")
            and any(
                host == domain or host.endswith("." + domain)
                for domain in ALLOWED_DOMAINS
            )
        )
    except Exception:
        return False

# =====================================
# TELEGRAM VIDEO
# =====================================

async def telegram_download(url, folder):

    if not user_client:
        raise Exception("Telegram session is not configured")

    match = re.search(
        r"(?:t\.me|telegram\.me)/(?:s/)?([^/?]+)/(\d+)",
        url
    )

    private_match = re.search(
        r"(?:t\.me|telegram\.me)/c/(\d+)/(\d+)",
        url
    )

    if private_match:
        entity = int("-100" + private_match.group(1))
        message_id = int(private_match.group(2))

    elif match:
        entity = match.group(1)
        message_id = int(match.group(2))

    else:
        raise Exception("Unsupported Telegram link")

    message = await user_client.get_messages(
        entity,
        ids=message_id
    )

    if not message or not message.media:
        raise Exception("Video not found")

    path = await user_client.download_media(
        message,
        file=folder
    )

    if not path:
        raise Exception("Download failed")

    return Path(path)

# =====================================
# SOCIAL MEDIA DOWNLOAD
# =====================================

async def social_download(url, folder):

    options = {
        "format": "best[ext=mp4]/best",
        "outtmpl": str(
            Path(folder) / "Shblood_%(id)s.%(ext)s"
        ),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "retries": 3,
        "fragment_retries": 3,
        "max_filesize": MAX_SIZE,
        "merge_output_format": "mp4"
    }

    def run():
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

    await asyncio.to_thread(run)

    files = list(Path(folder).glob("Shblood_*"))

    if not files:
        raise Exception("Video not found")

    return files[0]

# =====================================
# HANDLE LINKS
# =====================================

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    joined, error = await check_user(
        context.bot,
        user_id
    )

    if error:
        await update.message.reply_text(
            "⚠️ کێشەی پشکنینی چەناڵەکان هەیە."
        )
        return

    if not joined:
        context.user_data["waiting"] = False

        await update.message.reply_text(
            "تکایە جۆینی هەردوو چەناڵ بکە:",
            reply_markup=join_keyboard()
        )
        return

    if not context.user_data.get("waiting"):
        await update.message.reply_text(
            "بۆ دەستپێکردن /start بنووسە."
        )
        return

    url = update.message.text.strip()

    if not valid_url(url):
        await update.message.reply_text(
            "❌ لینکەکە دروست نییە یان پشتگیری ناکرێت."
        )
        return

    context.user_data["waiting"] = False

    waiting = await update.message.reply_text(
        "⏳ چاوەڕێبە...\n"
        "ڤیدیۆکەت ئامادە دەکرێت."
    )

    started = time.monotonic()

    try:
        with tempfile.TemporaryDirectory() as folder:

            host = (urlparse(url).hostname or "").lower()

            if host in ("t.me", "telegram.me"):
                video = await telegram_download(url, folder)
            else:
                video = await social_download(url, folder)

            if not video.exists():
                raise Exception("File missing")

            if video.stat().st_size > MAX_SIZE:
                raise Exception("Video exceeds file limit")

            remaining = 4 - (time.monotonic() - started)

            if remaining > 0:
                await asyncio.sleep(remaining)

            await waiting.edit_text(
                "✅ ڤیدیۆ ئامادەیە!"
            )

            caption = (
                "ShbloodTeam\n\n"
                "ڤیدیۆ هات بەبێ لۆگۆ\n"
                "TeamShblood"
            )

            with open(video, "rb") as file:

                if video.suffix.lower() == ".mp4":
                    await update.message.reply_video(
                        video=file,
                        caption=caption,
                        supports_streaming=True,
                        read_timeout=300,
                        write_timeout=300
                    )
                else:
                    await update.message.reply_document(
                        document=file,
                        caption=caption,
                        read_timeout=300,
                        write_timeout=300
                    )

    except Exception as error:

        print("DOWNLOAD ERROR:", repr(error))

        await waiting.edit_text(
            "❌ دابەزاندنی ڤیدیۆ سەرکەوتوو نەبوو.\n\n"
            "لینکەکە بپشکنە یان لینکێکی تر بنێرە."
        )

    finally:
        context.user_data["waiting"] = True

# =====================================
# ADMIN STATS
# =====================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        f"👥 بەکارهێنەران: {len(get_users())}"
    )

# =====================================
# ADMIN BROADCAST
# =====================================

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    message = " ".join(context.args)

    if not message:
        await update.message.reply_text(
            "بەکارهێنان:\n/broadcast نامەکەت"
        )
        return

    success = 0

    for user_id in get_users():
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message
            )
            success += 1
        except Exception as error:
            print("BROADCAST ERROR:", error)

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        f"✅ نێردرا بۆ {success} بەکارهێنەر."
    )

# =====================================
# TELEGRAM USER SESSION
# =====================================

async def post_init(app):

    global user_client

    if SESSION and API_ID and API_HASH:

        user_client = TelegramClient(
            StringSession(SESSION),
            API_ID,
            API_HASH
        )

        await user_client.start()

        print("Telegram session connected")

async def post_shutdown(app):

    global user_client

    if user_client:
        await user_client.disconnect()

# =====================================
# MAIN
# =====================================

def main():

    init_db()

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))

    app.add_handler(
        CallbackQueryHandler(
            check_join,
            pattern="^check_join$"
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    print("SHBLOOD DOWNLOADER STARTED")

    app.run_polling()

if __name__ == "__main__":
    main()
