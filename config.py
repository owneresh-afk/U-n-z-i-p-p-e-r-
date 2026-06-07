"""
╔══════════════════════════════════════════════════════════════════╗
║         ESH UnZipper Bot  —  config.py                         ║
║         Version  : 3.1.0                                        ║
║         Author   : @iam_esh  (Telegram)                        ║
║         Copyright: © 2026 ESH · All rights reserved            ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os

# ── Bot identity ──────────────────────────────────────────────────────────────
OWNER_ID    = 8731647972
BOT_NAME    = "ESH UnZipper"
BOT_VERSION = "3.1.0"
BOT_AUTHOR  = "@iam_esh"

# ── Limits ────────────────────────────────────────────────────────────────────
MAX_FILE_SIZE = 50 * 1024 * 1024   # 50 MB

# ── Temp storage ──────────────────────────────────────────────────────────────
TEMP_DIR = "/tmp/esh_unzipper_sessions"

# ── Supported archive extensions ─────────────────────────────────────────────
SUPPORTED_FORMATS = [
    ".zip", ".7z", ".rar",
    ".tar", ".tar.gz", ".tar.bz2", ".tar.xz",
    ".tgz", ".tbz2", ".txz",
    ".gz", ".bz2", ".xz",
    ".cab", ".iso",
]

# ── Credentials — set via environment variable ────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ── Keep-alive server port ────────────────────────────────────────────────────
FLASK_PORT = int(os.environ.get("PORT", 8080))
