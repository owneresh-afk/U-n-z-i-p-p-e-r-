"""
╔══════════════════════════════════════════════════════════════════╗
║         ESH UnZipper Bot  —  keep_alive.py                     ║
║         Version  : 3.1.0                                        ║
║         Author   : @iam_esh  (Telegram)                        ║
║         Copyright: © 2026 ESH · All rights reserved            ║
║                                                                  ║
║  Tiny Flask server so Render / UptimeRobot can ping the bot.    ║
╚══════════════════════════════════════════════════════════════════╝
"""

import threading
from flask import Flask
from config import FLASK_PORT, BOT_NAME, BOT_VERSION, BOT_AUTHOR

app = Flask(__name__)


@app.route("/")
def home():
    return (
        f"<pre>"
        f"╔══[ ESH UnZipper ]═════════════╗\n"
        f"║  Bot     : {BOT_NAME:<20} ║\n"
        f"║  Version : {BOT_VERSION:<20} ║\n"
        f"║  Author  : {BOT_AUTHOR:<20} ║\n"
        f"║  Status  : {'Running ✓':<20} ║\n"
        f"╚═══════════════════════════════╝"
        f"</pre>"
    )


@app.route("/health")
def health():
    return {
        "status":  "ok",
        "bot":     BOT_NAME,
        "version": BOT_VERSION,
        "author":  BOT_AUTHOR,
    }


def keep_alive():
    """Launch the Flask ping server in a background daemon thread."""
    t = threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0", port=FLASK_PORT, use_reloader=False
        ),
        daemon=True,
    )
    t.start()
