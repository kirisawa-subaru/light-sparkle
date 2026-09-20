# telepaste

Send something to your own Telegram bot from your phone. A second later it is on
your desktop clipboard: text as text, photos as images. Optionally it also goes
into today's markdown note, and photos can be uploaded to S3-compatible storage
so the thing on your clipboard is a public link.

That is the whole idea: **Telegram as a universal clipboard**. Works from any
phone to any desktop (Android to macOS, iPhone to Linux, anything to Windows),
needs no app on the phone, no shared Wi-Fi, no account besides Telegram, and
runs entirely on your own machine. About 1000 lines of Python.

```
phone ──Telegram──▶ telepaste (your laptop or a server)
                      ├─▶ clipboard   (local, or another machine over SSH)
                      ├─▶ notes/2026-09-17.md + attachments/    (optional)
                      └─▶ S3 / R2 / COS / OSS → link on the clipboard (optional)
```

## Features

- **Text → clipboard.** Unicode, newlines, shell metacharacters: all just text.
- **Photo → clipboard as an image** (PNG, EXIF orientation applied). Paste into
  a chat, a document, an image editor.
- **Files → saved** next to your notes; images sent as files also hit the clipboard.
- **Daily notes.** `JOURNAL_DIR/YYYY-MM-DD.md` with timestamped entries and
  relative links to `attachments/`. Drop the folder into an Obsidian vault.
- **Image hosting.** With S3-compatible credentials (AWS S3, Cloudflare R2,
  Tencent COS, Aliyun OSS, MinIO) a photo becomes a URL on your clipboard, or a
  ready-to-paste `![](url)`.
- **Remote clipboard.** Run the bot on a server or a headless box and push to
  the clipboard of your Mac or Linux desktop over SSH.
- **Safe by construction.** Chat allowlist; payloads travel on stdin or in a
  temp file and never get interpolated into a shell; messages older than two
  minutes (queued during an outage) are saved but do not overwrite your clipboard.

| Clipboard target | Backend | Text | Image | Status |
|---|---|---|---|---|
| macOS | `pbcopy` + `osascript` | ✓ | ✓ | verified over SSH (round-trip of text and a PNG); local mode runs the same commands |
| Linux, Wayland | `wl-copy` (wl-clipboard) | ✓ | ✓ | command path verified against stub tools; no live desktop test yet |
| Linux, X11 | `xclip` | ✓ | ✓ | same as above |
| Linux, X11 | `xsel` | ✓ | – | same as above |
| Windows 10/11 | PowerShell 5.1 (`Set-Clipboard`, WinForms) | ✓ | ✓ | written without a Windows machine; untested |

Reports for the unverified rows are very welcome.

## Quick start

1. Talk to [@BotFather](https://t.me/BotFather), `/newbot`, keep the token.
2. Install from this repository (Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)). No PyPI release is required:

   ```sh
   git clone https://github.com/kirisawa-subaru/light-sparkle.git
   cd light-sparkle/telepaste
   uv tool install .
   ```

   For optional image uploads, use `uv tool install ".[s3]"` instead of the last command. If you use pipx, `pipx install .` (or `pipx install ".[s3]"`) works from the same directory. Make sure the tool's executable directory is on your shell's PATH.

   Linux needs a clipboard tool: `wl-clipboard` on Wayland, `xclip` on X11.

3. Configure:

   ```sh
   mkdir -p ~/.telepaste
   cp .env.example ~/.telepaste/.env
   $EDITOR ~/.telepaste/.env        # set TELEGRAM_BOT_TOKEN
   telepaste doctor
   ```

4. Run `telepaste`, send your bot any message. It answers with your chat id.
   Put that id in `TELEGRAM_ALLOWED_CHAT_IDS`, restart, send it again: `✓ copied`.

