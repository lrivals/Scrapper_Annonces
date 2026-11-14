# storage/cleaner.py
# =========================
# Vérification et purge des annonces expirées
# =========================

import random
import sqlite3
import time

import requests

from storage.sqlite import DB_PATH, connect, get_connection
from utils.logger import setup_logger

logger = setup_logger("cleaner")

RATE_LIMIT_DELAY = 1.0  # secondes entre chaque requête (mode requests)
MAX_CONSECUTIVE_NETWORK_ERRORS = 3

_NETWORK_ERROR_PATTERNS = [
    "err_internet_disconnected",
    "err_name_not_resolved",
    "err_connection_refused",
    "err_connection_reset",
    "net::",
]

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
    "le bien a déjà été vendu",
    "l'annonceur a supprimé son annonce",
    "lien sur lequel vous avez cliqué peut être sectionné",
    "annonce introuvable",
    "cette annonce n'est plus disponible",
    "request interrupted",
    # Génériques
    "page introuvable",
    "erreur 404",
    "404 not found",
]


def is_expired_content(text: str) -> bool:
    """
    True si le texte indique que l'annonce a été retirée (SeLoger, LeBonCoin).
    ⚠️ Passer le texte **visible** (`page.inner_text("body")`), pas le HTML : les pages LBC
    embarquent tous leurs messages d'erreur (« annonce introuvable », « page introuvable »…)
    dans leurs scripts, même quand l'annonce est en ligne (constaté le 2026-11-13).
    """
    lowered = (text or "").lower()
    return any(pat in lowered for pat in _EXPIRED_PATTERNS)


def page_shows_expired(page) -> bool:
    """
    True si la page ouverte montre une annonce retirée.
    Une page dont le JSON embarqué contient l'annonce (LBC, SeLoger) est en ligne, quel que
    soit le texte.
    """
    from scrapers.detail_extractors import lbc_json, pap_html, seloger_json

    try:
        html = page.content()
        if lbc_json.extract_from_html(html) or seloger_json.extract_from_html(html):
            return False
        # Fiche PAP en ligne : JSON-LD `Product` présent
        if pap_html.parse_detail(html) is not None:
            return False
    except Exception:
        pass
    return is_expired_content(page.inner_text("body"))


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
        "SELECT id, url, title, price FROM annonces WHERE status = 'active'"
    ).fetchall()

    checked = 0
    expired = 0
    gone = []

    for annonce in annonces:
        alive = _check_url_alive(annonce["url"])
        checked += 1

        if not alive:
            cur.execute(
                "UPDATE annonces SET status = 'expired' WHERE id = ?",
                (annonce["id"],),
            )
            expired += 1
            gone.append(dict(annonce))
            logger.info(f"Expirée : {annonce['title']} ({annonce['url']})")
        else:
            logger.debug(f"Active : {annonce['title']}")

        time.sleep(RATE_LIMIT_DELAY)

    conn.commit()
    conn.close()
    _notify_gone(gone)

    summary = {"checked": checked, "expired": expired, "still_active": checked - expired}
    logger.info(
        f"Purge terminée : {summary['checked']} vérifiées, "
        f"{summary['expired']} expirées, {summary['still_active']} actives"
    )
    return summary


def _notify_gone(annonces: list):
    """Favoris (⭐) parmi les annonces expirées : notification (Sprint 15.6)."""
    if not annonces:
        return
    try:
        from notify import notify_favorites_gone
        notify_favorites_gone(annonces)
    except Exception as e:  # une notification ne doit jamais interrompre la vérification
        logger.warning(f"Suivi des favoris indisponible : {e}")


def _mark_checked(annonce_id: int):
    """Enregistre l'horodatage de la dernière vérification d'une annonce."""
    with connect() as c:
        c.execute(
            "UPDATE annonces SET checked_at = datetime('now') WHERE id = ?",
            (annonce_id,),
        )


def check_links_playwright(limit: int = None) -> dict:
    """
    Vérifie les annonces actives avec un navigateur Playwright headless.
    Attend 3–5 secondes aléatoires après chargement, puis inspecte le
    contenu de la page pour détecter les messages d'annonce supprimée.
    Marque les annonces concernées comme 'expired' en base.

    Comportement :
    - Ignore les annonces déjà vérifiées dans les dernières 24h (reprise possible).
    - Distingue erreurs réseau (non comptées, re-tentées) des erreurs de page.
    - Stoppe après MAX_CONSECUTIVE_NETWORK_ERRORS erreurs réseau consécutives.
    """
    from playwright.sync_api import sync_playwright
    from config import USER_AGENT
    from storage.sqlite import init_db

    # Assure que les colonnes status et checked_at existent (migrations)
    init_db()

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = """
        SELECT id, url, title, site, price FROM annonces
        WHERE COALESCE(status, 'active') = 'active'
          AND (checked_at IS NULL OR checked_at < datetime('now', '-24 hours'))
    """
    if limit:
        query += f" LIMIT {int(limit)}"
    annonces = cur.execute(query).fetchall()
    conn.close()

    checked = 0
    expired = 0
    gone = []
    network_errors = 0
    page_errors = 0
    consecutive_network_errors = 0

    logger.info(f"Vérification de {len(annonces)} annonce(s) avec Playwright...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)

        for annonce in annonces:
            page = context.new_page()
            try:
                page.goto(annonce["url"], timeout=30_000, wait_until="domcontentloaded")

                delay_ms = random.uniform(3.0, 5.0) * 1000
                page.wait_for_timeout(delay_ms)

                is_expired = page_shows_expired(page)

                if is_expired:
                    with connect() as c:
                        c.execute(
                            "UPDATE annonces SET status = 'expired' WHERE id = ?",
                            (annonce["id"],),
                        )
                    expired += 1
                    gone.append(dict(annonce))
                    logger.info(f"Expirée : {annonce['title']} ({annonce['site']})")
                else:
                    logger.debug(f"Active : {annonce['title']}")

                consecutive_network_errors = 0
                checked += 1
                _mark_checked(annonce["id"])

            except Exception as e:
                err_str = str(e).lower()
                is_network_error = any(p in err_str for p in _NETWORK_ERROR_PATTERNS)

                if is_network_error:
                    network_errors += 1
                    consecutive_network_errors += 1
                    logger.warning(f"Erreur réseau sur {annonce['url']} : {e}")
                    if consecutive_network_errors >= MAX_CONSECUTIVE_NETWORK_ERRORS:
                        logger.error(
                            f"Connexion perdue — arrêt après "
                            f"{consecutive_network_errors} erreurs réseau consécutives."
                        )
                        break
                    # checked_at non mis à jour → sera re-tenté au prochain run
                else:
                    page_errors += 1
                    consecutive_network_errors = 0
                    logger.warning(f"Erreur de page sur {annonce['url']} : {e}")
                    checked += 1
                    _mark_checked(annonce["id"])
            finally:
                page.close()

        context.close()
        browser.close()

    _notify_gone(gone)
    summary = {
        "checked": checked,
        "expired": expired,
        "still_active": checked - expired - page_errors,
        "network_errors": network_errors,
        "page_errors": page_errors,
    }
    logger.info(
        f"Vérification terminée : {checked} vérifiées, "
        f"{expired} expirées, {network_errors} erreurs réseau, {page_errors} erreurs de page"
    )
    return summary
