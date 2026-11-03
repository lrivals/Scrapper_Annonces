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


def notify_captcha(site_name: str, timeout_seconds: int) -> bool:
    minutes = max(1, round(timeout_seconds / 60))
    return send(
        f"Captcha à résoudre — {site_name}",
        f"Le scraping {site_name} est bloqué par un challenge anti-bot. "
        f"Résoudre le captcha dans la fenêtre Chrome (≈ {minutes} min avant abandon).",
        priority="high",
        tags=["warning"],
    )
