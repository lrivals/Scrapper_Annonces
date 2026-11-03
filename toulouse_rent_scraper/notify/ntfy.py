# notify/ntfy.py
# =========================
# ntfy.sh : publication JSON (les en-têtes HTTP n'acceptent pas « — » ni « € »)
# Appli mobile ntfy : s'abonner au topic NTFY_TOPIC.
# =========================

import requests

import config

_PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


def send(title, body, url=None, priority="default", tags=()):
    if not config.NTFY_TOPIC:
        raise RuntimeError("NTFY_TOPIC non défini (voir .env.example)")
    payload = {
        "topic": config.NTFY_TOPIC,
        "title": title,
        "message": body,
        "priority": _PRIORITY.get(priority, 3),
        "tags": list(tags) or ["house"],
    }
    if url:
        payload["click"] = url
    headers = {"Authorization": f"Bearer {config.NTFY_TOKEN}"} if config.NTFY_TOKEN else {}
    resp = requests.post(config.NTFY_SERVER.rstrip("/"), json=payload, headers=headers, timeout=10)
    resp.raise_for_status()
