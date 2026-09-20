import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telepaste.journal import (Journal, attachment_name, markdown_link, safe_filename,
                               unique_path)

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 17, 12, 34, 56, tzinfo=TZ)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "notes"
        self.journal = Journal(self.root, TZ)

    def test_append_creates_daily_file(self):
        self.journal.append("hello\nworld", NOW)
        self.journal.append("again", NOW)
        text = (self.root / "2026-09-17.md").read_text(encoding="utf-8")
        self.assertEqual(text, "12:34:56 hello\nworld\n\n12:34:56 again\n\n")
        self.assertEqual(self.journal.today_file(NOW).name, "2026-09-17.md")

    def test_attachments_are_unique_and_relative(self):
        a = self.journal.save_attachment(b"1", "2026-09-17_123456.jpg")
        b = self.journal.save_attachment(b"2", "2026-09-17_123456.jpg")
        self.assertEqual(a.name, "2026-09-17_123456.jpg")
        self.assertEqual(b.name, "2026-09-17_123456_1.jpg")
        self.assertEqual(b.read_bytes(), b"2")
        self.assertEqual(self.journal.relative(a), "attachments/2026-09-17_123456.jpg")
        c = self.journal.save_attachment(b"3", "2026-09-17_123456_my file.pdf")
        self.assertEqual(self.journal.relative(c), "attachments/2026-09-17_123456_my%20file.pdf")

    def test_read_today_empty(self):
        self.assertEqual(self.journal.read_today(), "")

    def test_attachment_name(self):
        self.assertEqual(attachment_name(NOW, ".jpg"), "2026-09-17_123456.jpg")
        self.assertEqual(attachment_name(NOW, "", "../../etc/passwd"), "2026-09-17_123456_passwd")
        self.assertEqual(attachment_name(NOW, "", "a\x00b.txt"), "2026-09-17_123456_a b.txt")

    def test_helpers(self):
        self.assertEqual(safe_filename(""), "file")
        self.assertEqual(safe_filename(".."), "file")
        self.assertEqual(len(safe_filename("x" * 300 + ".png")), 120)
        self.assertEqual(markdown_link("a [b]", "u"), "[a \\[b\\]](u)")
        p = Path(self.temp.name) / "z.txt"
        self.assertEqual(unique_path(p), p)
        p.write_text("x")
        self.assertEqual(unique_path(p).name, "z_1.txt")


if __name__ == "__main__":
    unittest.main()
