"""Run the real /bin/sh command path against stub clipboard tools on PATH.
No display server needed: the stubs capture stdin to a file and, like the
real xclip / wl-copy, leave a background child holding stdout and stderr."""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from telepaste.clipboard import Clipboard, ClipboardError

STUB = """#!/bin/sh
printf '%s\\n' "$*" > "$TELEPASTE_CAPTURE.args"
cat > "$TELEPASTE_CAPTURE"
# keep a child alive that inherits our stdout/stderr, as the real tools do
(sleep 20 &)
exit ${TELEPASTE_STUB_EXIT:-0}
"""


@unittest.skipIf(sys.platform.startswith("win"), "POSIX shell path only")
class LocalToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        for tool in ("wl-copy", "xclip", "xsel"):
            path = self.bin / tool
            path.write_text(STUB)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.capture = Path(self.temp.name) / "capture"
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
               "TELEPASTE_CAPTURE": str(self.capture)}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)

    async def test_text_reaches_each_tool_verbatim_without_hanging(self):
        text = "中文 ✅ $(touch /tmp/should-not-exist) `id`\nline 2"
        expected_args = {"wl-copy": "", "xclip": "-selection clipboard -i",
                         "xsel": "--clipboard --input"}
        for tool, args in expected_args.items():
            self.capture.unlink(missing_ok=True)
            await Clipboard(tool, timeout=3.0).write_text(text)
            self.assertEqual(self.capture.read_text(encoding="utf-8"), text, tool)
            self.assertEqual(Path(f"{self.capture}.args").read_text().strip(), args, tool)

    async def test_image_bytes_and_mime_flags(self):
        png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
        await Clipboard("wl-copy", timeout=3.0).write_image(png)
        self.assertEqual(self.capture.read_bytes(), png)
        self.assertIn("--type image/png", Path(f"{self.capture}.args").read_text())
        await Clipboard("xclip", timeout=3.0).write_image(png)
        self.assertIn("-t image/png", Path(f"{self.capture}.args").read_text())

    async def test_nonzero_exit_is_an_error(self):
        with mock.patch.dict(os.environ, {"TELEPASTE_STUB_EXIT": "2"}):
            with self.assertRaises(ClipboardError) as cm:
                await Clipboard("xclip", timeout=3.0).write_text("x")
        self.assertIn("exit 2", str(cm.exception))

    async def test_missing_tool_is_reported(self):
        (self.bin / "xclip").unlink()
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}):
            with self.assertRaises(ClipboardError) as cm:
                await Clipboard("xclip", timeout=3.0).write_text("x")
        self.assertIn("not found", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
