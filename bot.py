"""
Bypass Bot — link shortener bypass Telegram bot.

Koi bhi short link bhejo, yeh API se bypass karke direct link nikaal deta hai.
API response plain text hota hai, is liye result ko parse kiya jaata hai.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qsl

import httpx
from telegram import (
    InlineKeyboardButton,
    ReactionTypeEmoji,
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
TOOL = os.environ.get("TOOL", "nick-bypass")
TIMEOUT = float((os.environ.get("TIMEOUT") or "45").strip() or "45")

# Agar API_URL me galti se poora URL with query paste ho gaya ho
# (jaise ...lookup?tool=nick-bypass&key=xxx&q=), to usko saaf kar dete hain.
_raw_url = os.environ.get(
    "API_URL", "https://altaf-api-maker.base44.app/functions/lookup"
).strip()
if "?" in _raw_url:
    _base, _qs = _raw_url.split("?", 1)
    _q = dict(parse_qsl(_qs))
    API_URL = _base.rstrip("/")
    API_KEY = _q.get("key", API_KEY)
    TOOL = _q.get("tool", TOOL)
else:
    API_URL = _raw_url.rstrip("/")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "KingBypassRobot")

# Messages ke neeche credit
CREDIT = os.environ.get("CREDIT", "ModAppsKing")

# Result message kitne second baad delete ho (0 = kabhi nahi)
def _int_env(name: str, default: int) -> int:
    """Env se int padho; khali/galat value ho to default."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        # logging isse pehle set nahi hoti, is liye print
        print(f"[warn] {name}={raw!r} invalid, using default {default}")
        return default


AUTO_DELETE = _int_env("AUTO_DELETE", 60)

# User ka bheja hua link message bhi delete karna hai? (chat saaf rahe)
DELETE_USER_MSG = (os.environ.get("DELETE_USER_MSG") or "1").strip() not in ("0", "false", "False")

# /start ka thumbnail (khali karo to bina photo ke)
START_PIC = os.environ.get(
    "START_PIC",
    "https://raw.githubusercontent.com/R0Y4L-KING/Bypass/main/assets/fsub-banner.jpg",
).strip()

# Message reactions — khali string daalo to us step pe reaction nahi lagega
REACT_EVERY = os.environ.get("REACT_EVERY", "👀")   # har message pe
REACT_START = os.environ.get("REACT_START", "⚡")
REACT_OK = os.environ.get("REACT_OK", "🔥")
REACT_FAIL = os.environ.get("REACT_FAIL", "😢")

# Force-subscribe channels: comma separated, @username ya -100... id
# Example: FSUB_CHANNELS=@mychannel,-1001234567890
FSUB_CHANNELS = [
    c.strip()
    for c in os.environ.get("FSUB_CHANNELS", "").split(",")
    if c.strip()
]
FSUB_PIC = os.environ.get("FSUB_PIC", "").strip()
FSUB_MSG = os.environ.get(
    "FSUB_MSG",
    "ʜᴇʟʟᴏ {name}\n\n"
    "<b><blockquote>ᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟꜱ ᴀɴᴅ ᴛʜᴇɴ ᴄʟɪᴄᴋ ᴏɴ "
    "ʀᴇʟᴏᴀᴅ ʙᴜᴛᴛᴏɴ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛᴇᴅ ʟɪɴᴋ.</blockquote></b>",
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
    last_exc: Optional[Exception] = None

    for attempt in range(1, 3):  # 2 tries — zyada retry user ko atka deta hai
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(TIMEOUT, connect=15.0), follow_redirects=True
            ) as client:
                resp = await client.get(API_URL, params=params)

            if resp.status_code != 200:
                body = (resp.text or "").strip().replace("\n", " ")[:200]
                raise RuntimeError(f"API HTTP {resp.status_code}: {body}")

            try:
                data = resp.json()
            except ValueError:
                raise RuntimeError(
                    f"API ne JSON nahi bheja: {(resp.text or '')[:200]}"
                ) from None

            if not data.get("success"):
                raise RuntimeError(data.get("notice") or "API returned success=false")

            return data

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            log.warning(
                "attempt %s/2 failed for %s: %s: %s",
                attempt, link, type(exc).__name__, exc,
            )
            if attempt < 2:
                await asyncio.sleep(1.5)

    raise RuntimeError(
        f"{type(last_exc).__name__}: {last_exc or 'connection failed'} "
        f"(timeout {TIMEOUT:.0f}s, 2 tries)"
    )


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
        return InlineKeyboardButton(
            f"🚀 {title.upper()}", url=url, style="primary"
        )
    return InlineKeyboardButton(
        f"⚠️ {title.upper()}", callback_data="fsub_noop", style="danger"
    )


