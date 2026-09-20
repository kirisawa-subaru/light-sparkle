import unittest
from pathlib import Path

from telepaste.config import Config, ConfigError

BASE = {"TELEGRAM_BOT_TOKEN": "1:abc"}


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        c = Config.from_env(BASE)
        self.assertEqual(c.allowed_chat_ids, frozenset())
        self.assertEqual(c.clipboard, "auto")
        self.assertIsNone(c.clipboard_ssh_host)
        self.assertEqual(c.clipboard_max_age, 120)
        self.assertEqual(c.clipboard_photo, "image")
        self.assertIsNone(c.journal_dir)
        self.assertIsNone(c.s3)
        self.assertEqual(c.state_file, Path.home() / ".telepaste" / "state.json")

    def test_token_required(self):
        with self.assertRaises(ConfigError):
            Config.from_env({})

    def test_ids_parse_and_reject_garbage(self):
        c = Config.from_env({**BASE, "TELEGRAM_ALLOWED_CHAT_IDS": " 1, -200 ,"})
        self.assertEqual(c.allowed_chat_ids, frozenset({1, -200}))
        with self.assertRaises(ConfigError):
            Config.from_env({**BASE, "TELEGRAM_ALLOWED_CHAT_IDS": "1,abc"})

    def test_ssh_host_needs_explicit_backend(self):
        with self.assertRaises(ConfigError):
            Config.from_env({**BASE, "CLIPBOARD_SSH_HOST": "mac"})
        with self.assertRaises(ConfigError):
            Config.from_env({**BASE, "CLIPBOARD_SSH_HOST": "mac", "CLIPBOARD": "powershell"})
        c = Config.from_env({**BASE, "CLIPBOARD_SSH_HOST": "mac", "CLIPBOARD": "pbcopy"})
        self.assertEqual((c.clipboard, c.clipboard_ssh_host), ("pbcopy", "mac"))

    def test_unknown_backend_and_photo_mode(self):
        with self.assertRaises(ConfigError):
            Config.from_env({**BASE, "CLIPBOARD": "xyz"})
        with self.assertRaises(ConfigError):
            Config.from_env({**BASE, "CLIPBOARD_PHOTO": "url"})  # needs S3

    def test_s3_settings(self):
        env = {**BASE, "S3_BUCKET": "b", "S3_ACCESS_KEY_ID": "k", "S3_SECRET_ACCESS_KEY": "s",
               "S3_ENDPOINT_URL": "https://cos.ap-beijing.myqcloud.com/",
               "S3_PUBLIC_BASE_URL": "https://img.example.com/", "S3_PREFIX": "/clips/"}
        c = Config.from_env(env)
        self.assertEqual(c.s3.endpoint_url, "https://cos.ap-beijing.myqcloud.com")
        self.assertEqual(c.s3.public_base_url, "https://img.example.com")
        self.assertEqual(c.s3.prefix, "clips")
        self.assertEqual(c.s3.url_expire, 7 * 24 * 3600)
        self.assertEqual(c.clipboard_photo, "url")
        self.assertEqual(Config.from_env({**env, "CLIPBOARD_PHOTO": "markdown"}).clipboard_photo,
                         "markdown")
        with self.assertRaises(ConfigError):
            Config.from_env({**BASE, "S3_BUCKET": "b"})
        with self.assertRaises(ConfigError):
            Config.from_env({**env, "S3_PUBLIC_BASE_URL": "img.example.com"})
        with self.assertRaises(ConfigError):
            Config.from_env({**env, "S3_URL_EXPIRE": "0"})

    def test_timezone(self):
        c = Config.from_env({**BASE, "JOURNAL_TZ": "Asia/Shanghai", "JOURNAL_DIR": "~/notes"})
        self.assertEqual(c.journal_tz_name, "Asia/Shanghai")
        self.assertEqual(c.journal_dir, Path.home() / "notes")
        with self.assertRaises(ConfigError):
            Config.from_env({**BASE, "JOURNAL_TZ": "Mars/Olympus"})
        self.assertTrue(Config.from_env(BASE).journal_tz_name)


if __name__ == "__main__":
    unittest.main()
