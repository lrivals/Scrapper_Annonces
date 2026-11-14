# notify/__init__.py
# =========================
# Notifications (ntfy.sh ou Telegram). Un échec d'envoi est loggé,
# jamais propagé : il ne doit pas interrompre un scraping.
# =========================

from typing import Iterable, List, Optional

import config
from utils.logger import setup_logger

logger = setup_logger("notify")

PRIORITIES = ("min", "low", "default", "high", "urgent")


def _backend():
    name = config.NOTIFY_BACKEND
    if not name:
        return None
    if name == "ntfy":
        from notify import ntfy
        return ntfy
    if name == "telegram":
        from notify import telegram
        return telegram
    logger.warning(f"NOTIFY_BACKEND inconnu : {name!r} (attendu : ntfy, telegram)")
    return None


def is_enabled() -> bool:
    return _backend() is not None


def send(
    title: str,
    body: str,
    url: Optional[str] = None,
    priority: str = "default",
    tags: Optional[List[str]] = None,
) -> bool:
    """Envoie une notification. True si envoyée, False sinon (désactivé ou erreur)."""
    backend = _backend()
    if backend is None:
        logger.debug(f"Notifications désactivées — non envoyé : {title}")
        return False
    if priority not in PRIORITIES:
        priority = "default"
    try:
        backend.send(title, body, url=url, priority=priority, tags=tags or [])
        logger.info(f"🔔 Notification envoyée ({config.NOTIFY_BACKEND}) : {title}")
        return True
    except Exception as e:
        logger.warning(f"Échec d'envoi de la notification « {title} » : {e}")
        return False


def notify_events(events: Iterable[dict]) -> int:
    """Notifie les événements d'un run (nouvelles annonces, baisses de prix). Retourne le nombre de messages."""
    from notify.messages import build_messages

    sent = 0
    for message in build_messages(list(events)):
        sent += send(**message)
    return sent


def notify_favorites_gone(annonces: Iterable[dict]) -> int:
    """Favoris (⭐) devenus expirés (check-links, purge). Retourne le nombre de messages."""
    from notify.messages import favorite_gone_messages

    sent = 0
    for message in favorite_gone_messages(list(annonces)):
        sent += send(**message)
    return sent


def _top10_state() -> dict:
    import json
    try:
        return json.loads(config.TOP10_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def notify_top10(profile_keys: Iterable[str], now=None) -> int:
    """
    Sprint 5.6 — envoie le Top 10 de chaque profil selon NOTIFY_TOP10 :
    "run" après chaque run, "daily" au plus une fois par jour et par profil, sinon rien.
    Retourne le nombre de messages envoyés.
    """
    import json
    from datetime import datetime

    mode = config.NOTIFY_TOP10
    if mode not in ("run", "daily") or not is_enabled():
        return 0
    from notify.messages import top10_message
    from storage.run_stats import profile_rows
    from storage.sqlite import connect

    today = (now or datetime.now()).date().isoformat()
    state = _top10_state()
    sent = 0
    for key in profile_keys:
        if mode == "daily" and state.get(key) == today:
            continue
        with connect() as conn:
            message = top10_message(key, profile_rows(conn, key))
        if message and send(**message):
            sent += 1
            state[key] = today
    if sent:
        try:
            config.TOP10_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            config.TOP10_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        except OSError as e:
            logger.warning(f"Date du dernier Top 10 non enregistrée : {e}")
    return sent


def notify_captcha(site_name: str, timeout_seconds: int) -> bool:
    minutes = max(1, round(timeout_seconds / 60))
    return send(
        f"Captcha à résoudre — {site_name}",
        f"Le scraping {site_name} est bloqué par un challenge anti-bot. "
        f"Résoudre le captcha dans la fenêtre Chrome (≈ {minutes} min avant abandon).",
        priority="high",
        tags=["warning"],
    )
