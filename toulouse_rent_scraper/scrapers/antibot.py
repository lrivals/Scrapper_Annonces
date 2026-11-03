# scrapers/antibot.py
# =========================
# Détection des challenges anti-bot (DataDome, captcha) et attente
# de résolution manuelle dans la fenêtre Chrome.
# =========================

import time
from typing import Callable, Iterable, Optional

from utils.logger import setup_logger

logger = setup_logger("antibot")

BLOCKED_DOMAINS = ["captcha-delivery.com", "datadome.co", "arkoselabs.com"]

CHALLENGE_MARKERS = [
    "activité suspecte",
    "comportement du navigateur",
    "vitesse surhumaine",
    "accès temporairement restreint",
    "non pas à un robot",
    "we need to make sure",
    "suspicious activity",
]

BLOCK_TITLES = ["accès restreint", "blocked", "captcha", "restricted"]


def is_page_blocked(
    page,
    site_domain: Optional[str] = None,
    blocked_domains: Iterable[str] = BLOCKED_DOMAINS,
    markers: Iterable[str] = CHALLENGE_MARKERS,
) -> bool:
    """
    True si la page affiche un challenge anti-bot.
    `site_domain` (ex. 'www.leboncoin.fr') : une redirection hors du site compte comme un blocage.
    """
    current_url = page.url or ""
    if any(domain in current_url for domain in blocked_domains):
        return True

    if site_domain and site_domain not in current_url and current_url != "about:blank":
        return True

    markers = [m.lower() for m in markers]

    # Texte visible, puis HTML brut (le texte peut ne pas être encore rendu)
    for read in (lambda: page.inner_text("body"), page.content):
        try:
            if any(m in read().lower() for m in markers):
                return True
        except Exception:
            pass

    try:
        title = page.title().lower()
        if any(t in title for t in BLOCK_TITLES):
            return True
    except Exception:
        pass

    return False


def wait_for_challenge(
    page,
    timeout_seconds: int = 180,
    is_blocked: Optional[Callable] = None,
    on_challenge: Optional[Callable[[], None]] = None,
    poll_seconds: float = 3.0,
    log_every_seconds: float = 15.0,
) -> bool:
    """
    Attend la résolution manuelle d'un challenge. Retourne True si résolu (ou s'il n'y en avait pas).
    `is_blocked(page)` : détecteur (défaut : is_page_blocked).
    `on_challenge()` : appelé une fois au début de l'attente (ex. notification, Sprint 13).
    """
    is_blocked = is_blocked or is_page_blocked
    if not is_blocked(page):
        return True

    logger.warning("=" * 60)
    logger.warning("CHALLENGE ANTI-BOT DETECTE !")
    logger.warning("Resolvez le captcha dans la fenetre Chrome.")
    logger.warning(f"Vous avez {timeout_seconds}s...")
    logger.warning("=" * 60)
    if on_challenge:
        try:
            on_challenge()
        except Exception as e:
            logger.warning(f"on_challenge a échoué : {e}")

    start = time.monotonic()
    last_log = start
    while time.monotonic() - start < timeout_seconds:
        time.sleep(poll_seconds)
        try:
            if not is_blocked(page):
                logger.info("Challenge resolu ! Reprise...")
                time.sleep(2)
                return True
        except Exception:
            continue
        now = time.monotonic()
        if now - last_log >= log_every_seconds:
            last_log = now
            logger.info(f"En attente de resolution... ({int(timeout_seconds - (now - start))}s restantes)")

    logger.error("Timeout : challenge non resolu")
    return False
