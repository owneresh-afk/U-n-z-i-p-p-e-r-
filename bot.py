"""
╔══════════════════════════════════════════════════════════════════╗
║         ESH UnZipper Bot  —  bot.py                            ║
║         Version  : 3.1.0                                        ║
║         Author   : @iam_esh  (Telegram)                        ║
║         Copyright: © 2026 ESH · All rights reserved            ║
║                                                                  ║
║  Raw Bot API (requests) · magic-byte detection · py7zr          ║
║  No python-telegram-bot wrapper needed                          ║
╚══════════════════════════════════════════════════════════════════╝
"""

# ── stdlib ────────────────────────────────────────────────────────────────────
import os
import sys
import time
import shutil
import logging
import traceback
import zipfile
import tarfile
import gzip
import bz2
import lzma
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── third-party ───────────────────────────────────────────────────────────────
import requests

# py7zr — pure Python 7-zip (no system tool required)
try:
    import py7zr
    HAS_7Z = True
except ImportError:
    HAS_7Z = False

# rarfile — needs 'unrar' binary on PATH
try:
    import rarfile
    rarfile.UNRAR_TOOL = "unrar"
    HAS_RAR = True
except ImportError:
    HAS_RAR = False

# ── local modules ─────────────────────────────────────────────────────────────
from config import (
    OWNER_ID, BOT_NAME, BOT_VERSION, BOT_AUTHOR,
    MAX_FILE_SIZE, TEMP_DIR, SUPPORTED_FORMATS,
    TELEGRAM_BOT_TOKEN,
)
import database as db
from keep_alive import keep_alive

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
STATE_IDLE               = "idle"
STATE_WAITING_FILE       = "waiting_file"
STATE_WAITING_PASSWORD   = "waiting_password"
STATE_SELECTING_FOLDERS  = "selecting_folders"
STATE_ADMIN_MENU         = "admin_menu"
STATE_ADMIN_KEY_COUNT    = "admin_key_count"
STATE_ADMIN_KEY_DURATION = "admin_key_duration"
STATE_ADMIN_BROADCAST    = "admin_broadcast"

# Per-user state & session data stored in memory
user_states: dict[int, str]  = {}
user_data:   dict[int, dict] = {}

# ── Bot API raw helpers ───────────────────────────────────────────────────────

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"

TIMEOUT      = 30
POLL_TIMEOUT = 25