def fsub_caption(first_name: str) -> str:
    return FSUB_MSG.replace("{name}", html.escape(first_name)).replace(
        "{mention}", html.escape(first_name)
    )


async def send_force_sub(bot, chat_id: int, missing: list[str], first_name: str) -> None:
    """Force-sub message bhejo — photo ke saath agar FSUB_PIC set hai."""
    rows = [[await channel_button(bot, ch)] for ch in missing]
    rows.append(
        [InlineKeyboardButton("✅ VERIFY", callback_data="fsub_retry", style="success")]
    )

    markup = InlineKeyboardMarkup(rows)
    caption = fsub_caption(first_name)

    if FSUB_PIC:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=FSUB_PIC,
                caption=caption,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("send_photo failed (%s), falling back to text", exc)

    await bot.send_message(
        chat_id=chat_id,
        text=caption,
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def is_joined(bot, user, chat_id: int) -> bool:
    """True agar user sab channels me hai, warna force-sub message bhej ke False."""
    missing = await missing_channels(bot, user.id)
    if not missing:
        return True

    first_name = user.first_name or "User"
    await send_force_sub(bot, chat_id, missing, first_name)
    return False


def schedule_delete(message, seconds: int) -> None:
    """Message ko kuch second baad delete kar do (fire-and-forget)."""
    if seconds <= 0 or message is None:
        return

    async def _job() -> None:
        await asyncio.sleep(seconds)
        try:
            await message.delete()
        except Exception as exc:  # noqa: BLE001
            log.debug("auto-delete failed: %s", exc)

    asyncio.create_task(_job())


def same_url(a: str, b: str) -> bool:
    """Do URLs practically same hain? (trailing slash / case ignore)"""
    def norm(u: str) -> str:
        u = (u or "").strip().lower()
        u = u.split("#")[0]
        return u.rstrip("/")

    return norm(a) == norm(b)


async def react(message, emoji: str) -> None:
    """User ke message pe emoji reaction lagao (fail ho to chup-chaap ignore)."""
    if not emoji or message is None:
        return
    try:
        await message.set_reaction([ReactionTypeEmoji(emoji=emoji)])
    except Exception as exc:  # noqa: BLE001
        log.debug("reaction %s failed: %s", emoji, exc)


# --------------------------------------------------------------------- handlers
async def react_every_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Har incoming message pe reaction — /start, commands, sab pe."""
    await react(update.effective_message, REACT_EVERY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message

    if user and not await is_joined(context.bot, user, message.chat_id):
        return

    name = html.escape((user.first_name if user else None) or "there")

    caption = (
        f"<blockquote>👋 Hey <b>{name}</b>!</blockquote>\n\n"
        "<b>I'm your link bypass bot.</b>\n\n"
        "Send me any shortener link and I'll pull out the direct link — "
        "no ads, no waiting.\n\n"
        "<b>How to use</b>\n"
        "• Copy any short link\n"
        "• Paste it here\n"
        "• Get the direct link instantly\n\n"
        f"<blockquote><b>Powered By @{CREDIT}</b></blockquote>"
    )

    if START_PIC:
        try:
            await context.bot.send_photo(
                chat_id=message.chat_id,
                photo=START_PIC,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("start photo failed (%s), falling back to text", exc)

    await message.reply_text(
        caption,
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message

    if user and not await is_joined(context.bot, user, message.chat_id):
        return

    await message.reply_text(
        "<b>How to use</b>\n\n"
        "1. Copy any short link\n"
        "2. Send it to me\n"
        "3. Get the direct link\n\n"
        "<b>Commands</b>\n"
        "/start — welcome\n"
        "/help — this message\n\n"
        f"<blockquote><b>Powered By @{CREDIT}</b></blockquote>",
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None:
        return

    if user and not await is_joined(context.bot, user, message.chat_id):
        return

    text = message.text or ""
    match = URL_RE.search(text)
    if not match:
        await message.reply_text(
            "<blockquote><b>❌ No valid link found</b></blockquote>\n"
            "Send a link that starts with <b>http://</b> or <b>https://</b>.",
            parse_mode=ParseMode.HTML,
        )
        return

    link = match.group(0)
    if not REACT_EVERY:
        await react(message, REACT_START)
    status = await message.reply_text("🔗 Bypassing…")

    # User ka link message hata do — chat saaf rahe
    if DELETE_USER_MSG:
        try:
            await message.delete()
        except Exception as exc:  # noqa: BLE001
            log.debug("could not delete user message: %s", exc)

    started = time.perf_counter()

    async def nudge() -> None:
        """20s baad user ko batao ki kaam chal raha hai."""
        await asyncio.sleep(20)
        try:
            await status.edit_text("⏳ Still working… the API is slow, hang tight.")
        except Exception:  # noqa: BLE001
            pass

    nudge_task = asyncio.create_task(nudge())

    try:
        data = await call_api(link)
    except Exception as exc:  # noqa: BLE001
        log.exception("bypass failed for %s", link)
        detail = str(exc).strip() or type(exc).__name__
        await react(message, REACT_FAIL)
        await status.edit_text(
            "<blockquote><b>❌ Bypass failed</b></blockquote>\n"
            f"<code>{html.escape(detail[:300])}</code>",
            parse_mode=ParseMode.HTML,
        )
        schedule_delete(status, AUTO_DELETE)
        return

    finally:
        nudge_task.cancel()

    result_text = data.get("result") or ""
    bypassed = pick_url(result_text, "bypassed link")
    elapsed = time.perf_counter() - started

    if not bypassed:
        # API ne koi URL nahi diya (kabhi gate ka page text bhej deti hai).
        # Raw text user ko dikhana confusing hai — sirf log karo.
        log.warning("no URL in API result for %s: %r", link, result_text[:500])
        await react(message, REACT_FAIL)
        await status.edit_text(
            "<blockquote><b>❌ No bypassed link found</b></blockquote>\n"
            "<blockquote>" + html.escape(link) + "</blockquote>\n"
            "<blockquote>The shortener didn't return a direct link this time. "
            "Please try again in a moment.</blockquote>\n"
            "─────────────\n"
            f"<blockquote><b>Powered By @{CREDIT}</b></blockquote>",
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        schedule_delete(status, AUTO_DELETE)
        return

    # API ne "success" bola par link wahi ka wahi hai — matlab bypass hua hi nahi
    if same_url(link, bypassed):
        await react(message, REACT_FAIL)
        await status.edit_text(
            "<blockquote><b>⚠️ No bypass found for this link</b></blockquote>\n"
            "<blockquote>" + html.escape(link) + "</blockquote>\n"
            "<blockquote><b>I couldn't pull out a direct link from this one.</b> "
            "It may be a shortener I don't support yet, or the link is already "
            "direct.</blockquote>\n"
            "─────────────\n"
            f"<blockquote><b>Powered By @{CREDIT}</b></blockquote>",
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        schedule_delete(status, AUTO_DELETE)
        return

    await react(message, REACT_OK)

    await status.edit_text(
        "<blockquote><b>Original Link :</b></blockquote>\n"
        "<b>✅ " + html.escape(link) + "</b>\n\n"
        "<blockquote><b>Bypassed Link:</b></blockquote>\n"
        "<b>✅ " + html.escape(bypassed) + "</b>\n\n"
        f"<blockquote><b>Time Taken :</b> {elapsed:.0f} seconds</blockquote>\n\n"
        "─────────────\n\n"
        f"<blockquote><b>Powered By @{CREDIT}</b></blockquote>",
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    schedule_delete(status, AUTO_DELETE)


async def fsub_retry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """'Try Again' button — membership dobara check karo."""
    query = update.callback_query
    user = query.from_user

    missing = await missing_channels(context.bot, user.id)
    if missing:
        await query.answer("❌ Abhi bhi join nahi kiya!", show_alert=True)
        return

    await query.answer("✅ Verified!")
    text = (
        "✅ <b>Verification Successful!</b>\n\n"
        "Ab koi bhi short link bhejo, bypass kar dunga."
    )
    try:
        await query.message.edit_caption(caption=text, parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001
        try:
            await query.message.edit_text(text, parse_mode=ParseMode.HTML)
        except Exception:  # noqa: BLE001
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )


async def fsub_noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Jis channel ka invite link nahi mila, us button ke liye."""
    await update.callback_query.answer(
        "Is channel ka link nahi mila. Bot ko channel me admin banao.", show_alert=True
    )


async def on_error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Har handler exception yahan aayega — poora traceback log me."""
    log.error(
        "Handler error | update=%s | error=%s: %s",
        type(update).__name__ if update else "None",
        type(context.error).__name__,
        context.error,
        exc_info=context.error,
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

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        # default 1 hota hai — matlab ek waqt me ek hi update.
        # Ek slow API call poore bot ko block kar deti thi.
        .concurrent_updates(True)
        .build()
    )
    # group=-1 → baaki handlers se pehle chalta hai, par unhe rokta nahi
    app.add_handler(
        MessageHandler(filters.ALL, react_every_message, block=False), group=-1
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(fsub_retry, pattern="^fsub_retry$"))
    app.add_handler(CallbackQueryHandler(fsub_noop, pattern="^fsub_noop$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    # Python 3.12+ pe get_event_loop() khud loop nahi banata, is liye
    # run_polling se pehle ek loop set kar dete hain.
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception as exc:  # noqa: BLE001
        log.warning("could not set event loop: %s", exc)

    app.add_error_handler(on_error)

    log.info("bot starting (long polling)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
