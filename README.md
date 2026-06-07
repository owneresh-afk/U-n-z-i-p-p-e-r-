# ⚡ ESH UnZipper Bot

```
╔══════════════════════════════════════════════════════╗
║         ESH UnZipper Bot  —  v3.1.0                ║
║         Author   : @iam_esh  (Telegram)             ║
║         Copyright: © 2026 ESH · All rights reserved ║
╚══════════════════════════════════════════════════════╝
```

> A fast, naughty-cute Japanese anime girl Telegram bot that extracts
> **any** archive format and sends the files back to you~
> Built with raw Bot API requests (no wrapper), py7zr, and pure stdlib.

---

## 📁 Files in this folder

| File | Purpose |
|------|---------|
| `bot.py` | Main bot — all handlers, extraction engine, long-poll loop |
| `config.py` | Settings — token, owner ID, limits, supported formats |
| `database.py` | SQLite persistence — users, licences, global stats |
| `keep_alive.py` | Flask ping server for Render / UptimeRobot uptime monitoring |
| `requirements.txt` | Python dependencies |
| `bot_data.db` | Auto-created SQLite database (gitignored) |

---

## 🚀 Quick Start

### 1 — Install system packages

```bash
# Ubuntu / Debian
sudo apt install unrar p7zip-full cabextract

# Termux (Android)
pkg install unrar p7zip cabextract

# macOS
brew install unrar p7zip
```

### 2 — Install Python packages

```bash
pip install -r requirements.txt
```

### 3 — Set your token

```bash
export TELEGRAM_BOT_TOKEN="your_token_here"
# or add it to a .env file
```

### 4 — Run

```bash
python bot.py
```

---

## 🗜️ Extraction Engine

```
Format received
     │
     ▼
[magic-byte detection] ← reads first bytes, ignores extension lies
     │
     ├─ .zip          → Python zipfile  (stdlib, always works)
     ├─ .tar / .tar.* → Python tarfile r:* (stdlib, all compression)
     │                  └─ subprocess tar fallback
     ├─ .gz           → Python gzip     (stdlib, single-file)
     ├─ .bz2          → Python bz2      (stdlib, single-file)
     ├─ .xz           → Python lzma     (stdlib, single-file)
     ├─ .7z           → py7zr           (pure Python, NO system tool)
     ├─ .rar          → rarfile + unrar binary
     │                  └─ subprocess unrar / bsdtar fallback
     └─ .cab / .iso   → bsdtar / 7z / cabextract (system tools)
```

**Format detection is done by magic bytes (file header), not the filename extension.**  
A file called `totally_not_a_zip.rar` will still be correctly identified as ZIP if it has ZIP magic bytes.

---

## 🔑 Licence System

```
Admin generates key  →  user redeems with /redeem KEY
     │                           │
  Admin Panel                Database
  Gen Keys tab           activates the user
     │                    for chosen duration
  Keys are single-use,
  tied to one Telegram ID
```

Duration formats for key generation: `1H` `30D` `1W` `1MO`

---

## 💬 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Open the main menu |
| `/redeem KEY` | Activate a licence key |
| `/admin` | Admin panel *(owner only)* |
| `/cancel` | Abort current operation |
| `/formats` | List all supported archive formats |

---

## ⚙️ Configuration (`config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `OWNER_ID` | `8731647972` | Your Telegram user ID |
| `BOT_NAME` | `ESH UnZipper` | Display name |
| `MAX_FILE_SIZE` | `50 MB` | Upload size limit |
| `TEMP_DIR` | `/tmp/esh_unzipper_sessions` | Temp session storage |
| `FLASK_PORT` | `8080` | Keep-alive HTTP port |
| `TELEGRAM_BOT_TOKEN` | env var | Your bot token |

---

## 🗄️ Database Schema

```sql
users       — Telegram users, licence status, usage stats
licenses    — Generated keys, duration, who redeemed
bot_stats   — Global totals (archives, files, keys)
```

Database file: `bot_data.db` (auto-created on first run, SQLite)

---

## ☁️ Deployment

### Render (free tier)
- Start command: `python bot/bot.py`
- Set `TELEGRAM_BOT_TOKEN` in environment variables
- Add UptimeRobot → ping `https://your-app.onrender.com/health`

### Termux (Android)
```bash
pkg install python unrar p7zip
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN="token" python bot.py
```

### Railway / Fly.io
```bash
# Set token in dashboard, then:
python bot/bot.py
```

---

## 🔒 Security Notes

- Sessions auto-deleted after **30 minutes**
- Each licence key is **single-use** (bound to one Telegram ID)
- Bot token is read from **environment variable only** — never hardcode it
- Temp files stored in `/tmp` — cleared on system restart

---

```
╔══════════════════════════════════════════╗
║   Built with ♡ by @iam_esh              ║
║   Telegram: https://t.me/iam_esh        ║
║   © 2026 ESH  ·  All rights reserved   ║
╚══════════════════════════════════════════╝
```
