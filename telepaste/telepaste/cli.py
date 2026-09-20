"""`telepaste` command line: run, doctor, clip."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from . import __version__
from .clipboard import SSH_OPTIONS, Clipboard, ClipboardError
from .config import Config, ConfigError
from .images import ImageError, to_png


def _load_env(explicit: str | None) -> Path | None:
    candidates = ([explicit] if explicit
                  else [os.environ.get("TELEPASTE_ENV"), ".env",
                        str(Path.home() / ".telepaste" / ".env")])
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            load_dotenv(path, override=False)
            return path
    if explicit:
        raise SystemExit(f"env file not found: {explicit}")
    return None


def _clipboard_from_env() -> Clipboard:
    return Clipboard(os.environ.get("CLIPBOARD", "").strip().lower() or "auto",
                     os.environ.get("CLIPBOARD_SSH_HOST", "").strip() or None)


def doctor(env_file: Path | None) -> int:
    ok = True

    def line(good: bool, text: str) -> None:
        nonlocal ok
        ok = ok and good
        print(f"[{'ok' if good else 'FAIL'}] {text}")

    print(f"telepaste {__version__} · python {sys.version.split()[0]} · {sys.platform}")
    print(f"env file: {env_file or '(none found)'}")
    try:
        config = Config.from_env()
    except ConfigError as exc:
        line(False, f"config: {exc}")
        return 1
    line(True, "config loaded")
    if config.allowed_chat_ids:
        line(True, f"allowed chats: {', '.join(map(str, sorted(config.allowed_chat_ids)))}")
    else:
        line(True, "allowed chats: none yet (pairing mode: the bot replies with your chat id)")

    try:
        clipboard = Clipboard(config.clipboard, config.clipboard_ssh_host)
    except ClipboardError as exc:
        line(False, f"clipboard: {exc}")
    else:
        tool = clipboard.local_tool()
        if tool and not shutil.which(tool):
            line(False, f"clipboard: {clipboard.describe()}: {tool} not found on PATH")
        elif clipboard.ssh_host:
            try:
                probe = subprocess.run(["ssh", *SSH_OPTIONS, clipboard.ssh_host, "true"],
                                       capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired) as exc:
                line(False, f"clipboard: {clipboard.describe()}: ssh failed ({exc})")
            else:
                detail = probe.stderr.strip()[:200]
                line(probe.returncode == 0,
                     f"clipboard: {clipboard.describe()}: "
                     + ("ssh reachable" if probe.returncode == 0 else f"ssh failed: {detail}"))
        else:
            extra = "" if clipboard.supports_images else " (text only)"
            line(True, f"clipboard: {clipboard.describe()}{extra}")

    if config.journal_dir:
        try:
            config.journal_dir.mkdir(parents=True, exist_ok=True)
            probe_file = config.journal_dir / ".telepaste-write-test"
            probe_file.write_text("ok", encoding="utf-8")
            probe_file.unlink()
        except OSError as exc:
            line(False, f"notes: {config.journal_dir}: {exc}")
        else:
            line(True, f"notes: {config.journal_dir} ({config.journal_tz_name})")
    else:
        line(True, "notes: off (JOURNAL_DIR not set)")

    if config.s3:
        try:
            from .storage import Uploader
            uploader = Uploader(config.s3)
        except ConfigError as exc:
            line(False, f"upload: {exc}")
        else:
            line(True, f"upload: {uploader.describe()} · photos copy as {config.clipboard_photo}")
    else:
        line(True, "upload: off")

    base = (config.api_base or "https://api.telegram.org").rstrip("/")
    try:
        r = httpx.get(f"{base}/bot{config.token}/getMe", timeout=15, proxy=config.proxy)
        body = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        line(False, f"telegram: unreachable ({exc})")
    else:
        if r.status_code == 200 and body.get("ok"):
            line(True, f"telegram: @{body['result'].get('username', '?')}")
        else:
            line(False, f"telegram: {r.status_code} {body.get('description', '')}".strip())
    return 0 if ok else 1


def clip(image: bool) -> int:
    data = sys.stdin.buffer.read()
    if not data:
        print("nothing on stdin", file=sys.stderr)
        return 2
    try:
        clipboard = _clipboard_from_env()
        if image:
            asyncio.run(clipboard.write_image(to_png(data)))
        else:
            asyncio.run(clipboard.write_text(data.decode("utf-8")))
    except (ClipboardError, ImageError, UnicodeDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"copied {len(data)} bytes to {clipboard.describe()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="telepaste",
        description="Send text and images to your Telegram bot; get them on your desktop clipboard.")
    parser.add_argument("--env", help="path to .env (default: $TELEPASTE_ENV, ./.env, ~/.telepaste/.env)")
    parser.add_argument("--version", action="version", version=f"telepaste {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="run the bot (default)")
    sub.add_parser("doctor", help="check config, clipboard, notes folder, upload and Telegram")
    clip_parser = sub.add_parser("clip", help="copy stdin to the configured clipboard")
    clip_parser.add_argument("--image", action="store_true", help="stdin is an image")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    env_file = _load_env(args.env)
    command = args.command or "run"
    if command == "doctor":
        return doctor(env_file)
    if command == "clip":
        return clip(args.image)
    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    from .bot import run
    try:
        return run(config)
    except ClipboardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
