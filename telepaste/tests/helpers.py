from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

from PIL import Image


def jpeg_bytes(size=(4, 3), color=(200, 30, 30)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


def png_bytes(size=(2, 2), mode="RGBA") -> bytes:
    out = BytesIO()
    Image.new(mode, size, (1, 2, 3, 128) if mode == "RGBA" else (1, 2, 3)).save(out, format="PNG")
    return out.getvalue()


def message(**changes):
    fields = dict(text=None, caption=None, chat_id=123, message_id=1,
                  chat=SimpleNamespace(type="private"),
                  date=datetime.now(timezone.utc), reply_text=mock.AsyncMock(),
                  photo=None, document=None)
    fields.update(changes)
    return SimpleNamespace(**fields)


def tg_file(payload: bytes):
    return SimpleNamespace(download_as_bytearray=mock.AsyncMock(return_value=bytearray(payload)))


def photo_message(payload: bytes | None = None, **changes):
    payload = jpeg_bytes() if payload is None else payload
    photo = SimpleNamespace(get_file=mock.AsyncMock(return_value=tg_file(payload)))
    return message(photo=[photo], **changes)


def document_message(name="report v1.pdf", mime="application/pdf", payload=b"%PDF-1.4", **changes):
    doc = SimpleNamespace(file_name=name, file_unique_id="u1", mime_type=mime,
                          get_file=mock.AsyncMock(return_value=tg_file(payload)))
    return message(document=doc, **changes)


def update(msg):
    return SimpleNamespace(effective_message=msg, message=msg)


def context(services):
    return SimpleNamespace(bot_data={"services": services})
