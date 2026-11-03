# notify/telegram.py
# =========================
# Bot Telegram : TELEGRAM_BOT_TOKEN (via @BotFather) + TELEGRAM_CHAT_ID
# =========================

import requests

import config


def send(title, body, url=None, priority="default", tags=()):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID non définis (voir .env.example)")
    text = f"{'🚨 ' if priority in ('high', 'urgent') else ''}{title}\n\n{body}"
    if url:
        text += f"\n{url}"
    resp = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": False},
        timeout=10,
    )
    resp.raise_for_status()
