

import os
import time
import asyncio
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

WELCOME = (
    "سڵاو! بەخێربێیت بۆ Shblood Downloader\n\n"
    "تکایە لینکی سۆشیاڵ میدیای خۆت بنووسە:"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting"] = True
    await update.message.reply_text(WELCOME)


async def download_video(url, folder):
    options = {
        "format": "best[ext=mp4]/best",
        "outtmpl": str(Path(folder) / "Shblood_%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 25,
        "retries": 2,
        "max_filesize": 49 * 1024 * 1024,
    }

    def run():
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

    await asyncio.to_thread(run)

    files = list(Path(folder).glob("Shblood_*"))
    return files[0] if files else None


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("waiting"):
        await update.message.reply_text(
            "بۆ دەستپێکردن /start بنووسە."
        )
        return

    url = update.message.text.strip()

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        await update.message.reply_text(
            "لینکەکە دروست نییە. تکایە لینکێکی دروست بنێرە."
        )
        return

    context.user_data["waiting"] = False

    waiting_message = await update.message.reply_text(
        "⏳ چاوەڕێبە... ڤیدیۆکەت پشکنین و ئامادە دەکرێت."
    )

    started = time.monotonic()

    try:
        with tempfile.TemporaryDirectory() as folder:

            video = await download_video(url, folder)

            if not video:
                raise Exception("Video not found")

            remaining = 4 - (time.monotonic() - started)

            if remaining > 0:
                await asyncio.sleep(remaining)

            await waiting_message.edit_text(
                "✅ ڤیدیۆ ئامادەیە!"
            )

            caption = "ShbloodTeam"

            with open(video, "rb") as file:

                if video.suffix.lower() == ".mp4":
                    await update.message.reply_video(
                        video=file,
                        caption=caption,
                        supports_streaming=True
                    )
                else:
                    await update.message.reply_document(
                        document=file,
                        caption=caption
                    )

            await update.message.reply_text(
                "ڤیدیۆ هات بەبێ لۆگۆ\n\n"
                "TeamShblood"
            )

    except Exception:
        await waiting_message.edit_text(
            "❌ دابەزاندنی ڤیدیۆ سەرکەوتوو نەبوو.\n"
            "لینکەکە بپشکنە یان لینکێکی تر بنێرە."
        )

    finally:
        context.user_data["waiting"] = True


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)
    )

    print("Shblood Downloader is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
