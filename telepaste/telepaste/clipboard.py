"""Clipboard writers for macOS, Linux (Wayland / X11) and Windows, locally or
on another machine over SSH.

Payloads always travel on stdin or in a temp file. Message text is never
interpolated into a shell command, so a message like `$(rm -rf ~)` is just
text on the clipboard.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from typing import Callable, Mapping


class ClipboardError(RuntimeError):
    pass


# macOS: pbcopy / osascript only reach the visible pasteboard when the user
# owns the console (a logged-in desktop session). Fail loudly otherwise.
_DARWIN_GUARD = (
    'test "$(/usr/bin/stat -f %Su /dev/console)" = "$(/usr/bin/id -un)" '
    '|| { echo "no desktop session for $(/usr/bin/id -un) on this Mac" >&2; exit 3; }; '
)
_DARWIN_IMAGE = (
    _DARWIN_GUARD
    + 'd="$(/usr/bin/mktemp -d -t telepaste)" || exit 4; f="$d/clip.png"; '
    '/bin/cat >"$f" && TELEPASTE_FILE="$f" /usr/bin/osascript -e '
    "'set the clipboard to (read (POSIX file (system attribute \"TELEPASTE_FILE\")) as «class PNGf»)'; "
    'r=$?; /bin/rm -rf "$d"; exit $r'
)

# wl-copy, xclip and xsel fork a child that keeps serving the selection and
# holds the inherited stdout/stderr open; redirect them or the caller never sees EOF.
SNIPPETS: dict[str, dict[str, str | None]] = {
    "pbcopy": {
        "text": _DARWIN_GUARD + "LANG=en_US.UTF-8 /usr/bin/pbcopy",
        "image": _DARWIN_IMAGE,
    },
    "wl-copy": {
        "text": "wl-copy >/dev/null 2>&1",
        "image": "wl-copy --type image/png >/dev/null 2>&1",
    },
    "xclip": {
        "text": "xclip -selection clipboard -i >/dev/null 2>&1",
        "image": "xclip -selection clipboard -t image/png -i >/dev/null 2>&1",
    },
    "xsel": {
        "text": "xsel --clipboard --input >/dev/null 2>&1",
        "image": None,
    },
}

_POWERSHELL_TEXT = (
    "Set-Clipboard -Value (Get-Content -LiteralPath $env:TELEPASTE_FILE -Raw -Encoding UTF8)"
)
_POWERSHELL_IMAGE = (
    "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
    "$img = [System.Drawing.Image]::FromFile($env:TELEPASTE_FILE); "
    "[System.Windows.Forms.Clipboard]::SetImage($img); $img.Dispose()"
)

SSH_OPTIONS = (
    "-T",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=3",
    "-o", "StrictHostKeyChecking=accept-new",
)


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    via_file: bool = False  # payload in a temp file named by $TELEPASTE_FILE, not stdin


def detect_backend(env: Mapping[str, str] | None = None, platform: str | None = None,
                   which: Callable[[str], str | None] = shutil.which) -> str:
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        return "pbcopy"
    if platform.startswith("win"):
        return "powershell"
    if env.get("WAYLAND_DISPLAY") and which("wl-copy"):
        return "wl-copy"
    if env.get("DISPLAY"):
        if which("xclip"):
            return "xclip"
        if which("xsel"):
            return "xsel"
    for name in ("wl-copy", "xclip", "xsel"):
        if which(name):
            return name
    raise ClipboardError(
        "no clipboard tool found: install wl-clipboard (Wayland) or xclip (X11), "
        "or set CLIPBOARD=off")


class Clipboard:
    def __init__(self, backend: str = "auto", ssh_host: str | None = None,
                 timeout: float = 5.0):
        if backend == "auto":
            backend = detect_backend()
        if backend not in SNIPPETS and backend not in ("powershell", "off"):
            raise ClipboardError(f"unknown clipboard backend {backend!r}")
        if ssh_host and backend not in SNIPPETS:
            raise ClipboardError("remote clipboard needs pbcopy, wl-copy, xclip or xsel")
        self.backend = backend
        self.ssh_host = ssh_host
        self.timeout = timeout + (5.0 if ssh_host else 0.0)

    @property
    def enabled(self) -> bool:
        return self.backend != "off"

    @property
    def supports_images(self) -> bool:
        if self.backend == "powershell":
            return True
        return self.backend in SNIPPETS and SNIPPETS[self.backend]["image"] is not None

    def describe(self) -> str:
        if not self.enabled:
            return "off"
        if self.ssh_host:
            return f"{self.backend} on {self.ssh_host}"
        return f"{self.backend} (local)"

    def local_tool(self) -> str | None:
        """Executable name to look up with `which` for a local backend."""
        if self.ssh_host or not self.enabled:
            return None
        return {"pbcopy": "pbcopy", "powershell": "powershell.exe"}.get(self.backend, self.backend)

    def command(self, kind: str) -> Command:
        if self.backend == "powershell":
            script = _POWERSHELL_TEXT if kind == "text" else _POWERSHELL_IMAGE
            return Command(("powershell.exe", "-NoProfile", "-NonInteractive", "-STA",
                            "-Command", script), via_file=True)
        snippet = SNIPPETS[self.backend][kind]
        if snippet is None:
            raise ClipboardError(f"{self.backend} cannot take images; use wl-copy or xclip")
        if self.ssh_host:
            return Command(("ssh", *SSH_OPTIONS, self.ssh_host, snippet))
        return Command(("/bin/sh", "-c", snippet))

    async def write_text(self, text: str) -> None:
        await self._write("text", text.encode("utf-8"))

    async def write_image(self, png: bytes) -> None:
        await self._write("image", png)

    async def _write(self, kind: str, payload: bytes) -> None:
        if not self.enabled:
            return
        cmd = self.command(kind)
        env = dict(os.environ)
        tmp: str | None = None
        try:
            if cmd.via_file:
                fd, tmp = tempfile.mkstemp(prefix="telepaste-",
                                           suffix=".png" if kind == "image" else ".txt")
                with os.fdopen(fd, "wb") as fp:
                    fp.write(payload)
                env["TELEPASTE_FILE"] = tmp
                await self._run(cmd.argv, None, env)
            else:
                await self._run(cmd.argv, payload, env)
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    async def _run(self, argv: tuple[str, ...], payload: bytes | None,
                   env: Mapping[str, str]) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if payload is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            raise ClipboardError(f"cannot start {argv[0]}: {exc}") from exc
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(payload), self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ClipboardError(f"{self.describe()} timed out after {self.timeout:.0f}s") from None
        if proc.returncode:
            detail = stderr.decode("utf-8", "replace").strip()[:300]
            if proc.returncode == 127 and not detail:
                detail = "command not found"
            message = f"{self.describe()} failed (exit {proc.returncode})"
            raise ClipboardError(f"{message}: {detail}" if detail else message)
