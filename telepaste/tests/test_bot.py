import dataclasses
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from telepaste import bot
from telepaste.clipboard import ClipboardError
from telepaste.config import Config, S3Config
from telepaste.journal import Journal
from telepaste.storage import UploadError
from tests.helpers import (context, document_message, jpeg_bytes, message, photo_message,
                           png_bytes, update)

PNG_SIG = b"\x89PNG\r\n\x1a\n"


class FakeClipboard:
    def __init__(self, images=True, enabled=True, fail=None):
        self.supports_images = images
        self.enabled = enabled
        self.fail = fail
        self.writes = []

    def describe(self):
        return "fake"

    async def write_text(self, text):
        if self.fail:
            raise ClipboardError(self.fail)
        self.writes.append(("text", text))

    async def write_image(self, png):
        if self.fail:
            raise ClipboardError(self.fail)
        self.writes.append(("image", png))


class FakeUploader:
    def __init__(self, fail=False):
        self.fail = fail
        self.uploads = []

    def describe(self):
        return "fake-s3"

    def key_for(self, day, filename):
        return f"clips/{day}/{filename}"

    def upload(self, data, key, content_type):
        if self.fail:
            raise UploadError(f"upload failed for {key}: AccessDenied")
        self.uploads.append((key, content_type, data))
        return f"https://img.example.com/{key}"


class BotTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Config.from_env({
            "TELEGRAM_BOT_TOKEN": "1:x", "TELEGRAM_ALLOWED_CHAT_IDS": "123",
            "JOURNAL_DIR": str(self.root / "notes"), "JOURNAL_TZ": "Asia/Shanghai",
            "CLIPBOARD": "off", "STATE_FILE": str(self.root / "state.json"),
        })
        self.clipboard = FakeClipboard()
        self.uploader = None
        self.services = None

    def build(self, **config_changes):
        config = dataclasses.replace(self.config, **config_changes)
        journal = Journal(config.journal_dir, config.journal_tz) if config.journal_dir else None
        self.services = bot.Services(config, self.clipboard, journal, self.uploader,
                                     bot.State(config.state_file))
        return context(self.services)

    def notes(self):
        return self.services.journal.read_today()

    @staticmethod
    def reply(msg):
        return msg.reply_text.await_args.args[0]


class TextTests(BotTestCase):
    async def test_text_is_saved_copied_and_acknowledged(self):
        ctx = self.build()
        msg = message(text="hello 中文")
        await bot.on_text(update(msg), ctx)
        self.assertRegex(self.notes(), r"^\d\d:\d\d:\d\d hello 中文$")
        self.assertEqual(self.clipboard.writes, [("text", "hello 中文")])
        self.assertEqual(self.reply(msg), "✓ copied")

    async def test_pairing_mode_replies_with_chat_id_and_stores_nothing(self):
        ctx = self.build(allowed_chat_ids=frozenset())
        msg = message(text="hi", chat_id=555)
        await bot.on_text(update(msg), ctx)
        self.assertIn("555", self.reply(msg))
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.notes(), "")

    async def test_unknown_chat_is_dropped_silently(self):
        ctx = self.build()
        msg = message(text="hi", chat_id=999)
        await bot.on_text(update(msg), ctx)
        msg.reply_text.assert_not_awaited()
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.notes(), "")

    async def test_stale_message_is_saved_but_not_copied(self):
        ctx = self.build()
        msg = message(text="old", date=datetime.now(timezone.utc) - timedelta(seconds=500))
        await bot.on_text(update(msg), ctx)
        self.assertEqual(self.clipboard.writes, [])
        self.assertIn("old", self.notes())
        self.assertEqual(self.reply(msg), "✓ saved · not copied (older than 120s)")

    async def test_clipboard_failure_is_reported_not_fatal(self):
        self.clipboard = FakeClipboard(fail="pbcopy on mac failed (exit 3): no desktop session")
        ctx = self.build()
        msg = message(text="x")
        await bot.on_text(update(msg), ctx)
        self.assertIn("x", self.notes())
        self.assertEqual(self.reply(msg), "✓ saved · clipboard failed: pbcopy on mac failed (exit 3): no desktop session")

    async def test_clipboard_off_and_notes_off(self):
        self.clipboard = FakeClipboard(enabled=False)
        ctx = self.build()
        msg = message(text="x")
        await bot.on_text(update(msg), ctx)
        self.assertEqual(self.reply(msg), "✓ saved")

        self.clipboard = FakeClipboard()
        ctx = self.build(journal_dir=None)
        msg = message(text="y")
        await bot.on_text(update(msg), ctx)
        self.assertEqual(self.clipboard.writes, [("text", "y")])
        self.assertEqual(self.reply(msg), "✓ copied")
        written = "".join(f.read_text(encoding="utf-8") for f in (self.root / "notes").glob("*.md"))
        self.assertNotIn("y", written)

    async def test_quiet_mode_suppresses_replies_and_persists(self):
        ctx = self.build()
        toggle = message(text="/quiet")
        await bot.cmd_quiet(update(toggle), ctx)
        self.assertIn("quiet mode on", self.reply(toggle))
        msg = message(text="silent")
        await bot.on_text(update(msg), ctx)
        msg.reply_text.assert_not_awaited()
        self.assertEqual(self.clipboard.writes, [("text", "silent")])
        self.assertTrue(bot.State(self.config.state_file).get("quiet"))
        await bot.cmd_quiet(update(toggle), ctx)
        self.assertEqual(self.reply(toggle), "quiet mode off")