def _api(method: str, **kwargs) -> dict:
    """POST to Bot API. Always returns a dict (never raises)."""
    try:
        r = requests.post(f"{BASE_URL}/{method}", json=kwargs, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error(f"[API] {method} failed: {exc}")
        return {"ok": False, "description": str(exc)}


def _api_mp(method: str, data: dict, files: dict) -> dict:
    """Multipart POST — for sendDocument."""
    try:
        r = requests.post(
            f"{BASE_URL}/{method}", data=data, files=files, timeout=120
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error(f"[API MP] {method} failed: {exc}")
        return {"ok": False, "description": str(exc)}


def get_updates(offset: int) -> list:
    try:
        r = requests.post(
            f"{BASE_URL}/getUpdates",
            json={"offset": offset, "timeout": POLL_TIMEOUT,
                  "allowed_updates": ["message", "callback_query"]},
            timeout=POLL_TIMEOUT + 5,
        )
        data = r.json()
        return data.get("result", []) if data.get("ok") else []
    except Exception as exc:
        logger.warning(f"[POLL] {exc}")
        return []

# ═══════════════════════════════════════════════════════════════════════════════
#  ✦  PERSONALITY  —  Happy naughty Japanese anime girl  ✦
#  Every message the bot sends should feel like it came from her~
# ═══════════════════════════════════════════════════════════════════════════════

# Kawaii kaomoji pool — randomly picked to sprinkle in messages
_KAOMOJI = [
    "(◕‿◕✿)", "(づ ᴗ _ᴗ)づ♡", "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧",
    "(*≧ω≦)", "(⌒▽⌒)☆", "＼(≧▽≦)／",
    "(˘▾˘~)", "(*ﾉ▽ﾉ)", "( ˘ ³˘)♥",
    "(｡♥‿♥｡)", "ʕ•ᴥ•ʔ", "(✿◠‿◠)",
]

import random

def _kao() -> str:
    return random.choice(_KAOMOJI)


# ── No-subscription gate message (naughty girl style) ────────────────────────
def no_sub_msg() -> str:
    return (
        f"Ara ara~ {_kao()}\n"
        f"╔══[ ✦ Onii-chan... ]══╗\n"
        f"║                       ║\n"
        f"║  Mou~ you sneaky one~ ║\n"
        f"║  You don't have a     ║\n"
        f"║  subscription yet!    ║\n"
        f"║                       ║\n"
        f"╚═══════════════════════╝\n\n"
        f"Ehehe~ I can't let you in without a key, naughty~\n"
        f"Go get one and come back to me, okay? {_kao()}\n\n"
        f"[ /redeem YOUR\\-KEY ] ← tap tap~"
    )


# ── Terminal-style UI helpers ─────────────────────────────────────────────────

def _box(title: str, lines: list[str], width: int = 32) -> str:
    """Draw a terminal-style box with a title and body lines."""
    top  = f"╔══[ {title} ]"
    top  = top + "═" * max(2, width - len(top)) + "╗"
    body = "\n".join(f"║  {ln:<{width-4}}║" for ln in lines)
    bot  = "╚" + "═" * (width - 2) + "╝"
    return f"{top}\n{body}\n{bot}"


def _bar(current: int, total: int, width: int = 18) -> str:
    """Block-character progress bar: ▓▓▓▓▒░░░░ 50%"""
    pct    = current / max(total, 1)
    filled = int(pct * width)
    half   = max(0, min(1, width - filled))   # transition block
    empty  = width - filled - half
    bar    = "▓" * filled + "▒" * half + "░" * empty
    return f"`[{bar}]` {int(pct*100)}%"


def _ok(text: str)  -> str: return f"[+] {text}"
def _err(text: str) -> str: return f"[✗] {text}"
def _inf(text: str) -> str: return f"[>] {text}"
def _warn(text: str)-> str: return f"[!] {text}"
def _sep(n: int = 28) -> str: return "─" * n


# ── Kawaii wrappers for common status messages ────────────────────────────────

def msg_downloading(pct: int = 0) -> str:
    return (
        f"Nyaa~ downloading your file~ {_kao()}\n"
        f"{_bar(pct, 100)}"
    )

def msg_extracting(pct: int = 30) -> str:
    return (
        f"Haaa~ extracting for you~ {_kao()}\n"
        f"{_bar(pct, 100)}"
    )

def msg_scanning() -> str:
    return f"Hmm let me peek inside~ {_kao()}\n{_bar(70, 100)}"

def msg_sending(i: int, total: int, sent: int, failed: int) -> str:
    return (
        f"Sending files~ do your best! {_kao()}\n"
        f"{_bar(i, total)}\n"
        f"`[+] Sent: {sent}   [✗] Failed: {failed}`"
    )

def msg_done(sent: int) -> str:
    return (
        f"Kyaa~ All done onii-chan! {_kao()}\n"
        f"╔══[ COMPLETE ]═══════════╗\n"
        f"║  [+] Files sent: {str(sent):<7} ║\n"
        f"╚═════════════════════════╝"
    )

def msg_wrong_password() -> str:
    return (
        f"Mou~ that password is wrong! {_kao()}\n"
        f"`[✗]` None of your passwords worked~\n\n"
        f"Send the correct one, or tap cancel okay~?"
    )

def msg_password_ok() -> str:
    return f"Yatta! Password accepted! {_kao()} Now let me unpack~"

def msg_ask_file() -> str:
    return (
        f"Ooh ooh send me your archive~ {_kao()}\n"
        f"{_sep()}\n"
        f"I know these formats:\n"
        f"`.zip` `.7z` `.rar` `.tar` `.tar.gz`\n"
        f"`.tar.bz2` `.tar.xz` `.gz` `.bz2` `.xz`\n"
        f"`.cab` `.iso` …and more!\n"
        f"{_sep()}\n"
        f"Max size: `{_fmt_size(MAX_FILE_SIZE)}`\n\n"
        f"Send the file now, or /cancel~"
    )

def msg_ask_password() -> str:
    return (
        f"Kyaa~ this archive is locked! {_kao()}\n"
        f"`[!]` Send me the password~\n\n"
        f"_Send multiple passwords on separate lines_\n"
        f"_if the files inside have different passwords~_"
    )

def msg_error(reason: str) -> str:
    return (
        f"Ugh, something went wrong... {_kao()}\n"
        f"╔══[ ERROR ]═══════════════╗\n"
        f"║ {_err(reason[:26]):<30}║\n"
        f"╚══════════════════════════╝\n\n"
        f"_Try again or use /cancel~_"
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  Keyboard builders  (Bot API 9.4 — style field)
# ═══════════════════════════════════════════════════════════════════════════════

def _btn(text: str, cb: str, style: str = "primary") -> dict:
    return {"text": text, "callback_data": cb, "style": style}


def main_menu_kb(is_admin: bool = False) -> dict:
    rows = [
        [_btn("▸ Unzip File",   "menu_unzip",   "success")],
        [_btn("▸ My Profile",   "menu_profile", "primary"),
         _btn("▸ My Stats",     "menu_stats",   "primary")],
        [_btn("▸ Formats",      "menu_formats", "primary"),
         _btn("▸ Help",         "menu_help",    "primary")],
        [_btn("▸ Support",      "menu_support", "primary")],
    ]
    if is_admin:
        rows.append([_btn("▸ Admin Panel", "admin_panel", "danger")])
    return {"inline_keyboard": rows}


def back_kb() -> dict:
    return {"inline_keyboard": [[_btn("◂ Main Menu", "back_main", "primary")]]}


def admin_kb() -> dict:
    return {
        "inline_keyboard": [
            [_btn("▸ Stats",        "admin_stats",     "primary"),
             _btn("▸ All Users",    "admin_users",     "primary")],
            [_btn("▸ Active Users", "admin_active",    "success"),
             _btn("▸ Lookup",       "admin_lookup",    "primary")],
            [_btn("▸ Gen Keys",     "admin_gen_keys",  "success"),
             _btn("▸ Broadcast",    "admin_broadcast", "primary")],
            [_btn("◂ Main Menu",    "back_main",       "danger")],
        ]
    }


def cancel_kb() -> dict:
    return {"inline_keyboard": [[_btn("✕ Cancel", "back_main", "danger")]]}


def folder_kb(top_dirs: dict, selected: set, session_id: str) -> dict:
    rows = []
    for name, files in top_dirs.items():
        tick = "▣" if name in selected else "▢"
        style = "success" if name in selected else "primary"
        rows.append([_btn(
            f"{tick} {name[:26]}  ({len(files)}f)",
            f"folder_toggle:{session_id}:{name}",
            style,
        )])
    rows.append([
        _btn("▣ All",  f"folder_all:{session_id}",     "success"),
        _btn("▢ None", f"folder_none:{session_id}",    "primary"),
    ])
    rows.append([
        _btn("▸ Extract Selected", f"folder_confirm:{session_id}", "success"),
        _btn("✕ Cancel",           "folder_cancel",                "danger"),
    ])
    return {"inline_keyboard": rows}

# ═══════════════════════════════════════════════════════════════════════════════
#  Messaging helpers
# ═══════════════════════════════════════════════════════════════════════════════

def send(chat_id: int, text: str, kb: dict = None,
         parse_mode: str = "Markdown") -> dict:
    p = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if kb:
        p["reply_markup"] = kb
    return _api("sendMessage", **p)


def edit(chat_id: int, msg_id: int, text: str,
         kb: dict = None, parse_mode: str = "Markdown") -> dict:
    p = {"chat_id": chat_id, "message_id": msg_id,
         "text": text, "parse_mode": parse_mode}
    if kb:
        p["reply_markup"] = kb
    return _api("editMessageText", **p)


def answer_cb(cbq_id: str, text: str = "", alert: bool = False) -> dict:
    return _api("answerCallbackQuery",
                callback_query_id=cbq_id, text=text, show_alert=alert)


def send_doc(chat_id: int, fpath: str, caption: str = "") -> dict:
    with open(fpath, "rb") as f:
        return _api_mp(
            "sendDocument",
            data={"chat_id": str(chat_id), "caption": caption},
            files={"document": (os.path.basename(fpath), f)},
        )


def dl_file(file_id: str, dest: str) -> bool:
    try:
        resp = _api("getFile", file_id=file_id)
        if not resp.get("ok"):
            return False
        url = f"{FILE_URL}/{resp['result']['file_path']}"
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
        return True
    except Exception as exc:
        logger.error(f"dl_file: {exc}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
#  Extraction engine
#  Priority: stdlib → py7zr → subprocess (tar/unzip) → rarfile → error
# ═══════════════════════════════════════════════════════════════════════════════

MAGIC_SIGNATURES = [
    (0,     b"PK\x03\x04",          ".zip"),
    (0,     b"PK\x05\x06",          ".zip"),
    (0,     b"Rar!\x1a\x07\x00",    ".rar"),
    (0,     b"Rar!\x1a\x07\x01",    ".rar"),
    (0,     b"7z\xbc\xaf\x27\x1c",  ".7z"),
    (0,     b"\x1f\x8b",            ".gz"),
    (0,     b"BZh",                 ".bz2"),
    (0,     b"\xfd7zXZ\x00",        ".xz"),
    (0,     b"MSCF",                ".cab"),
    (257,   b"ustar",               ".tar"),
    (32769, b"CD001",               ".iso"),
    (34817, b"CD001",               ".iso"),
    (36865, b"CD001",               ".iso"),
]


def _magic(path: str) -> Optional[str]:
    """
    Detect archive type from first bytes (magic numbers).
    Returns canonical extension or None if unknown.
    Wraps ALL calls in try/except so a bad file never crashes detection.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(37000)
    except OSError:
        return None

    for off, sig, fmt in MAGIC_SIGNATURES:
        end = off + len(sig)
        if len(head) >= end and head[off:end] == sig:
            # For a bare .gz hit, check whether the inner stream is a tar
            if fmt == ".gz":
                try:
                    if tarfile.is_tarfile(path):
                        return ".tar.gz"
                except Exception:
                    pass          # corrupt gzip — still treat as plain .gz
            return fmt
    return None


def detect_fmt(filename: str, filepath: str = None) -> Optional[str]:
    """
    Two-phase format detection:
      1. Magic bytes (reliable, beats extensions)
      2. File-name extension fallback
    Compound tar extensions (.tar.gz etc.) are resolved via filename
    when magic confirms the outer compression type.
    """
    nl = (filename or "").lower()

    if filepath and os.path.isfile(filepath):
        try:
            magic = _magic(filepath)
        except Exception:
            magic = None

        if magic:
            # Resolve compound tar variants from extension
            if magic in (".gz", ".tar.gz"):
                if nl.endswith(".tar.gz") or nl.endswith(".tgz"):
                    return ".tar.gz"
                return magic          # plain .gz
            if magic == ".bz2":
                if nl.endswith(".tar.bz2") or nl.endswith(".tbz2"):
                    return ".tar.bz2"
                return ".bz2"
            if magic == ".xz":
                if nl.endswith(".tar.xz") or nl.endswith(".txz"):
                    return ".tar.xz"
                return ".xz"
            if magic == ".tar":
                # ustar marker found — check for compound name anyway
                for comp in (".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                             ".tar.xz", ".txz"):
                    if nl.endswith(comp):
                        return comp
                return ".tar"
            return magic

    # Extension-only fallback (pre-download check, or magic returned None)
    for ext in sorted(SUPPORTED_FORMATS, key=len, reverse=True):
        if nl.endswith(ext):
            return ext
    return None


def _cmd(args: list, cwd: str = None) -> tuple[bool, str]:
    """Run a subprocess command. Returns (success, stderr)."""
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=180, cwd=cwd
        )
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or r.stdout or "non-zero exit").strip()
    except FileNotFoundError:
        return False, f"command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return False, "extraction timed out"
    except Exception as e:
        return False, str(e)


def needs_password(path: str, fmt: str) -> bool:
    try:
        if fmt == ".zip":
            with zipfile.ZipFile(path) as zf:
                return any(i.flag_bits & 0x1 for i in zf.infolist())
        if fmt == ".7z" and HAS_7Z:
            with py7zr.SevenZipFile(path, mode="r") as sz:
                return sz.needs_password()
        if fmt == ".rar" and HAS_RAR:
            with rarfile.RarFile(path) as rf:
                return rf.needs_password()
    except Exception:
        pass
    return False


def extract_archive(path: str, out_dir: str, fmt: str,
                    password: bytes = None) -> tuple[bool, str]:
    """
    Extract *path* → *out_dir*.
    Returns (success, user-friendly error string).

    Engine priority per format:
      .zip          → zipfile (stdlib)
      .tar / .tar.* → tarfile (stdlib) → subprocess tar
      .gz/.bz2/.xz  → gzip/bz2/lzma (stdlib) — single-file decompress
      .7z           → py7zr (pure Python)
      .rar          → rarfile + unrar binary
      .cab/.iso     → subprocess bsdtar / 7z (if installed)
    """
    os.makedirs(out_dir, exist_ok=True)
    pwd_str = password.decode("utf-8", errors="replace") if password else None

    # ── ZIP ───────────────────────────────────────────────────────────────────
    if fmt == ".zip":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(out_dir, pwd=password)
            return True, ""
        except RuntimeError as e:
            # bad password gives RuntimeError
            return False, f"Wrong password or corrupt ZIP: {e}"
        except Exception as e:
            return False, str(e)

    # ── TAR family ────────────────────────────────────────────────────────────
    if fmt in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"):
        # 1) Python tarfile — 'r:*' auto-detects gz/bz2/xz compression
        try:
            with tarfile.open(path, "r:*") as tf:
                tf.extractall(out_dir)
            return True, ""
        except tarfile.ReadError as e:
            logger.warning(f"tarfile ReadError ({fmt}): {e}")
        except tarfile.CompressionError as e:
            logger.warning(f"tarfile CompressionError ({fmt}): {e}")
        except Exception as e:
            logger.warning(f"tarfile failed ({fmt}): {e}")
        # 2) subprocess tar fallback (tar binary is always present)
        ok, err = _cmd(["tar", "xf", path, "-C", out_dir])
        if ok:
            return True, ""
        return False, (
            f"Could not extract {os.path.basename(path)}\n"
            f"Error: {err or 'unknown tar error'}\n"
            f"Make sure the file is a valid archive."
        )

    # ── GZIP single-file ──────────────────────────────────────────────────────
    if fmt == ".gz":
        try:
            out_name = os.path.basename(path)
            out_name = out_name[:-3] if out_name.endswith(".gz") else out_name
            out_file = os.path.join(out_dir, out_name or "extracted_file")
            with gzip.open(path, "rb") as fi, open(out_file, "wb") as fo:
                shutil.copyfileobj(fi, fo)
            return True, ""
        except Exception as e:
            return False, str(e)

    # ── BZ2 single-file ───────────────────────────────────────────────────────
    if fmt == ".bz2":
        try:
            out_name = os.path.basename(path)
            out_name = out_name[:-4] if out_name.endswith(".bz2") else out_name
            out_file = os.path.join(out_dir, out_name or "extracted_file")
            with bz2.open(path, "rb") as fi, open(out_file, "wb") as fo:
                shutil.copyfileobj(fi, fo)
            return True, ""
        except Exception as e:
            return False, str(e)

    # ── XZ single-file ────────────────────────────────────────────────────────
    if fmt == ".xz":
        try:
            out_name = os.path.basename(path)
            out_name = out_name[:-3] if out_name.endswith(".xz") else out_name
            out_file = os.path.join(out_dir, out_name or "extracted_file")
            with lzma.open(path, "rb") as fi, open(out_file, "wb") as fo:
                shutil.copyfileobj(fi, fo)
            return True, ""
        except Exception as e:
            return False, str(e)

    # ── 7Z — pure Python via py7zr (NO system tool needed) ───────────────────
    if fmt == ".7z":
        if not HAS_7Z:
            return False, (
                "py7zr not installed!\n"
                "Run: pip install py7zr"
            )
        try:
            with py7zr.SevenZipFile(path, mode="r", password=pwd_str) as sz:
                sz.extractall(path=out_dir)
            return True, ""
        except py7zr.exceptions.PasswordRequired:
            return False, "This .7z archive is password protected — send me the password~"
        except py7zr.exceptions.Bad7zFile as e:
            return False, f"Corrupt or unsupported .7z file: {e}"
        except Exception as e:
            return False, str(e)

    # ── RAR — needs unrar binary ──────────────────────────────────────────────
    if fmt == ".rar":
        # 1) rarfile library (wraps unrar binary)
        if HAS_RAR:
            try:
                with rarfile.RarFile(path) as rf:
                    rf.extractall(out_dir, pwd=password)
                return True, ""
            except rarfile.BadRarFile as e:
                return False, f"Bad RAR file: {e}"
            except rarfile.RarWrongPassword:
                return False, "Wrong password for RAR archive~"
            except rarfile.RarCannotExec:
                pass  # unrar not found, try subprocess
            except Exception as e:
                return False, str(e)

        # 2) subprocess unrar
        cmd = ["unrar", "x", "-o+", path, out_dir + os.sep]
        if pwd_str:
            cmd = ["unrar", "x", f"-p{pwd_str}", "-o+", path, out_dir + os.sep]
        ok, err = _cmd(cmd)
        if ok:
            return True, ""

        # 3) subprocess bsdtar (handles RAR on some systems)
        ok, err2 = _cmd(["bsdtar", "xf", path, "-C", out_dir])
        if ok:
            return True, ""

        return False, (
            "Cannot extract RAR — unrar is not installed!\n\n"
            "Install it:\n"
            "  Ubuntu:  apt install unrar\n"
            "  Termux:  pkg install unrar\n"
            "  macOS:   brew install unrar"
        )

    # ── CAB / ISO / unknown → try system tools ────────────────────────────────
    for tool_cmd in (
        ["bsdtar",   "xf",  path, "-C", out_dir],
        ["7z",       "x",   path, f"-o{out_dir}", "-y"],
        ["7za",      "x",   path, f"-o{out_dir}", "-y"],
        ["cabextract", path, "-d", out_dir],
    ):
        ok, _ = _cmd(tool_cmd)
        if ok:
            return True, ""

    return False, (
        f"Cannot extract {fmt} — no suitable tool found.\n\n"
        "Install system tools:\n"
        "  Ubuntu:  apt install p7zip-full cabextract\n"
        "  Termux:  pkg install p7zip cabextract\n"
        "  macOS:   brew install p7zip"
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  File-system helpers
# ═══════════════════════════════════════════════════════════════════════════════

def scan_extracted(ext_dir: str) -> tuple[dict, list]:
    top_dirs:   dict[str, list] = {}
    flat_files: list[str]       = []
    try:
        for entry in os.scandir(ext_dir):
            if entry.is_dir(follow_symlinks=False):
                files = [
                    os.path.join(r, fn)
                    for r, _, fns in os.walk(entry.path)
                    for fn in fns
                ]
                top_dirs[entry.name] = files
            elif entry.is_file():
                flat_files.append(entry.path)
    except Exception as exc:
        logger.error(f"scan_extracted: {exc}")
    return top_dirs, flat_files


def cleanup_old_sessions():
    try:
        if not os.path.isdir(TEMP_DIR):
            return
        now = time.time()
        for entry in os.scandir(TEMP_DIR):
            if not entry.is_dir():
                continue
            try:
                created = float((Path(entry.path) / ".created_at").read_text())
            except Exception:
                created = entry.stat().st_mtime
            if now - created > 1800:
                shutil.rmtree(entry.path, ignore_errors=True)
    except Exception as exc:
        logger.warning(f"cleanup: {exc}")


def _clean(uid: int):
    sd = user_data.get(uid, {}).get("session_dir")
    if sd:
        shutil.rmtree(sd, ignore_errors=True)
    user_data.pop(uid, None)
    user_states[uid] = STATE_IDLE

# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_dur(secs: float) -> str:
    secs = max(0, int(secs))
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    parts  = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)

# ═══════════════════════════════════════════════════════════════════════════════
#  File sending
# ═══════════════════════════════════════════════════════════════════════════════

def _send_files(chat_id: int, files: list, msg_id: int) -> int:
    total = len(files)
    if total == 0:
        edit(chat_id, msg_id,
             f"Hmm~ nothing to send? {_kao()}\n"
             f"`[!]` The archive seems to be empty...",
             kb=back_kb())
        return 0

    sent = failed = 0
    for i, fp in enumerate(files, 1):
        try:
            r = send_doc(chat_id, fp)
            if r.get("ok"):
                sent += 1
            else:
                failed += 1
        except Exception as exc:
            logger.warning(f"send_doc failed: {fp}: {exc}")
            failed += 1
        if i % 5 == 0 or i == total:
            edit(chat_id, msg_id, msg_sending(i, total, sent, failed))
        time.sleep(0.05)
    return sent

# ═══════════════════════════════════════════════════════════════════════════════
#  Main menu
# ═══════════════════════════════════════════════════════════════════════════════

def show_menu(chat_id: int, fname: str, uid: int, msg_id: int = None):
    is_admin = (uid == OWNER_ID)
    text = (
        f"Yahallo~ {_kao()}  I'm *{BOT_NAME}*!\n"
        f"╔══[ MAIN MENU ]══════════════╗\n"
        f"║  Hello, *{fname[:16]}*~              ║\n"
        f"║  What shall we do today?    ║\n"
        f"╚═════════════════════════════╝"
    )
    kb = main_menu_kb(is_admin)
    if msg_id:
        edit(chat_id, msg_id, text, kb=kb)
    else:
        send(chat_id, text, kb=kb)

# ═══════════════════════════════════════════════════════════════════════════════
#  Command handlers
# ═══════════════════════════════════════════════════════════════════════════════

def h_start(msg: dict):
    chat_id  = msg["chat"]["id"]
    u        = msg.get("from", {})
    uid, un, fn, ln = (u.get("id",0), u.get("username",""),
                       u.get("first_name","User"), u.get("last_name",""))
    try:
        db.upsert_user(uid, un, fn, ln)
    except Exception:
        pass
    user_states[uid] = STATE_IDLE
    user_data[uid]   = {}
    show_menu(chat_id, fn, uid)


def h_redeem(msg: dict):
    chat_id = msg["chat"]["id"]
    uid     = msg.get("from", {}).get("id", 0)
    parts   = msg.get("text", "").strip().split()
    if len(parts) < 2:
        send(chat_id,
             f"Hmm~ {_kao()}\n"
             f"Usage: `/redeem YOUR-KEY`\n\n"
             f"_Example: `/redeem ABCD-EFGH-IJKL-MNOP`_")
        return
    key = parts[1].strip().upper()
    try:
        ok, resp_msg, dur = db.redeem_license(key, uid)
    except Exception as exc:
        send(chat_id, f"Kyaa something broke~ {_kao()}\n`[✗]` {exc}")
        return
    if ok:
        send(chat_id,
             f"Yatta~! {_kao()}\n"
             f"╔══[ LICENCE ACTIVATED ]══════╗\n"
             f"║  [+] Key:  `{key[:20]}`\n"
             f"║  [+] Time: `{_fmt_dur(dur)}`\n"
             f"╚════════════════════════════╝\n\n"
             f"Now you can unzip ALL the things~ ♡",
             kb=back_kb())
    else:
        send(chat_id,
             f"Mou~ {_kao()}\n`[✗]` {resp_msg}")


def h_cancel(msg: dict):
    chat_id = msg["chat"]["id"]
    uid     = msg.get("from", {}).get("id", 0)
    fn      = msg.get("from", {}).get("first_name", "User")
    _clean(uid)
    send(chat_id, f"Okay okay~ cancelled! {_kao()}")
    show_menu(chat_id, fn, uid)


def h_admin_cmd(msg: dict):
    chat_id = msg["chat"]["id"]
    uid     = msg.get("from", {}).get("id", 0)
    if uid != OWNER_ID:
        send(chat_id, f"Nope~ {_kao()} That's for onii-sama only!")
        return
    user_states[uid] = STATE_ADMIN_MENU
    send(chat_id,
         f"Hehe~ Welcome back onii-sama {_kao()}\n"
         f"╔══[ ADMIN PANEL ]═══╗\n"
         f"║  What shall I do~? ║\n"
         f"╚═══════════════════╝",
         kb=admin_kb())


def h_formats(msg: dict):
    chat_id = msg["chat"]["id"]
    fmts    = "  ".join(f"`{f}`" for f in SUPPORTED_FORMATS)
    send(chat_id,
         f"Nyaa~ I can handle these~ {_kao()}\n"
         f"╔══[ FORMATS ]════════════════╗\n"
         f"║  {fmts[:56]}\n"
         f"╚═════════════════════════════╝\n\n"
         f"`[>]` Format detected by *magic bytes* (not extension!)\n"
         f"`[>]` Password-protected archives: ✓",
         kb=back_kb())

# ═══════════════════════════════════════════════════════════════════════════════
#  File flow
# ═══════════════════════════════════════════════════════════════════════════════

def h_file(msg: dict):
    """Handles document upload when state = WAITING_FILE."""
    chat_id = msg["chat"]["id"]
    uid     = msg.get("from", {}).get("id", 0)
    doc     = msg.get("document")

    if not doc:
        send(chat_id,
             f"Hmm~ {_kao()} I need a *file*, not a photo or voice message~")
        return

    fname     = doc.get("file_name") or "archive"
    file_size = doc.get("file_size", 0)
    file_id   = doc.get("file_id")

    if file_size and file_size > MAX_FILE_SIZE:
        send(chat_id,
             f"Kyaa that's too big for me~ {_kao()}\n"
             f"`[!]` Max: `{_fmt_size(MAX_FILE_SIZE)}`\n"
             f"`[!]` Yours: `{_fmt_size(file_size)}`",
             kb=back_kb())
        return

    # Pre-check by extension (magic check after download)
    if detect_fmt(fname) is None:
        send(chat_id,
             f"Hmm I don't know that format~ {_kao()}\n"
             f"`[!]` Use /formats to see what I support!",
             kb=back_kb())
        return

    # Prepare session
    session_id  = f"{uid}_{int(time.time())}"
    session_dir = os.path.join(TEMP_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    (Path(session_dir) / ".created_at").write_text(str(time.time()))
    archive_path = os.path.join(session_dir, fname)

    res = send(chat_id, msg_downloading(0))
    pmid = res.get("result", {}).get("message_id")

    edit(chat_id, pmid, msg_downloading(40))
    if not dl_file(file_id, archive_path):
        shutil.rmtree(session_dir, ignore_errors=True)
        edit(chat_id, pmid,
             f"Download failed... {_kao()}\n`[✗]` Please try again~",
             kb=back_kb())
        return

    edit(chat_id, pmid, msg_downloading(100))

    # Real format detection from file bytes
    real_fmt = detect_fmt(fname, archive_path)
    if not real_fmt:
        shutil.rmtree(session_dir, ignore_errors=True)
        edit(chat_id, pmid,
             f"Hmm the file doesn't look like an archive~ {_kao()}\n"
             f"`[!]` It might be corrupt or unsupported.",
             kb=back_kb())
        return

    user_data[uid] = {
        "session_id":   session_id,
        "session_dir":  session_dir,
        "archive_path": archive_path,
        "archive_name": fname,
        "archive_fmt":  real_fmt,
        "prog_msg_id":  pmid,
    }

    # Check password requirement
    time.sleep(0.3)
    try:
        pwd_needed = needs_password(archive_path, real_fmt)
    except Exception:
        pwd_needed = False

    if pwd_needed:
        user_states[uid] = STATE_WAITING_PASSWORD
        edit(chat_id, pmid, msg_ask_password(), kb=cancel_kb())
        return

    edit(chat_id, pmid, msg_scanning())
    _extract_and_send(chat_id, uid, pmid)


def h_password(msg: dict):
    """Handles password text when state = WAITING_PASSWORD."""
    chat_id  = msg["chat"]["id"]
    uid      = msg.get("from", {}).get("id", 0)
    pwd_text = msg.get("text", "").strip()
    if not pwd_text:
        send(chat_id, f"Psst~ {_kao()} Send me the password as a text message~")
        return

    passwords = [p.encode() for p in pwd_text.splitlines() if p.strip()]
    ud = user_data.get(uid, {})
    archive_path = ud.get("archive_path", "")
    session_dir  = ud.get("session_dir", "")
    real_fmt     = ud.get("archive_fmt", "")
    pmid         = ud.get("prog_msg_id")

    res    = send(chat_id, f"Testing password(s)~ {_kao()}")
    tid    = res.get("result", {}).get("message_id")
    ext_dir = os.path.join(session_dir, "extracted")
    success = used_pwd = None

    for pwd in passwords:
        shutil.rmtree(ext_dir, ignore_errors=True)
        ok, _ = extract_archive(archive_path, ext_dir, real_fmt, pwd)
        if ok:
            success = True
            used_pwd = pwd
            break

    if not success:
        shutil.rmtree(ext_dir, ignore_errors=True)
        ok, _ = extract_archive(archive_path, ext_dir, real_fmt, None)
        success = ok

    if not success:
        if tid:
            edit(chat_id, tid, msg_wrong_password(), kb=cancel_kb())
        return

    user_data[uid]["used_password"] = used_pwd
    if tid:
        edit(chat_id, tid, msg_password_ok())
    _extract_and_send(chat_id, uid, pmid, already_extracted=ext_dir)


def _extract_and_send(chat_id: int, uid: int, pmid: int,
                       already_extracted: str = None):
    ud           = user_data.get(uid, {})
    archive_path = ud.get("archive_path", "")
    session_dir  = ud.get("session_dir", "")
    real_fmt     = ud.get("archive_fmt", "")
    password     = ud.get("used_password")
    session_id   = ud.get("session_id", "")

    ext_dir = already_extracted or os.path.join(session_dir, "extracted")

    if not already_extracted:
        edit(chat_id, pmid, msg_extracting(30))
        ok, err = extract_archive(archive_path, ext_dir, real_fmt, password)
        if not ok:
            edit(chat_id, pmid, msg_error(err), kb=back_kb())
            _clean(uid)
            return

    edit(chat_id, pmid, msg_scanning())
    top_dirs, flat_files = scan_extracted(ext_dir)
    user_data[uid].update({
        "ext_dir":    ext_dir,
        "top_dirs":   top_dirs,
        "flat_files": flat_files,
    })

    total = len(flat_files) + sum(len(v) for v in top_dirs.values())
    edit(chat_id, pmid,
         f"Archive opened~ {_kao()}\n"
         f"╔══[ CONTENTS ]═══════════╗\n"
         f"║  [>] Files:   `{total:<8}` ║\n"
         f"║  [>] Folders: `{len(top_dirs):<8}` ║\n"
         f"╚═════════════════════════╝")
    time.sleep(0.4)

    if top_dirs:
        user_states[uid] = STATE_SELECTING_FOLDERS
        user_data[uid]["selected_folders"] = set(top_dirs.keys())
        kb = folder_kb(top_dirs, set(top_dirs.keys()), session_id)
        edit(chat_id, pmid,
             f"Pick the folders you want~ {_kao()}\n"
             f"All `{len(top_dirs)}` selected by default.",
             kb=kb)
    else:
        edit(chat_id, pmid,
             f"Sending `{len(flat_files)}` file(s)~ {_kao()}")
        sent = _send_files(chat_id, flat_files, pmid)
        try:
            db.increment_user_stats(uid, files=sent, archives=1)
            db.increment_global_stats(files=sent, archives=1)
        except Exception:
            pass
        edit(chat_id, pmid, msg_done(sent), kb=back_kb())
        _clean(uid)

# ═══════════════════════════════════════════════════════════════════════════════
#  Callback dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

def h_callback(cbq: dict):
    cbq_id  = cbq["id"]
    data    = cbq.get("data", "")
    u       = cbq.get("from", {})
    uid     = u.get("id", 0)
    fn      = u.get("first_name", "User")
    chat_id = cbq.get("message", {}).get("chat", {}).get("id", 0)
    msg_id  = cbq.get("message", {}).get("message_id")

    # Always answer — removes the loading spinner
    answer_cb(cbq_id)

    # ── Subscription guard ────────────────────────────────────────────────────
    guarded = {"menu_unzip", "menu_profile", "menu_stats"}
    if data in guarded and uid != OWNER_ID:
        try:
            if not db.is_user_active(uid):
                edit(chat_id, msg_id, no_sub_msg(),
                     kb={"inline_keyboard": [[
                         _btn("▸ Redeem Key", "back_main", "success")
                     ]]})
                return
        except Exception:
            pass

    # ── Navigation ────────────────────────────────────────────────────────────
    if data == "back_main":
        _clean(uid)
        show_menu(chat_id, fn, uid, msg_id=msg_id)
        return

    # ── Menu pages ────────────────────────────────────────────────────────────
    if data == "menu_unzip":
        user_states[uid] = STATE_WAITING_FILE
        user_data[uid]   = {}
        edit(chat_id, msg_id, msg_ask_file(), kb=cancel_kb())
        return

    if data == "menu_profile":
        _show_profile(chat_id, msg_id, uid)
        return

    if data == "menu_stats":
        _show_stats(chat_id, msg_id, uid)
        return

    if data == "menu_help":
        edit(chat_id, msg_id,
             f"How to use me~ {_kao()}\n"
             f"╔══[ HELP ]═══════════════════╗\n"
             f"║  1) /redeem YOUR-KEY        ║\n"
             f"║  2) /start  → open menu     ║\n"
             f"║  3) ▸ Unzip File            ║\n"
             f"║  4) Send your archive~      ║\n"
             f"║  5) Pick password if asked  ║\n"
             f"║  6) Pick folders~           ║\n"
             f"║  7) Get files back! ♡       ║\n"
             f"╚═════════════════════════════╝\n\n"
             f"`[>]` Max size: `{_fmt_size(MAX_FILE_SIZE)}`\n"
             f"`[>]` Magic\\-byte format detect: ✓\n"
             f"`[>]` Password archives: ✓\n\n"
             f"Built by *{BOT_AUTHOR}* ♡",
             kb=back_kb())
        return

    if data == "menu_formats":
        fmts = "\n".join(f"  `{f}`" for f in SUPPORTED_FORMATS)
        edit(chat_id, msg_id,
             f"Formats I can handle~ {_kao()}\n"
             f"{'─'*28}\n{fmts}\n{'─'*28}\n\n"
             f"`[>]` Detected by *magic bytes*\n"
             f"`[>]` Password\\-protected: ✓",
             kb=back_kb())
        return

    if data == "menu_support":
        edit(chat_id, msg_id,
             f"Kyaa need help? {_kao()}\n"
             f"╔══[ SUPPORT ]════════════╗\n"
             f"║  Contact: *{BOT_AUTHOR}*   ║\n"
             f"║  on Telegram~            ║\n"
             f"╚═════════════════════════╝\n\n"
             f"_⚡ {BOT_NAME} v{BOT_VERSION}_",
             kb=back_kb())
        return

    # ── Folder selection ──────────────────────────────────────────────────────
    if data.startswith("folder_toggle:"):
        parts = data.split(":", 2)
        if len(parts) == 3:
            folder = parts[2]
            ud = user_data.get(uid, {})
            sel = ud.get("selected_folders", set())
            sel.discard(folder) if folder in sel else sel.add(folder)
            ud["selected_folders"] = sel
        _refresh_folder_kb(chat_id, msg_id, uid)
        return

    if data.startswith("folder_all:"):
        ud = user_data.get(uid, {})
        ud["selected_folders"] = set(ud.get("top_dirs", {}).keys())
        _refresh_folder_kb(chat_id, msg_id, uid)
        return

    if data.startswith("folder_none:"):
        user_data.get(uid, {})["selected_folders"] = set()
        _refresh_folder_kb(chat_id, msg_id, uid)
        return

    if data.startswith("folder_confirm:"):
        _confirm_folders(chat_id, msg_id, uid)
        return

    if data == "folder_cancel":
        _clean(uid)
        edit(chat_id, msg_id, f"Okay~ cancelled! {_kao()}")
        show_menu(chat_id, fn, uid)
        return

    # ── Admin panel ───────────────────────────────────────────────────────────
    if data == "admin_panel":
        if uid != OWNER_ID:
            answer_cb(cbq_id, "Nope~ that's for onii-sama only!", alert=True)
            return
        user_states[uid] = STATE_ADMIN_MENU
        edit(chat_id, msg_id,
             f"Hehe~ Welcome back onii-sama {_kao()}\n"
             f"╔══[ ADMIN PANEL ]═══╗\n"
             f"║  What shall I do~? ║\n"
             f"╚═══════════════════╝",
             kb=admin_kb())
        return

    if data == "admin_stats":
        _admin_stats(chat_id, msg_id)
        return

    if data == "admin_users":
        _admin_users(chat_id, msg_id)
        return

    if data == "admin_active":
        _admin_active_users(chat_id, msg_id)
        return

    if data == "admin_gen_keys":
        user_states[uid] = STATE_ADMIN_KEY_COUNT
        edit(chat_id, msg_id,
             f"Ooh generating keys~ {_kao()}\n"
             f"`[>]` How many keys? Send a number (1\\-100)\n\n/cancel to stop~",
             kb={"inline_keyboard": [[_btn("◂ Back", "admin_panel", "primary")]]})
        return

    if data == "admin_broadcast":
        user_states[uid] = STATE_ADMIN_BROADCAST
        edit(chat_id, msg_id,
             f"Broadcast time~ {_kao()}\n"
             f"`[>]` Send me the message to broadcast to all users\n\n/cancel to stop~",
             kb={"inline_keyboard": [[_btn("◂ Back", "admin_panel", "primary")]]})
        return

    if data == "admin_lookup":
        user_states[uid]                      = STATE_ADMIN_MENU
        user_data.setdefault(uid, {})["admin_action"] = "lookup"
        edit(chat_id, msg_id,
             f"Lookup mode~ {_kao()}\n"
             f"`[>]` Send me a Telegram user ID (numbers)\n\n/cancel to stop~",
             kb={"inline_keyboard": [[_btn("◂ Back", "admin_panel", "primary")]]})
        return


def _refresh_folder_kb(chat_id: int, msg_id: int, uid: int):
    ud       = user_data.get(uid, {})
    top_dirs = ud.get("top_dirs", {})
    selected = ud.get("selected_folders", set())
    sid      = ud.get("session_id", "")
    kb       = folder_kb(top_dirs, selected, sid)
    edit(chat_id, msg_id,
         f"Pick folders~ {_kao()}\n"
         f"`[>]` `{len(selected)}/{len(top_dirs)}` folder(s) selected",
         kb=kb)


def _confirm_folders(chat_id: int, msg_id: int, uid: int):
    ud         = user_data.get(uid, {})
    top_dirs   = ud.get("top_dirs", {})
    selected   = ud.get("selected_folders", set())
    flat_files = ud.get("flat_files", [])

    files_to_send = list(flat_files)
    for folder in selected:
        files_to_send.extend(top_dirs.get(folder, []))

    if not files_to_send:
        edit(chat_id, msg_id,
             f"Mou~ pick at least one folder~ {_kao()}")
        return

    user_states[uid] = STATE_IDLE
    edit(chat_id, msg_id,
         f"Preparing `{len(files_to_send)}` file(s)~ {_kao()}")
    sent = _send_files(chat_id, files_to_send, msg_id)
    try:
        db.increment_user_stats(uid, files=sent, archives=1)
        db.increment_global_stats(files=sent, archives=1)
    except Exception:
        pass
    edit(chat_id, msg_id, msg_done(sent), kb=back_kb())
    _clean(uid)

# ── Info panels ───────────────────────────────────────────────────────────────

def _show_profile(chat_id: int, msg_id: int, uid: int):
    try:
        row = db.get_user(uid)
    except Exception:
        row = None
    now = time.time()
    if row and row["is_active"] and row["license_expires"]:
        rem     = row["license_expires"] - now
        exp_dt  = datetime.fromtimestamp(row["license_expires"]).strftime("%Y-%m-%d")
        status  = "[+] Active"
        tleft   = _fmt_dur(rem) if rem > 0 else "[!] Expired"
        kdisp   = f"`{row['license_key']}`"
    else:
        status  = "[✗] No licence"
        tleft   = "─"
        exp_dt  = "─"
        kdisp   = "─"
    joined   = datetime.fromtimestamp(row["joined_at"]).strftime("%Y-%m-%d") if row else "─"
    username = f"@{row['username']}" if row and row["username"] else "─"
    edit(chat_id, msg_id,
         f"Your profile~ {_kao()}\n"
         f"╔══[ PROFILE ]════════════════╗\n"
         f"║  ID:       `{uid}`\n"
         f"║  Username: {username}\n"
         f"║  Joined:   `{joined}`\n"
         f"║  {'─'*28}\n"
         f"║  Status:   `{status}`\n"
         f"║  Key:      {kdisp}\n"
         f"║  Expires:  `{exp_dt}`\n"
         f"║  Remaining:`{tleft}`\n"
         f"╚═════════════════════════════╝",
         kb=back_kb())


def _show_stats(chat_id: int, msg_id: int, uid: int):
    try:
        row = db.get_user(uid)
    except Exception:
        row = None
    files    = row["files_sent"]         if row else 0
    archives = row["archives_processed"] if row else 0
    edit(chat_id, msg_id,
         f"Your stats~ {_kao()}\n"
         f"╔══[ STATISTICS ]═════════════╗\n"
         f"║  [>] Archives: `{archives:<12}` ║\n"
         f"║  [>] Files:    `{files:<12}` ║\n"
         f"╚═════════════════════════════╝\n\n"
         f"_⚡ Powered by {BOT_NAME}_",
         kb=back_kb())

# ── Admin panels ──────────────────────────────────────────────────────────────

def _admin_stats(chat_id: int, msg_id: int):
    try:
        st = db.get_global_stats()
        all_u  = db.get_all_users()
        act_u  = db.get_active_users()
    except Exception:
        edit(chat_id, msg_id, f"Oops failed to fetch stats~ {_kao()}", kb=admin_kb())
        return
    edit(chat_id, msg_id,
         f"Bot stats~ {_kao()}\n"
         f"╔══[ GLOBAL STATS ]═══════════╗\n"
         f"║  [>] Total users:  `{len(all_u):<8}` ║\n"
         f"║  [>] Active users: `{len(act_u):<8}` ║\n"
         f"║  [>] Archives:     `{(st['total_archives_done'] if st else 0):<8}` ║\n"
         f"║  [>] Files sent:   `{(st['total_files_sent'] if st else 0):<8}` ║\n"
         f"║  [>] Keys gen:     `{(st['total_keys_generated'] if st else 0):<8}` ║\n"
         f"╚═════════════════════════════╝",
         kb=admin_kb())


def _admin_users(chat_id: int, msg_id: int):
    try:
        users = db.get_all_users()
    except Exception:
        users = []
    lines = [f"All users ({len(users)})~ {_kao()}"]
    lines.append("─" * 28)
    for u in users[:20]:
        un = f"@{u['username']}" if u["username"] else "─"
        lines.append(f"`{u['user_id']}` {u['first_name']} {un}")
    if len(users) > 20:
        lines.append(f"…and {len(users)-20} more")
    edit(chat_id, msg_id, "\n".join(lines), kb=admin_kb())


def _admin_active_users(chat_id: int, msg_id: int):
    try:
        users = db.get_active_users()
    except Exception:
        users = []
    lines = [f"Active users ({len(users)})~ {_kao()}"]
    lines.append("─" * 28)
    for u in users[:20]:
        un = f"@{u['username']}" if u["username"] else "─"
        lines.append(f"`{u['user_id']}` {u['first_name']} {un}")
    if len(users) > 20:
        lines.append(f"…and {len(users)-20} more")
    edit(chat_id, msg_id, "\n".join(lines), kb=admin_kb())

# ── Admin text input handlers ─────────────────────────────────────────────────

def h_admin_key_count(msg: dict):
    chat_id = msg["chat"]["id"]
    uid     = msg.get("from", {}).get("id", 0)
    txt     = msg.get("text", "").strip()
    if not txt.isdigit() or not (1 <= int(txt) <= 100):
        send(chat_id, f"Hmm~ {_kao()} Send a number between 1 and 100~")
        return
    user_data.setdefault(uid, {})["key_count"] = int(txt)
    user_states[uid] = STATE_ADMIN_KEY_DURATION
    send(chat_id,
         f"Okay~ `{txt}` key(s)! {_kao()}\n"
         f"`[>]` Now send the duration:\n"
         f"  `7D`  `30D`  `1W`  `1MO`  `1H`  `30M`")


def h_admin_key_duration(msg: dict):
    chat_id = msg["chat"]["id"]
    uid     = msg.get("from", {}).get("id", 0)
    txt     = msg.get("text", "").strip()
    dur, label = db.parse_duration(txt)
    if dur is None:
        send(chat_id, f"Hmm~ {_kao()} Invalid format! Try `7D`, `30D`, `1MO`, `1H`…")
        return
    count = user_data.get(uid, {}).get("key_count", 1)
    try:
        keys = db.generate_keys(count, dur, label)
    except Exception as exc:
        send(chat_id, f"Oops! {_kao()} `[✗]` {exc}")
        user_states[uid] = STATE_ADMIN_MENU
        return
    key_lines = "\n".join(f"`{k}`" for k in keys)
    send(chat_id,
         f"Keys ready~ {_kao()}\n"
         f"╔══[ {count} KEY(S) GENERATED ]══╗\n"
         f"║  Duration: `{label}`\n"
         f"╚══════════════════════════╝\n\n"
         f"{key_lines}")
    send(chat_id,
         f"Anything else onii-sama? {_kao()}",
         kb=admin_kb())
    user_data.get(uid, {}).pop("key_count", None)
    user_states[uid] = STATE_ADMIN_MENU


def h_admin_broadcast(msg: dict):
    chat_id = msg["chat"]["id"]
    uid     = msg.get("from", {}).get("id", 0)
    try:
        users = db.get_all_users()
    except Exception:
        users = []
    st_res = send(chat_id, f"Broadcasting to {len(users)} users~ {_kao()}")
    st_id  = st_res.get("result", {}).get("message_id")
    sent = failed = 0
    for u in users:
        try:
            _api("forwardMessage",
                 chat_id=u["user_id"],
                 from_chat_id=chat_id,
                 message_id=msg["message_id"])
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
    if st_id:
        edit(chat_id, st_id,
             f"Broadcast done~ {_kao()}\n"
             f"`[+]` Sent: `{sent}`\n"
             f"`[✗]` Failed: `{failed}`")
    send(chat_id, f"Anything else~ {_kao()}", kb=admin_kb())
    user_states[uid] = STATE_ADMIN_MENU


def h_admin_lookup(msg: dict, uid: int):
    chat_id = msg["chat"]["id"]
    txt = msg.get("text", "").strip()
    if not txt.lstrip("-").isdigit():
        send(chat_id, f"Hmm~ {_kao()} Send a valid Telegram ID (numbers only)~")
        return
    tid = int(txt)
    try:
        row = db.get_user(tid)
    except Exception:
        row = None
    if not row:
        send(chat_id, f"Mou~ `{tid}` not found in my database~ {_kao()}")
    else:
        now  = time.time()
        act  = row["is_active"] and (
            not row["license_expires"] or row["license_expires"] > now)
        rem  = _fmt_dur(row["license_expires"] - now) \
            if row["license_expires"] and act else "─"
        send(chat_id,
             f"Found them~ {_kao()}\n"
             f"╔══[ USER LOOKUP ]═══════════╗\n"
             f"║  ID:       `{row['user_id']}`\n"
             f"║  Name:     {row['first_name']}\n"
             f"║  Username: @{row['username'] or '─'}\n"
             f"║  Active:   {'[+] Yes' if act else '[✗] No'}\n"
             f"║  Key:      `{row['license_key'] or '─'}`\n"
             f"║  Left:     `{rem}`\n"
             f"║  Archives: `{row['archives_processed']}`\n"
             f"║  Files:    `{row['files_sent']}`\n"
             f"╚════════════════════════════╝")
    user_data.get(uid, {}).pop("admin_action", None)
    send(chat_id, f"Anything else~ {_kao()}", kb=admin_kb())

# ═══════════════════════════════════════════════════════════════════════════════
#  Central dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

def dispatch_msg(msg: dict):
    try:
        uid     = msg.get("from", {}).get("id", 0)
        chat_id = msg["chat"]["id"]
        text    = msg.get("text") or ""
        state   = user_states.get(uid, STATE_IDLE)

        if text.startswith("/start"):   h_start(msg);     return
        if text.startswith("/redeem"):  h_redeem(msg);    return
        if text.startswith("/cancel"):  h_cancel(msg);    return
        if text.startswith("/admin"):   h_admin_cmd(msg); return
        if text.startswith("/formats"): h_formats(msg);   return

        if state == STATE_WAITING_FILE:
            h_file(msg) if msg.get("document") else \
                send(chat_id, f"Hmm~ {_kao()} Please send a *file* attachment~")
            return
        if state == STATE_WAITING_PASSWORD:
            h_password(msg) if text else \
                send(chat_id, f"Psst~ {_kao()} Send the password as text~")
            return
        if state == STATE_ADMIN_KEY_COUNT:
            h_admin_key_count(msg); return
        if state == STATE_ADMIN_KEY_DURATION:
            h_admin_key_duration(msg); return
        if state == STATE_ADMIN_BROADCAST:
            h_admin_broadcast(msg); return
        if state == STATE_ADMIN_MENU:
            action = user_data.get(uid, {}).get("admin_action")
            if action == "lookup":
                h_admin_lookup(msg, uid)
            return

        fn = msg.get("from", {}).get("first_name", "User")
        show_menu(chat_id, fn, uid)

    except Exception:
        logger.error(f"dispatch_msg:\n{traceback.format_exc()}")
        try:
            send(msg["chat"]["id"],
                 f"Kyaa something went wrong~ {_kao()}\n"
                 f"`[!]` Please try again or /cancel~")
        except Exception:
            pass


def dispatch_cb(cbq: dict):
    try:
        h_callback(cbq)
    except Exception:
        logger.error(f"dispatch_cb:\n{traceback.format_exc()}")
        try:
            answer_cb(cbq["id"],
                      "Kyaa something went wrong~ Please try again!", alert=True)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
#  Long-poll loop
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not set!")
        sys.exit(1)

    os.makedirs(TEMP_DIR, exist_ok=True)
    db.init_db()
    keep_alive()

    _api("setMyCommands", commands=[
        {"command": "start",   "description": "Open menu"},
        {"command": "redeem",  "description": "Redeem a licence key"},
        {"command": "admin",   "description": "Admin panel (owner only)"},
        {"command": "cancel",  "description": "Cancel current operation"},
        {"command": "formats", "description": "List supported formats"},
    ])

    logger.info(f"[BOOT] {BOT_NAME} v{BOT_VERSION} by {BOT_AUTHOR}")
    logger.info(f"[BOOT] py7zr={HAS_7Z}  rarfile={HAS_RAR}")
    logger.info("[POLL] Starting long-poll loop...")

    # Drop stale updates
    stale = get_updates(-1)
    offset = (stale[-1]["update_id"] + 1) if stale else 0

    last_cleanup = time.time()

    while True:
        try:
            updates = get_updates(offset)
        except Exception as exc:
            logger.warning(f"[POLL] {exc}")
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                if "message"        in upd: dispatch_msg(upd["message"])
                elif "callback_query" in upd: dispatch_cb(upd["callback_query"])
            except Exception:
                logger.error(traceback.format_exc())

        if time.time() - last_cleanup > 300:
            cleanup_old_sessions()
            last_cleanup = time.time()


if __name__ == "__main__":
    main()
