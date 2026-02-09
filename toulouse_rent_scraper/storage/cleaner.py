# storage/cleaner.py
# =========================
# Vérification et purge des annonces expirées
# =========================

import sqlite3
import time

import requests

from storage.sqlite import DB_PATH, get_connection
from utils.logger import setup_logger

logger = setup_logger("cleaner")

RATE_LIMIT_DELAY = 1.0  # secondes entre chaque requête


def _check_url_alive(url: str) -> bool:
    """Vérifie si une URL est encore accessible (HEAD request, fallback GET)."""
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True)
        if resp.status_code == 405:
            resp = requests.get(url, timeout=10, allow_redirects=True, stream=True)
        return resp.status_code < 400
    except requests.RequestException:
        return False


def check_expired_annonces() -> dict:
    """
    Vérifie toutes les annonces actives et marque les expirées.
    Retourne un résumé {checked, expired, still_active}.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    annonces = cur.execute(
        "SELECT id, url, title FROM annonces WHERE status = 'active'"
    ).fetchall()

    checked = 0
    expired = 0

    for annonce in annonces:
        alive = _check_url_alive(annonce["url"])
        checked += 1

        if not alive:
            cur.execute(
                "UPDATE annonces SET status = 'expired' WHERE id = ?",
                (annonce["id"],),
            )
            expired += 1
            logger.info(f"Expirée : {annonce['title']} ({annonce['url']})")
        else:
            logger.debug(f"Active : {annonce['title']}")

        time.sleep(RATE_LIMIT_DELAY)

    conn.commit()
    conn.close()

    summary = {"checked": checked, "expired": expired, "still_active": checked - expired}
    logger.info(
        f"Purge terminée : {summary['checked']} vérifiées, "
        f"{summary['expired']} expirées, {summary['still_active']} actives"
    )
    return summary
