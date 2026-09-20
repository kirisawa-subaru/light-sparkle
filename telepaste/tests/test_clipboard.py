import asyncio
import os
import unittest
from pathlib import Path
from unittest import mock

from telepaste.clipboard import Clipboard, ClipboardError, detect_backend


class CommandTests(unittest.TestCase):
    def test_local_unix_backends_run_through_sh(self):
        for backend in ("pbcopy", "wl-copy", "xclip", "xsel"):
            cmd = Clipboard(backend).command("text")
            self.assertEqual(cmd.argv[:2], ("/bin/sh", "-c"))
            self.assertFalse(cmd.via_file)
        self.assertIn("pbcopy", Clipboard("pbcopy").command("text").argv[2])
        self.assertIn("«class PNGf»", Clipboard("pbcopy").command("image").argv[2])
        self.assertIn("/dev/console", Clipboard("pbcopy").command("image").argv[2])
        self.assertIn("--type image/png", Clipboard("wl-copy").command("image").argv[2])
        self.assertIn("-t image/png", Clipboard("xclip").command("image").argv[2])

    def test_forking_tools_redirect_their_output(self):
        for backend in ("wl-copy", "xclip", "xsel"):
            for kind in ("text", "image"):
                if backend == "xsel" and kind == "image":
                    continue
                self.assertIn(">/dev/null 2>&1", Clipboard(backend).command(kind).argv[2])

    def test_xsel_is_text_only(self):
        clipboard = Clipboard("xsel")
        self.assertFalse(clipboard.supports_images)
        with self.assertRaises(ClipboardError):
            clipboard.command("image")

    def test_ssh_wraps_the_same_snippet(self):
        local = Clipboard("pbcopy").command("image").argv[2]
        remote = Clipboard("pbcopy", ssh_host="mac").command("image").argv
        self.assertEqual(remote[0], "ssh")
        self.assertIn("BatchMode=yes", remote)
        self.assertEqual(remote[-2:], ("mac", local))
        self.assertEqual(Clipboard("pbcopy", ssh_host="mac").describe(), "pbcopy on mac")
        with self.assertRaises(ClipboardError):
            Clipboard("powershell", ssh_host="win")

    def test_powershell_uses_temp_file_and_sta(self):
        clipboard = Clipboard("powershell")
        self.assertTrue(clipboard.supports_images)
        for kind in ("text", "image"):
            cmd = clipboard.command(kind)
            self.assertTrue(cmd.via_file)
            self.assertEqual(cmd.argv[0], "powershell.exe")
            self.assertIn("-STA", cmd.argv)
            self.assertIn("$env:TELEPASTE_FILE", cmd.argv[-1])
        self.assertIn("SetImage", clipboard.command("image").argv[-1])

    def test_off_and_unknown(self):
        self.assertFalse(Clipboard("off").enabled)
        self.assertEqual(Clipboard("off").describe(), "off")
        with self.assertRaises(ClipboardError):
            Clipboard("clipboardy")


class DetectTests(unittest.TestCase):
    def test_platforms(self):
        self.assertEqual(detect_backend({}, "darwin", lambda n: None), "pbcopy")
        self.assertEqual(detect_backend({}, "win32", lambda n: None), "powershell")

    def test_linux_prefers_session_matching_tool(self):
        tools = {"wl-copy": "/usr/bin/wl-copy", "xclip": "/usr/bin/xclip", "xsel": "/usr/bin/xsel"}
        which = tools.get
        self.assertEqual(detect_backend({"WAYLAND_DISPLAY": "wayland-0"}, "linux", which), "wl-copy")
        self.assertEqual(detect_backend({"DISPLAY": ":0"}, "linux", which), "xclip")
        self.assertEqual(detect_backend({"DISPLAY": ":0"}, "linux", {"xsel": "/usr/bin/xsel"}.get), "xsel")
        self.assertEqual(detect_backend({}, "linux", {"xclip": "/usr/bin/xclip"}.get), "xclip")
        with self.assertRaises(ClipboardError):
            detect_backend({}, "linux", lambda n: None)


