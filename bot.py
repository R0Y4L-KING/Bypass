"""
Bypass Bot — link shortener bypass Telegram bot.

Koi bhi short link bhejo, yeh API se bypass karke direct link nikaal deta hai.
API response plain text hota hai, is liye result ko parse kiya jaata hai.
"""

from __future__ import annotations

import html
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --------------------------------------------------------------------- config
BOT_TOKEN = os.environ["BOT_TOKEN"]
API_KEY = os.environ["KEY"]
API_URL = os.environ.get(
    "API_URL", "https://altaf-api-maker.base44.app/functions/lookup"
)
TOOL = os.environ.get("TOOL", "nick-bypass")
TIMEOUT = float(os.environ.get("TIMEOUT", "45"))
BOT_USERNAME = os.environ.get("BOT_USERNAME", "KingBypassRobot")

# Force-subscribe channels: comma separated, @username ya -100... id
# Example: FSUB_CHANNELS=@mychannel,-1001234567890
FSUB_CHANNELS = [
    c.strip()
    for c in os.environ.get("FSUB_CHANNELS", "").split(",")
    if c.strip()
]
FSUB_MSG = os.environ.get(
    "FSUB_MSG",
    "🔒 <b>Pehle humare channel join karo</b>\n\n"
    "Neeche diye buttons se join karo, phir <b>Try Again</b> dabao.",
)

URL_RE = re.compile(r"https?://[^\s\"'<>]+")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
log = logging.getLogger("bypass-bot")

# chat_id -> (title, join_url) cache, taaki baar baar get_chat na karna pade
_CHAT_CACHE: dict[str, tuple[str, Optional[str]]] = {}