5. Keep it running: see [Run as a service](#run-as-a-service).

## Configuration

Everything is an environment variable, read from `--env FILE`, `$TELEPASTE_ENV`,
`./.env` or `~/.telepaste/.env` (first one found). See [`.env.example`](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | required | Token from @BotFather |
| `TELEGRAM_ALLOWED_CHAT_IDS` | empty | Comma-separated chat ids. Empty = pairing mode: every sender is told their id and nothing is stored |
| `TELEGRAM_PROXY` | – | HTTP or SOCKS proxy for Telegram |
| `TELEGRAM_API_BASE` | – | Alternative Bot API base URL |
| `CLIPBOARD` | `auto` | `pbcopy`, `wl-copy`, `xclip`, `xsel`, `powershell`, `off`. `auto` picks by platform and session |
| `CLIPBOARD_SSH_HOST` | – | Push to this ssh host's clipboard instead; needs an explicit `CLIPBOARD` for that host |
| `CLIPBOARD_MAX_AGE` | `120` | Messages older than this (seconds) are saved but not copied |
| `CLIPBOARD_PHOTO` | `image` (`url` when S3 is set) | What a photo puts on the clipboard: `image`, `url`, `markdown` |
| `JOURNAL_DIR` | – | Notes folder. Unset = no notes, clipboard only |
| `JOURNAL_TZ` | system | IANA timezone for timestamps and file names |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | – | Upload target. Endpoint examples: `https://<account>.r2.cloudflarestorage.com`, `https://cos.ap-beijing.myqcloud.com`, `https://oss-cn-hangzhou.aliyuncs.com` |
| `S3_PUBLIC_BASE_URL` | – | Public origin or CDN in front of the bucket. Unset = presigned links |
| `S3_PREFIX` | empty | Key prefix |
| `S3_URL_EXPIRE` | `604800` | Presigned link lifetime, seconds |
| `STATE_FILE` | `~/.telepaste/state.json` | Where `/quiet` is remembered |

## Commands in Telegram

`/today` shows today's note, `/quiet` toggles replies (everything still gets
copied and saved), `/id` shows the chat id, `/help` shows status.

## Platform notes

**macOS.** Nothing to install. The bot (or the SSH user, in remote mode) must be
logged into the desktop; telepaste checks that the console belongs to that user
and fails with a clear message otherwise.

**Linux.** Install `wl-clipboard` (Wayland) or `xclip` (X11). A clipboard only
exists inside a graphical session, so a systemd user service must know your
display: uncomment `WAYLAND_DISPLAY` or `DISPLAY` in `deploy/telepaste.service`.
`telepaste doctor` tells you which backend was picked.

**Windows.** Uses Windows PowerShell 5.1, present on every Windows 10/11.
Text goes through `Set-Clipboard`, images through `System.Windows.Forms.Clipboard`.
Written without a Windows machine at hand; `deploy/install-windows-task.ps1`
registers a logon task. If it misbehaves, `telepaste clip` is the quickest way
to isolate the clipboard step (see below).

## Clipboard on another machine

Run the bot wherever is convenient and keep the clipboard where you paste:

```
CLIPBOARD_SSH_HOST=macbook     # an alias in ~/.ssh/config with key auth
CLIPBOARD=pbcopy               # what that machine uses: pbcopy, wl-copy, xclip, xsel
```

telepaste runs `ssh -T -o BatchMode=yes macbook '<clipboard command>'` and feeds
the payload on stdin. The remote side needs nothing installed beyond its normal
clipboard tool. Host keys are accepted on first contact (`accept-new`); add the
host to `known_hosts` yourself if you want stricter behaviour.

## Notes layout

```
JOURNAL_DIR/
├── 2026-09-17.md
└── attachments/
    ├── 2026-09-17_093012.jpg
    └── 2026-09-17_101540_report v1.pdf
```

```markdown
09:30:12 ![](attachments/2026-09-17_093012.jpg)
whiteboard after standup

10:15:40 [report v1.pdf](attachments/2026-09-17_101540_report%20v1.pdf)

10:16:03 call the dentist
```

With uploads enabled the links are the object URLs instead.

## Image hosting

```
S3_BUCKET=clips-12345
S3_ENDPOINT_URL=https://cos.ap-beijing.myqcloud.com
S3_REGION=ap-beijing
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_PUBLIC_BASE_URL=https://img.example.com
S3_PREFIX=telepaste
CLIPBOARD_PHOTO=markdown        # or url (default) or image
```

Photos and files are uploaded as `PREFIX/YYYY-MM-DD/<filename>` with the right
content type; the reply contains the link. Give the key PutObject on that bucket
only. If the upload fails the local copy is kept and the reply says so.

## Run as a service

- **Linux:** `deploy/telepaste.service` (systemd user unit; instructions inside).
- **macOS:** `deploy/com.telepaste.bot.plist` (launchd agent; edit the paths).
- **Windows:** `deploy/install-windows-task.ps1` (Scheduled Task at logon).

If Telegram is unreachable at boot, telepaste waits with backoff instead of
crash-looping; if it becomes unreachable later, it exits after three failed
heartbeats so the service manager restarts it.

## Troubleshooting

```sh
telepaste doctor                       # config, clipboard tool, ssh, notes dir, upload, Telegram
echo "hello" | telepaste clip          # exercise the clipboard path alone
telepaste clip --image < photo.jpg     # same for images
```

Telegram blocked on your network? Set `TELEGRAM_PROXY`, or point
`TELEGRAM_API_BASE` at a relay you control.

## Development

```sh
git clone https://github.com/kirisawa-subaru/light-sparkle.git
cd light-sparkle/telepaste
uv venv && uv pip install -e ".[s3]"
.venv/bin/python -m unittest discover -s tests -v
```

## License

MIT.