class RunTests(unittest.IsolatedAsyncioTestCase):
    def spawn(self, returncode=0, stderr=b"", communicate=None):
        proc = mock.Mock(returncode=returncode, wait=mock.AsyncMock())
        proc.communicate = communicate or mock.AsyncMock(return_value=(b"", stderr))
        return mock.AsyncMock(return_value=proc), proc

    async def test_text_travels_on_stdin_never_in_argv(self):
        text = "中文 ✅\n'\" $(touch /tmp/no) `whoami`"
        spawn, proc = self.spawn()
        with mock.patch("telepaste.clipboard.asyncio.create_subprocess_exec", spawn):
            await Clipboard("pbcopy").write_text(text)
        proc.communicate.assert_awaited_once_with(text.encode("utf-8"))
        self.assertNotIn(text, " ".join(spawn.call_args.args))
        self.assertIs(spawn.call_args.kwargs["stdin"], asyncio.subprocess.PIPE)

    async def test_failure_reports_exit_and_stderr(self):
        spawn, _ = self.spawn(returncode=3, stderr=b"no desktop session for bob")
        with mock.patch("telepaste.clipboard.asyncio.create_subprocess_exec", spawn):
            with self.assertRaises(ClipboardError) as cm:
                await Clipboard("pbcopy", ssh_host="mac").write_text("x")
        self.assertIn("exit 3", str(cm.exception))
        self.assertIn("no desktop session", str(cm.exception))

    async def test_exit_127_means_not_found(self):
        spawn, _ = self.spawn(returncode=127)
        with mock.patch("telepaste.clipboard.asyncio.create_subprocess_exec", spawn):
            with self.assertRaises(ClipboardError) as cm:
                await Clipboard("xclip").write_text("x")
        self.assertIn("command not found", str(cm.exception))

    async def test_timeout_kills_process(self):
        spawn, proc = self.spawn(communicate=mock.AsyncMock(side_effect=asyncio.TimeoutError))
        proc.returncode = None
        with mock.patch("telepaste.clipboard.asyncio.create_subprocess_exec", spawn):
            with self.assertRaises(ClipboardError) as cm:
                await Clipboard("wl-copy").write_image(b"png")
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()
        self.assertIn("timed out", str(cm.exception))

    async def test_missing_binary(self):
        spawn = mock.AsyncMock(side_effect=FileNotFoundError("ssh"))
        with mock.patch("telepaste.clipboard.asyncio.create_subprocess_exec", spawn):
            with self.assertRaises(ClipboardError):
                await Clipboard("pbcopy", ssh_host="mac").write_text("x")

    async def test_off_backend_spawns_nothing(self):
        spawn, _ = self.spawn()
        with mock.patch("telepaste.clipboard.asyncio.create_subprocess_exec", spawn):
            await Clipboard("off").write_text("x")
            await Clipboard("off").write_image(b"x")
        spawn.assert_not_awaited()

    async def test_powershell_payload_goes_through_temp_file(self):
        seen = {}

        async def fake_run(argv, payload, env):
            seen["argv"] = argv
            seen["payload"] = payload
            seen["file"] = Path(env["TELEPASTE_FILE"])
            seen["content"] = seen["file"].read_bytes()

        clipboard = Clipboard("powershell")
        with mock.patch.object(clipboard, "_run", fake_run):
            await clipboard.write_text("héllo\nworld")
        self.assertIsNone(seen["payload"])
        self.assertEqual(seen["content"], "héllo\nworld".encode("utf-8"))
        self.assertTrue(str(seen["file"]).endswith(".txt"))
        self.assertFalse(seen["file"].exists(), "temp file must be removed")
        self.assertEqual(seen["argv"][0], "powershell.exe")


if __name__ == "__main__":
    unittest.main()