class PhotoTests(BotTestCase):
    async def test_photo_goes_to_clipboard_as_png_and_into_notes(self):
        ctx = self.build()
        msg = photo_message(caption="screenshot")
        await bot.on_photo(update(msg), ctx)
        kind, png = self.clipboard.writes[0]
        self.assertEqual(kind, "image")
        self.assertTrue(png.startswith(PNG_SIG))
        self.assertRegex(self.notes(), r"!\[\]\(attachments/\d{4}-\d\d-\d\d_\d{6}\.jpg\)\nscreenshot$")
        saved = list((self.root / "notes" / "attachments").iterdir())
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), jpeg_bytes())
        self.assertEqual(self.reply(msg), "✓ copied")

    async def test_photo_without_notes_still_copies(self):
        ctx = self.build(journal_dir=None)
        msg = photo_message()
        await bot.on_photo(update(msg), ctx)
        self.assertEqual(self.clipboard.writes[0][0], "image")
        self.assertEqual(self.reply(msg), "✓ copied")

    async def test_text_only_clipboard_copies_caption_instead(self):
        self.clipboard = FakeClipboard(images=False)
        ctx = self.build()
        msg = photo_message(caption="cap")
        await bot.on_photo(update(msg), ctx)
        self.assertEqual(self.clipboard.writes, [("text", "cap")])
        msg = photo_message()
        await bot.on_photo(update(msg), ctx)
        self.assertEqual(len(self.clipboard.writes), 1)
        self.assertEqual(self.reply(msg), "✓ saved")

    async def test_undecodable_photo_falls_back(self):
        ctx = self.build()
        msg = photo_message(payload=b"not really a jpeg", caption="c")
        await bot.on_photo(update(msg), ctx)
        self.assertEqual(self.clipboard.writes, [("text", "c")])
        self.assertIn("![](attachments/", self.notes())

    async def test_same_second_photos_get_distinct_files(self):
        ctx = self.build()
        fixed = datetime(2026, 9, 17, 1, 2, 3, tzinfo=self.config.journal_tz)
        with mock.patch.object(self.services.journal, "now", return_value=fixed):
            await bot.on_photo(update(photo_message()), ctx)
            await bot.on_photo(update(photo_message()), ctx)
        names = sorted(p.name for p in (self.root / "notes" / "attachments").iterdir())
        self.assertEqual(names, ["2026-09-17_010203.jpg", "2026-09-17_010203_1.jpg"])


