# scrapers/antibot.py
# =========================
# Détection des challenges anti-bot (DataDome, captcha) et attente
# de résolution manuelle dans la fenêtre Chrome.
# =========================

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

from config import BLOCK_COOLDOWN_HOURS, BLOCK_STATE_FILE
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
    # Cloudflare (PAP.fr, Sprint 4)
    "vérifiez que vous êtes humain",
    "verify you are human",
]

BLOCK_TITLES = ["accès restreint", "blocked", "captcha", "restricted", "just a moment"]


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

    # DataDome affiche son challenge dans une iframe (geo.captcha-delivery.com) :
    # l'URL principale et le titre restent ceux du site.
    try:
        for frame in page.frames:
            if any(domain in (frame.url or "") for domain in blocked_domains):
                return True
    except Exception:
        pass

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


# =========================
# Mémoire des blocages (anti-ban pour les runs planifiés)
# =========================

def _read_blocks(path: Optional[Path]) -> dict:
    path = path or BLOCK_STATE_FILE
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_block(site_name: str, path: Optional[Path] = None, now: Optional[datetime] = None):
    """Mémorise un blocage non résolu pour `site_name`."""
    path = path or BLOCK_STATE_FILE
    blocks = _read_blocks(path)
    blocks[site_name] = (now or datetime.now()).isoformat(timespec="seconds")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(blocks, indent=2), encoding="utf-8")
    logger.warning(f"Blocage mémorisé pour {site_name} (pause de {BLOCK_COOLDOWN_HOURS} h en mode planifié)")


def recently_blocked(
    site_name: str,
    hours: float = BLOCK_COOLDOWN_HOURS,
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    """Date du dernier blocage de `site_name` s'il date de moins de `hours`, sinon None."""
    stamp = _read_blocks(path).get(site_name)
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return when if (now or datetime.now()) - when < timedelta(hours=hours) else None

