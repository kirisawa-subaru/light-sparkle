"""Daily markdown notes: <JOURNAL_DIR>/YYYY-MM-DD.md with attachments under
<JOURNAL_DIR>/attachments/. Relative links, so the folder drops straight
into an Obsidian vault or any markdown editor."""

from __future__ import annotations

import re
from datetime import datetime, tzinfo
from pathlib import Path
from urllib.parse import quote

ATTACHMENTS = "attachments"


def safe_filename(name: str | None, fallback: str = "file") -> str:
    name = (name or "").strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]+", " ", name).strip()
    if name in ("", ".", ".."):
        name = fallback
    if len(name) <= 120:
        return name
    path = Path(name)
    suffix = path.suffix[:24]
    return f"{path.stem[:120 - len(suffix)]}{suffix}"


def markdown_link(label: str, target: str) -> str:
    label = label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"[{label}]({target})"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    n = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


class Journal:
    def __init__(self, root: Path, tz: tzinfo):
        self.root = root
        self.tz = tz

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def today_file(self, now: datetime | None = None) -> Path:
        now = now or self.now()
        return self.root / f"{now:%Y-%m-%d}.md"

    def append(self, text: str, now: datetime | None = None) -> None:
        now = now or self.now()
        path = self.today_file(now)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(f"{now:%H:%M:%S} {text}\n\n")

    def save_attachment(self, data: bytes, filename: str) -> Path:
        folder = self.root / ATTACHMENTS
        folder.mkdir(parents=True, exist_ok=True)
        path = unique_path(folder / filename)
        path.write_bytes(data)
        return path

    def relative(self, path: Path) -> str:
        return quote(path.relative_to(self.root).as_posix(), safe="/")

    def read_today(self) -> str:
        path = self.today_file()
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def attachment_name(now: datetime, suffix: str, original: str | None = None) -> str:
    stamp = f"{now:%Y-%m-%d_%H%M%S}"
    if original:
        return f"{stamp}_{safe_filename(original)}"
    return f"{stamp}{suffix}"
