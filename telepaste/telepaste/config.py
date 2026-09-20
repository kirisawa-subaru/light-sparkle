"""Environment-based configuration. Every setting is a plain env var so the
same file works for systemd, launchd, a Windows scheduled task, or a shell."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BACKENDS = ("auto", "pbcopy", "wl-copy", "xclip", "xsel", "powershell", "off")
REMOTE_BACKENDS = ("pbcopy", "wl-copy", "xclip", "xsel")
PHOTO_MODES = ("image", "url", "markdown")
DEFAULT_MAX_AGE = 120
DEFAULT_URL_EXPIRE = 7 * 24 * 3600


class ConfigError(ValueError):
    pass


def _ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            raise ConfigError(f"TELEGRAM_ALLOWED_CHAT_IDS: {part!r} is not an integer") from None
    return frozenset(ids)


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer") from None
    if value <= 0:
        raise ConfigError(f"{key} must be positive")
    return value


def _url(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key, "").strip().rstrip("/")
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        raise ConfigError(f"{key} must start with http:// or https://")
    return value


@dataclass(frozen=True)
class S3Config:
    bucket: str
    endpoint_url: str | None
    region: str | None
    access_key_id: str
    secret_access_key: str
    public_base_url: str | None
    prefix: str
    url_expire: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "S3Config | None":
        bucket = env.get("S3_BUCKET", "").strip()
        if not bucket:
            return None
        missing = [k for k in ("S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
                   if not env.get(k, "").strip()]
        if missing:
            raise ConfigError(f"S3_BUCKET is set but {', '.join(missing)} missing")
        return cls(
            bucket=bucket,
            endpoint_url=_url(env, "S3_ENDPOINT_URL"),
            region=env.get("S3_REGION", "").strip() or None,
            access_key_id=env["S3_ACCESS_KEY_ID"].strip(),
            secret_access_key=env["S3_SECRET_ACCESS_KEY"].strip(),
            public_base_url=_url(env, "S3_PUBLIC_BASE_URL"),
            prefix=env.get("S3_PREFIX", "").strip().strip("/"),
            url_expire=_positive_int(env, "S3_URL_EXPIRE", DEFAULT_URL_EXPIRE),
        )


@dataclass(frozen=True)
class Config:
    token: str
    allowed_chat_ids: frozenset[int]
    api_base: str | None
    proxy: str | None
    journal_dir: Path | None
    journal_tz: tzinfo
    journal_tz_name: str
    clipboard: str
    clipboard_ssh_host: str | None
    clipboard_max_age: int
    clipboard_photo: str
    state_file: Path
    s3: S3Config | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env

        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN is not set (get one from @BotFather)")

        journal_raw = env.get("JOURNAL_DIR", "").strip()
        journal_dir = Path(journal_raw).expanduser() if journal_raw else None

        tz_name = env.get("JOURNAL_TZ", "").strip()
        if tz_name:
            try:
                tz: tzinfo = ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, ValueError):
                raise ConfigError(f"JOURNAL_TZ: unknown timezone {tz_name!r}") from None
        else:
            local = datetime.now().astimezone()
            tz = local.tzinfo or ZoneInfo("UTC")
            tz_name = local.tzname() or "local"

        clipboard = env.get("CLIPBOARD", "").strip().lower() or "auto"
        if clipboard not in BACKENDS:
            raise ConfigError(f"CLIPBOARD must be one of {', '.join(BACKENDS)}")
        ssh_host = env.get("CLIPBOARD_SSH_HOST", "").strip() or None
        if ssh_host and clipboard not in REMOTE_BACKENDS:
            raise ConfigError(
                "CLIPBOARD_SSH_HOST needs an explicit remote backend: "
                f"CLIPBOARD={' | '.join(REMOTE_BACKENDS)}")

        s3 = S3Config.from_env(env)
        photo = env.get("CLIPBOARD_PHOTO", "").strip().lower() or ("url" if s3 else "image")
        if photo not in PHOTO_MODES:
            raise ConfigError(f"CLIPBOARD_PHOTO must be one of {', '.join(PHOTO_MODES)}")
        if photo != "image" and s3 is None:
            raise ConfigError(f"CLIPBOARD_PHOTO={photo} needs the S3_* upload settings")

        state_raw = env.get("STATE_FILE", "").strip()
        state_file = (Path(state_raw).expanduser() if state_raw
                      else Path.home() / ".telepaste" / "state.json")

        return cls(
            token=token,
            allowed_chat_ids=_ids(env.get("TELEGRAM_ALLOWED_CHAT_IDS", "")),
            api_base=_url(env, "TELEGRAM_API_BASE"),
            proxy=env.get("TELEGRAM_PROXY", "").strip() or None,
            journal_dir=journal_dir,
            journal_tz=tz,
            journal_tz_name=tz_name,
            clipboard=clipboard,
            clipboard_ssh_host=ssh_host,
            clipboard_max_age=_positive_int(env, "CLIPBOARD_MAX_AGE", DEFAULT_MAX_AGE),
            clipboard_photo=photo,
            state_file=state_file,
            s3=s3,
        )
