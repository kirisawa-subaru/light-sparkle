"""Telegram handlers, replies and the polling loop."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from . import __version__
from .clipboard import Clipboard, ClipboardError
from .config import Config
from .images import ImageError, to_png
from .journal import Journal, attachment_name, markdown_link
from .storage import Uploader, UploadError

log = logging.getLogger("telepaste")

HEARTBEAT_INTERVAL = 60
HEARTBEAT_FAILS = 3
TELEGRAM_TEXT_LIMIT = 4000

PAIRING = (
    "No allowed chats are configured yet.\n"
    "Your chat id is {chat_id}.\n"
    "Put it in TELEGRAM_ALLOWED_CHAT_IDS in your .env and restart telepaste."
)


class State:
    """Tiny JSON file for settings toggled from Telegram (quiet mode)."""

    def __init__(self, path: Path):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("cannot persist state to %s: %s", self.path, exc)


@dataclass
class Services:
    config: Config
    clipboard: Clipboard
    journal: Journal | None
    uploader: Uploader | None
    state: State

    @property
    def quiet(self) -> bool:
        return bool(self.state.get("quiet", False))


def _services(context) -> Services:
    return context.bot_data["services"]


# ---------- admission / clipboard / replies ----------
async def _admit(msg, s: Services) -> bool:
    if not s.config.allowed_chat_ids:
        log.warning("pairing mode: replying with chat id to chat_id=%s", msg.chat_id)
        await msg.reply_text(PAIRING.format(chat_id=msg.chat_id))
        return False
    if msg.chat_id not in s.config.allowed_chat_ids:
        log.warning("ignored message from chat_id=%s (not in allowlist)", msg.chat_id)
        return False
    return True


def _stale(msg, s: Services) -> bool:
    return time.time() - msg.date.timestamp() > s.config.clipboard_max_age


async def _copy(msg, s: Services, kind: str, payload) -> str:
    """Write to the clipboard; return a short note for the reply."""
    if not s.clipboard.enabled:
        return "saved"
    if _stale(msg, s):
        log.info("clipboard skipped: message_id=%s older than %ss",
                 msg.message_id, s.config.clipboard_max_age)
        return f"saved · not copied (older than {s.config.clipboard_max_age}s)"
    try:
        if kind == "text":
            await s.clipboard.write_text(payload)
        else:
            await s.clipboard.write_image(payload)
    except ClipboardError as exc:
        log.warning("clipboard: %s", exc)
        return f"saved · clipboard failed: {exc}"
    log.info("clipboard updated (%s) message_id=%s", kind, msg.message_id)
    return "copied"


async def _reply(msg, s: Services, note: str, url: str | None = None) -> None:
    if s.quiet:
        return
    text = f"✓ {note}"
    if url:
        text += f"\n{url}"
    await msg.reply_text(text)


def _clip_payload(s: Services, *, url: str | None, is_image: bool, caption: str | None,
                  data: bytes, label: str):
    """Decide what a photo / file puts on the clipboard."""
    mode = s.config.clipboard_photo
    if is_image and (mode == "image" or url is None):
        if s.clipboard.supports_images:
            try:
                return "image", to_png(data)
            except ImageError as exc:
                log.warning("%s; falling back to text", exc)
        if url:
            return "text", url
        return ("text", caption) if caption else (None, None)
    if url:
        if mode == "markdown":
            return "text", (f"![]({url})" if is_image else markdown_link(label, url))
        return "text", url
    return ("text", caption) if caption else (None, None)


# ---------- handlers ----------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or not msg.text:
        return
    s = _services(context)
    if not await _admit(msg, s):
        return
    if s.journal:
        s.journal.append(msg.text)
    note = await _copy(msg, s, "text", msg.text)
    await _reply(msg, s, note)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or not msg.photo:
        return
    s = _services(context)
    if not await _admit(msg, s):
        return
    tg_file = await msg.photo[-1].get_file()
    data = bytes(await tg_file.download_as_bytearray())
    await _attachment(msg, s, data, suffix=".jpg", original=None,
                      content_type="image/jpeg", is_image=True)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or not msg.document:
        return
    s = _services(context)
    if not await _admit(msg, s):
        return
    doc = msg.document
    tg_file = await doc.get_file()
    data = bytes(await tg_file.download_as_bytearray())
    mime = doc.mime_type or "application/octet-stream"
    await _attachment(msg, s, data, suffix="",
                      original=doc.file_name or f"file_{doc.file_unique_id}",
                      content_type=mime, is_image=mime.startswith("image/"))


async def _attachment(msg, s: Services, data: bytes, *, suffix: str, original: str | None,
                      content_type: str, is_image: bool) -> None:
    now = s.journal.now() if s.journal else datetime.now(s.config.journal_tz)
    filename = attachment_name(now, suffix, original)
    local = s.journal.save_attachment(data, filename) if s.journal else None
    name = local.name if local else filename

    url: str | None = None
    upload_note: str | None = None
    if s.uploader:
        key = s.uploader.key_for(f"{now:%Y-%m-%d}", name)
        try:
            url = await asyncio.to_thread(s.uploader.upload, data, key, content_type)
            log.info("uploaded %s (%d bytes)", key, len(data))
        except UploadError as exc:
            log.warning("%s", exc)
            upload_note = "upload failed"

    if s.journal:
        ref = url or s.journal.relative(local)
        entry = f"![]({ref})" if is_image else markdown_link(original or name, ref)
        if msg.caption:
            entry += f"\n{msg.caption}"
        s.journal.append(entry, now)

    kind, payload = _clip_payload(s, url=url, is_image=is_image, caption=msg.caption,
                                  data=data, label=original or name)
    note = "saved" if payload is None else await _copy(msg, s, kind, payload)
    if upload_note:
        note += f" · {upload_note}"
    await _reply(msg, s, note, url)


# ---------- commands ----------
def _status_text(msg, s: Services) -> str:
    lines = [
        f"telepaste {__version__}",
        f"chat id: {msg.chat_id}",
        f"clipboard: {s.clipboard.describe()}",
        f"notes: {s.journal.root if s.journal else 'off'}",
        f"upload: {s.uploader.describe() if s.uploader else 'off'}",
        f"quiet: {'on' if s.quiet else 'off'}",
        "",
        "Send text, a photo or a file. /today shows today's notes, /quiet toggles replies.",
    ]
    return "\n".join(lines)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    s = _services(context)
    if msg is None or not await _admit(msg, s):
        return
    await msg.reply_text(_status_text(msg, s))


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is not None:
        await msg.reply_text(f"chat id: {msg.chat_id}")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    s = _services(context)
    if msg is None or not await _admit(msg, s):
        return
    if s.journal is None:
        await msg.reply_text("notes are off (JOURNAL_DIR is not set)")
        return
    content = s.journal.read_today() or "nothing today"
    for i in range(0, len(content), TELEGRAM_TEXT_LIMIT):
        await msg.reply_text(content[i:i + TELEGRAM_TEXT_LIMIT])


async def cmd_quiet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    s = _services(context)
    if msg is None or not await _admit(msg, s):
        return
    quiet = not s.quiet
    s.state.set("quiet", quiet)
    await msg.reply_text("quiet mode on: no replies until /quiet again" if quiet
                         else "quiet mode off")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("update %s caused error: %s", update, context.error, exc_info=context.error)


# ---------- watchdog ----------
async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    fails = context.bot_data.get("heartbeat_fails", 0)
    try:
        await context.bot.get_me()
    except Exception as exc:
        fails += 1
        context.bot_data["heartbeat_fails"] = fails
        log.warning("heartbeat fail %d/%d: %s", fails, HEARTBEAT_FAILS, exc)
        if fails >= HEARTBEAT_FAILS:
            log.error("Telegram unreachable; exiting so the service manager restarts")
            os._exit(1)
        return
    if fails:
        log.info("heartbeat recovered after %d fails", fails)
    context.bot_data["heartbeat_fails"] = 0


# ---------- assembly ----------
BOT_COMMANDS = [
    BotCommand("today", "today's notes"),
    BotCommand("quiet", "toggle replies"),
    BotCommand("id", "show this chat id"),
    BotCommand("help", "status and usage"),
]


async def _post_init(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)


def build_services(config: Config) -> Services:
    clipboard = Clipboard(config.clipboard, config.clipboard_ssh_host)
    journal = Journal(config.journal_dir, config.journal_tz) if config.journal_dir else None
    uploader = Uploader(config.s3) if config.s3 else None
    return Services(config, clipboard, journal, uploader, State(config.state_file))


def build_application(config: Config, services: Services) -> Application:
    socket_options = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    keep_idle = getattr(socket, "TCP_KEEPIDLE", None) or getattr(socket, "TCP_KEEPALIVE", None)
    if keep_idle is not None:
        socket_options.append((socket.IPPROTO_TCP, keep_idle, 15))
    request_options = dict(
        connect_timeout=10.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=5.0,
        socket_options=socket_options,
        proxy=config.proxy,
    )
    builder = (
        Application.builder()
        .token(config.token)
        .request(HTTPXRequest(**request_options))
        .get_updates_request(HTTPXRequest(**request_options))
        .post_init(_post_init)
    )
    if config.api_base:
        builder = builder.base_url(f"{config.api_base}/bot").base_file_url(
            f"{config.api_base}/file/bot")
    app = builder.build()
    app.bot_data["services"] = services
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("quiet", cmd_quiet))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_error_handler(on_error)
    if app.job_queue is not None:
        app.job_queue.run_repeating(heartbeat, interval=HEARTBEAT_INTERVAL,
                                    first=HEARTBEAT_INTERVAL)
    return app


def wait_for_telegram(config: Config, max_backoff: int = 60) -> None:
    """Block until getMe succeeds, so a boot-time network gap does not burn
    the service manager's restart budget."""
    base = (config.api_base or "https://api.telegram.org").rstrip("/")
    backoff = 5
    while True:
        try:
            r = httpx.get(f"{base}/bot{config.token}/getMe", timeout=15, proxy=config.proxy)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 200 and body.get("ok"):
                log.info("connected as @%s", body["result"].get("username", "?"))
                return
            if r.status_code == 401:
                raise SystemExit("Telegram rejected the bot token (401)")
            log.warning("getMe returned %s, retrying in %ss", r.status_code, backoff)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Telegram unreachable (%s), retrying in %ss", exc, backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


def run(config: Config) -> int:
    services = build_services(config)
    log.info("telepaste %s · clipboard: %s · notes: %s · upload: %s · allowed chats: %s",
             __version__, services.clipboard.describe(),
             services.journal.root if services.journal else "off",
             services.uploader.describe() if services.uploader else "off",
             sorted(config.allowed_chat_ids) or "none (pairing mode)")
    if services.clipboard.enabled and not services.clipboard.supports_images:
        log.warning("%s cannot take images; photos will copy their caption or URL",
                    services.clipboard.describe())
    if config.journal_dir:
        config.journal_dir.mkdir(parents=True, exist_ok=True)
    wait_for_telegram(config)
    app = build_application(config, services)
    app.run_polling(drop_pending_updates=False)
    return 0