class UploadTests(BotTestCase):
    def setUp(self):
        super().setUp()
        self.uploader = FakeUploader()
        self.s3 = S3Config(bucket="b", endpoint_url=None, region=None, access_key_id="k",
                           secret_access_key="s", public_base_url="https://img.example.com",
                           prefix="clips", url_expire=600)

    async def test_url_mode_copies_url_and_links_it_in_notes(self):
        ctx = self.build(s3=self.s3, clipboard_photo="url")
        msg = photo_message(caption="c")
        await bot.on_photo(update(msg), ctx)
        key, content_type, data = self.uploader.uploads[0]
        self.assertRegex(key, r"^clips/\d{4}-\d\d-\d\d/\d{4}-\d\d-\d\d_\d{6}\.jpg$")
        self.assertEqual((content_type, data), ("image/jpeg", jpeg_bytes()))
        url = f"https://img.example.com/{key}"
        self.assertEqual(self.clipboard.writes, [("text", url)])
        self.assertIn(f"![]({url})\nc", self.notes())
        self.assertEqual(self.reply(msg), f"✓ copied\n{url}")

    async def test_markdown_mode(self):
        ctx = self.build(s3=self.s3, clipboard_photo="markdown")
        await bot.on_photo(update(photo_message()), ctx)
        url = f"https://img.example.com/{self.uploader.uploads[0][0]}"
        self.assertEqual(self.clipboard.writes, [("text", f"![]({url})")])
        await bot.on_document(update(document_message(name="a.pdf")), ctx)
        url = f"https://img.example.com/{self.uploader.uploads[1][0]}"
        self.assertEqual(self.clipboard.writes[1], ("text", f"[a.pdf]({url})"))

    async def test_image_mode_with_upload_keeps_image_on_clipboard(self):
        ctx = self.build(s3=self.s3, clipboard_photo="image")
        msg = photo_message()
        await bot.on_photo(update(msg), ctx)
        self.assertEqual(self.clipboard.writes[0][0], "image")
        self.assertIn("https://img.example.com/", self.notes())
        self.assertIn("https://img.example.com/", self.reply(msg))

    async def test_upload_failure_falls_back_to_local_link(self):
        self.uploader = FakeUploader(fail=True)
        ctx = self.build(s3=self.s3, clipboard_photo="url")
        msg = photo_message()
        await bot.on_photo(update(msg), ctx)
        self.assertEqual(self.clipboard.writes[0][0], "image")
        self.assertIn("![](attachments/", self.notes())
        self.assertEqual(self.reply(msg), "✓ copied · upload failed")


class DocumentTests(BotTestCase):
    async def test_file_is_saved_and_caption_copied(self):
        ctx = self.build()
        msg = document_message(name="report v1.pdf", caption="the report")
        await bot.on_document(update(msg), ctx)
        self.assertRegex(self.notes(), r"\[report v1\.pdf\]\(attachments/\d{4}-\d\d-\d\d_\d{6}_report%20v1\.pdf\)\nthe report$")
        self.assertEqual(self.clipboard.writes, [("text", "the report")])
        saved = list((self.root / "notes" / "attachments").iterdir())
        self.assertEqual(saved[0].read_bytes(), b"%PDF-1.4")

    async def test_file_without_caption_is_only_saved(self):
        ctx = self.build()
        msg = document_message()
        await bot.on_document(update(msg), ctx)
        self.assertEqual(self.clipboard.writes, [])
        self.assertEqual(self.reply(msg), "✓ saved")

    async def test_image_document_goes_to_clipboard_as_image(self):
        ctx = self.build()
        msg = document_message(name="shot.png", mime="image/png", payload=png_bytes())
        await bot.on_document(update(msg), ctx)
        self.assertEqual(self.clipboard.writes[0][0], "image")
        self.assertRegex(self.notes(), r"!\[\]\(attachments/.*_shot\.png\)$")

    async def test_path_traversal_in_name_is_neutralised(self):
        ctx = self.build()
        await bot.on_document(update(document_message(name="../../evil.sh")), ctx)
        saved = list((self.root / "notes" / "attachments").iterdir())
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].name.endswith("_evil.sh"))


class CommandTests(BotTestCase):
    async def test_start_shows_status(self):
        ctx = self.build()
        msg = message(text="/start")
        await bot.cmd_start(update(msg), ctx)
        text = self.reply(msg)
        self.assertIn("chat id: 123", text)
        self.assertIn("clipboard: fake", text)

    async def test_id_answers_anyone(self):
        ctx = self.build()
        msg = message(text="/id", chat_id=999)
        await bot.cmd_id(update(msg), ctx)
        self.assertEqual(self.reply(msg), "chat id: 999")

    async def test_today(self):
        ctx = self.build()
        msg = message(text="/today")
        await bot.cmd_today(update(msg), ctx)
        self.assertEqual(self.reply(msg), "nothing today")
        await bot.on_text(update(message(text="entry")), ctx)
        msg = message(text="/today")
        await bot.cmd_today(update(msg), ctx)
        self.assertIn("entry", self.reply(msg))


class AssemblyTests(unittest.TestCase):
    def test_build_application_registers_handlers(self):
        config = Config.from_env({"TELEGRAM_BOT_TOKEN": "1:x", "CLIPBOARD": "off",
                                  "TELEGRAM_API_BASE": "https://tg.example.com/"})
        services = bot.Services(config, FakeClipboard(), None, None,
                                bot.State(Path(tempfile.mkdtemp()) / "state.json"))
        app = bot.build_application(config, services)
        self.assertEqual(app.bot.base_url, "https://tg.example.com/bot1:x")
        self.assertEqual(len(app.handlers[0]), 7)
        self.assertEqual(len(app.job_queue.jobs()), 1)
        self.assertIs(app.bot_data["services"], services)


if __name__ == "__main__":
    unittest.main()
