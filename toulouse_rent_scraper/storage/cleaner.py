# storage/cleaner.py
# =========================
# Vérification et purge des annonces expirées
# =========================

import random
import sqlite3
import time

import requests

from storage.sqlite import DB_PATH, get_connection
from utils.logger import setup_logger

logger = setup_logger("cleaner")

RATE_LIMIT_DELAY = 1.0  # secondes entre chaque requête (mode requests)

# Fragments de texte indiquant qu'une annonce a été supprimée
_EXPIRED_PATTERNS = [
    # SeLoger
    "annonce supprimée",
    "cette annonce a déjà été supprimée",
    "a déjà été supprimée",
    "il n'y a plus cette annonce",
    # LeBonCoin
    "cette annonce a été désactivée",
    "cette annonce n'est plus en ligne",
    "cette annonce n'existe plus",
    "annonce n'est plus disponible",
    # Génériques
    "page introuvable",
    "erreur 404",
    "404 not found",
]


def _check_url_alive(url: str) -> bool:
    """
    Vérifie si une URL répond (HEAD/GET sans navigateur).
    ATTENTION : peu fiable pour SeLoger/LeBonCoin (SPAs) — préférer check_links_playwright().
    """
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


def check_links_playwright(limit: int = None) -> dict:
    """
    Vérifie les annonces actives avec un navigateur Playwright headless.
    Attend 3–5 secondes aléatoires après chargement, puis inspecte le
    contenu de la page pour détecter les messages d'annonce supprimée.
    Marque les annonces concernées comme 'expired' en base.
    """
    from playwright.sync_api import sync_playwright
    from storage.sqlite import init_db

    # Assure que la colonne status existe (migration)
    init_db()

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = "SELECT id, url, title, site FROM annonces WHERE COALESCE(status, 'active') = 'active'"
    if limit:
        query += f" LIMIT {int(limit)}"
    annonces = cur.fetchall() if False else cur.execute(query).fetchall()
    conn.close()

    checked = 0
    expired = 0
    errors = 0

    logger.info(f"Vérification de {len(annonces)} annonce(s) avec Playwright...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        )

        for annonce in annonces:
            page = context.new_page()
            try:
                page.goto(annonce["url"], timeout=30_000, wait_until="domcontentloaded")

                delay_ms = random.uniform(3.0, 5.0) * 1000
                page.wait_for_timeout(delay_ms)

                content = page.content().lower()
                is_expired = any(pat in content for pat in _EXPIRED_PATTERNS)

                if is_expired:
                    with get_connection() as c:
                        c.execute(
                            "UPDATE annonces SET status = 'expired' WHERE id = ?",
                            (annonce["id"],),
                        )
                    expired += 1
                    logger.info(f"Expirée : {annonce['title']} ({annonce['site']})")
                else:
                    logger.debug(f"Active : {annonce['title']}")

                checked += 1

            except Exception as e:
                logger.warning(f"Erreur sur {annonce['url']} : {e}")
                errors += 1
                checked += 1
            finally:
                page.close()

        context.close()
        browser.close()

    summary = {
        "checked": checked,
        "expired": expired,
        "still_active": checked - expired - errors,
        "errors": errors,
    }
    logger.info(
        f"Vérification terminée : {checked} vérifiées, "
        f"{expired} expirées, {errors} erreurs"
    )
    return summary