# --------------------------------------------------------------------- api
async def call_api(link: str) -> dict:
    """API ko call karke JSON response lauta do. Fail hone pe exception."""
    params = {"tool": TOOL, "key": API_KEY, "q": link}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(API_URL, params=params)

    if resp.status_code != 200:
        raise RuntimeError(f"API HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError("API ne JSON ke bajaye kuch aur bheja") from None

    if not data.get("success"):
        raise RuntimeError(data.get("notice") or "API returned success=false")

    return data


def pick_url(text: str, label: str) -> Optional[str]:
    """
    `label` wali line se URL nikaalo (jaise "Bypassed Link").
    Na mile to result ka aakhri URL lauta do.
    """
    for line in text.splitlines():
        if label in line.lower():
            match = URL_RE.search(line)
            if match:
                return match.group(0).rstrip("─—–- ")

    urls = URL_RE.findall(text)
    return urls[-1].rstrip("─—–- ") if urls else None


# --------------------------------------------------------------------- force sub
async def missing_channels(bot, user_id: int) -> list[str]:
    """Woh channels lauta do jo user ne join nahi kiye."""
    if not FSUB_CHANNELS:
        return []

    missing: list[str] = []
    for chat_id in FSUB_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ("left", "kicked"):
                missing.append(chat_id)
        except Exception as exc:  # noqa: BLE001
            # Bot us channel me admin nahi hai, ya channel id galat hai.
            # User ko block na karo, bas log kar do.
            log.warning("get_chat_member failed for %s: %s", chat_id, exc)
    return missing


async def channel_button(bot, chat_id: str) -> InlineKeyboardButton:
    """Channel ka title + join link nikaalo (cached)."""
    cached = _CHAT_CACHE.get(chat_id)
    if cached is None:
        title, url = chat_id, None
        try:
            chat = await bot.get_chat(chat_id)
            title = chat.title or chat_id
            if chat.invite_link:
                url = chat.invite_link
            elif chat.username:
                url = f"https://t.me/{chat.username}"
        except Exception as exc:  # noqa: BLE001
            log.warning("get_chat failed for %s: %s", chat_id, exc)

        cached = (title, url)
        _CHAT_CACHE[chat_id] = cached

    title, url = cached
    if url:
        return InlineKeyboardButton(f"📢 {title}", url=url)
    return InlineKeyboardButton(f"📢 {title}", callback_data="fsub_noop")


async def send_force_sub(bot, chat_id: int, missing: list[str]) -> None:
    rows = [[await channel_button(bot, ch)] for ch in missing]
    rows.append([InlineKeyboardButton("🔄 Try Again", callback_data="fsub_retry")])

    await bot.send_message(
        chat_id=chat_id,
        text=FSUB_MSG,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def is_joined(bot, user_id: int, chat_id: int) -> bool:
    """True agar user sab channels me hai, warna force-sub message bhej ke False."""
    missing = await missing_channels(bot, user_id)
    if not missing:
        return True
    await send_force_sub(bot, chat_id, missing)
    return False


# --------------------------------------------------------------------- handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message

    if user and not await is_joined(context.bot, user.id, message.chat_id):
        return

    await message.reply_text(
        "👋 <b>Bypass Bot</b>\n\n"
        "Mujhe koi bhi short link bhejo, main uska direct link nikaal dunga.\n\n"
        "<b>Example</b>\n"
        "<code>https://link.vipshort.in/I9xA</code>\n\n"
        f"<i>Powered by @{BOT_USERNAME}</i>",
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message

    if user and not await is_joined(context.bot, user.id, message.chat_id):
        return

    await message.reply_text(
        "<b>Kaise use karein</b>\n\n"
        "1. Koi bhi short link copy karo\n"
        "2. Is bot ko bhejo\n"
        "3. Direct link mil jayega\n\n"
        "<b>Commands</b>\n"
        "/start — welcome\n"
        "/help — yeh message\n\n"
        "<i>Sirf http:// ya https:// wale links chalte hain.</i>",
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None:
        return

    if user and not await is_joined(context.bot, user.id, message.chat_id):
        return

    text = message.text or ""
    match = URL_RE.search(text)
    if not match:
        await message.reply_text(
            "❌ Koi valid link nahi mila.\n"
            "Link <code>http://</code> ya <code>https://</code> se shuru hona chahiye.",
            parse_mode=ParseMode.HTML,
        )
        return

    link = match.group(0)
    status = await message.reply_text("🔗 Bypassing…")
    started = time.perf_counter()

    try:
        data = await call_api(link)
    except Exception as exc:  # noqa: BLE001
        log.exception("bypass failed for %s", link)
        await status.edit_text(
            "❌ Bypass fail ho gaya.\n"
            f"<code>{html.escape(str(exc)[:300])}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    result_text = data.get("result") or ""
    bypassed = pick_url(result_text, "bypassed link")
    elapsed = time.perf_counter() - started

    if not bypassed:
        await status.edit_text(
            "❌ Bypassed link nahi mila.\n\n"
            f"<pre>{html.escape(result_text[:3000])}</pre>",
            parse_mode=ParseMode.HTML,
        )
        return

    credits = data.get("credits") or {}
    used = credits.get("used", "?")

    await status.edit_text(
        "<b>Original Link</b>\n"
        f"<code>{html.escape(link)}</code>\n\n"
        "<b>Bypassed Link</b>\n"
        f"<code>{html.escape(bypassed)}</code>\n\n"
        f"⏱ {elapsed:.1f}s\n"
        f"💳 Credits used: {used}\n"
        f"<i>Powered by @{BOT_USERNAME}</i>",
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def fsub_retry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """'Try Again' button — membership dobara check karo."""
    query = update.callback_query
    user = query.from_user

    missing = await missing_channels(context.bot, user.id)
    if missing:
        await query.answer("❌ Abhi bhi join nahi kiya!", show_alert=True)
        return

    await query.answer("✅ Verified!")
    await query.message.edit_text(
        "✅ Verification ho gaya!\n\n"
        "Ab koi bhi short link bhejo, bypass kar dunga.",
        parse_mode=ParseMode.HTML,
    )


async def fsub_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Jis channel ka invite link nahi mila, us button ke liye."""
    await update.callback_query.answer(
        "Is channel ka link nahi mila. Bot ko channel me admin banao.", show_alert=True
    )


# --------------------------------------------------------------------- health
class _HealthHandler(BaseHTTPRequestHandler):
    """Render (aur baaki PaaS) ko ek open port chahiye hota hai."""

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args) -> None:
        pass


def start_health_server() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("health server listening on :%s", port)


# --------------------------------------------------------------------- main
def main() -> None:
    start_health_server()

    if FSUB_CHANNELS:
        log.info("force-sub channels: %s", ", ".join(FSUB_CHANNELS))
    else:
        log.info("force-sub disabled (FSUB_CHANNELS khali hai)")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(fsub_retry, pattern="^fsub_retry$"))
    app.add_handler(CallbackQueryHandler(fsub_noop, pattern="^fsub_noop$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    log.info("bot starting (long polling)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
