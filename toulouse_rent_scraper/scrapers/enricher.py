# scrapers/enricher.py
# =========================
# Enrichissement des annonces (détails via page individuelle)
# =========================

import random
import subprocess
import time
from datetime import datetime
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import (
    BROWSER_PROFILE_DIR,
    ENRICHMENT_DEFAULT_LIMIT,
    ENRICHMENT_MAX_DELAY,
    ENRICHMENT_MIN_DELAY,
    PAGE_LOAD_TIMEOUT,
)
from storage.sqlite import get_pending_annonces, init_db, update_annonce_enrichment
from utils.logger import setup_logger

logger = setup_logger("enricher")

# Marqueurs de challenge anti-bot (identiques à BaseScraper)
_BLOCKED_DOMAINS = ["captcha-delivery.com", "datadome.co", "arkoselabs.com"]
_CHALLENGE_MARKERS = [
    "activité suspecte",
    "comportement du navigateur",
    "vitesse surhumaine",
    "accès temporairement restreint",
    "non pas à un robot",
    "we need to make sure",
    "suspicious activity",
]
_BLOCK_TITLES = ["accès restreint", "blocked", "captcha", "restricted"]


def _is_page_blocked(page) -> bool:
    current_url = page.url
    if any(domain in current_url for domain in _BLOCKED_DOMAINS):
        return True
    try:
        page_text = page.inner_text("body").lower()
        if any(m.lower() in page_text for m in _CHALLENGE_MARKERS):
            return True
    except Exception:
        pass
    try:
        title = page.title().lower()
        if any(t in title for t in _BLOCK_TITLES):
            return True
    except Exception:
        pass
    return False


def _wait_for_challenge(page, timeout_seconds: int = 180) -> bool:
    """Attend la résolution manuelle d'un challenge. Retourne True si résolu."""
    if not _is_page_blocked(page):
        return True
    logger.warning("=" * 60)
    logger.warning("CHALLENGE ANTI-BOT DETECTE !")
    logger.warning("Resolvez le captcha dans la fenetre Chrome.")
    logger.warning(f"Vous avez {timeout_seconds}s...")
    logger.warning("=" * 60)
    start = time.time()
    while time.time() - start < timeout_seconds:
        time.sleep(3)
        try:
            if not _is_page_blocked(page):
                logger.info("Challenge resolu ! Reprise de l'enrichissement...")
                time.sleep(2)
                return True
            remaining = int(timeout_seconds - (time.time() - start))
            if remaining % 15 == 0:
                logger.info(f"En attente de resolution... ({remaining}s restantes)")
        except Exception:
            continue
    logger.error("Timeout : challenge non resolu")
    return False


def enrich_annonces(
    site_filter: Optional[str] = None,
    limit: int = ENRICHMENT_DEFAULT_LIMIT,
) -> dict:
    """
    Enrichit les annonces en attente en naviguant vers chaque URL.

    Args:
        site_filter: 'SeLoger' ou 'LeBonCoin' pour filtrer par site, None = tous
        limit: nombre max d'annonces à traiter par session

    Returns:
        dict avec les clés 'total', 'enriched', 'errors'
    """
    init_db()

    pending = get_pending_annonces(site_filter=site_filter, limit=limit)
    if not pending:
        logger.info("Aucune annonce à enrichir.")
        return {"total": 0, "enriched": 0, "errors": 0}

    logger.info(f"Enrichissement de {len(pending)} annonce(s) (limit={limit}, site={site_filter or 'tous'})")

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    enriched_count = 0
    error_count = 0
    chrome_proc = None

    try:
        with sync_playwright() as p:
            chrome_cmd = [
                "google-chrome",
                "--remote-debugging-port=9222",
                f"--user-data-dir={BROWSER_PROFILE_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1920,1080",
            ]

            logger.info("Lancement de Chrome avec port de debug...")
            chrome_proc = subprocess.Popen(
                chrome_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(3)

            logger.info("Connexion a Chrome via CDP...")
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()

            for idx, annonce in enumerate(pending, 1):
                url = annonce["url"]
                site = annonce.get("site", "")
                logger.info(f"[{idx}/{len(pending)}] Enrichissement {site} : {url[:80]}")

                # Délai entre pages (sauf première)
                if idx > 1:
                    delay = random.uniform(ENRICHMENT_MIN_DELAY, ENRICHMENT_MAX_DELAY)
                    logger.debug(f"Pause {delay:.1f}s avant prochaine page")
                    time.sleep(delay)

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                except PlaywrightTimeoutError:
                    logger.warning(f"Timeout navigation vers {url}")
                    update_annonce_enrichment(url, {
                        "enrichment_status": "error",
                        "enriched_at": datetime.now().isoformat(),
                    })
                    error_count += 1
                    continue
                except Exception as nav_err:
                    logger.warning(f"Erreur navigation {url}: {nav_err}")
                    update_annonce_enrichment(url, {
                        "enrichment_status": "error",
                        "enriched_at": datetime.now().isoformat(),
                    })
                    error_count += 1
                    continue

                # Vérification challenge anti-bot
                if _is_page_blocked(page):
                    resolved = _wait_for_challenge(page, timeout_seconds=180)
                    if not resolved:
                        logger.error("Challenge non résolu, arrêt de l'enrichissement.")
                        break

                # Sélectionner l'extracteur selon le site
                try:
                    if "seloger" in site.lower():
                        from scrapers.detail_extractors.seloger_detail import extract_detail
                    elif "leboncoin" in site.lower() or "lbc" in site.lower():
                        from scrapers.detail_extractors.leboncoin_detail import extract_detail
                    else:
                        logger.warning(f"Site inconnu '{site}' pour {url}, ignoré")
                        update_annonce_enrichment(url, {
                            "enrichment_status": "error",
                            "enriched_at": datetime.now().isoformat(),
                        })
                        error_count += 1
                        continue

                    detail_data = extract_detail(page, url)

                except Exception as extract_err:
                    logger.error(f"Erreur extracteur {site} pour {url}: {extract_err}", exc_info=True)
                    detail_data = {"enrichment_status": "error", "error_detail": str(extract_err)[:200]}

                # Toujours marquer enriched_at
                detail_data["enriched_at"] = datetime.now().isoformat()

                updated = update_annonce_enrichment(url, detail_data)

                if detail_data.get("enrichment_status") == "done":
                    enriched_count += 1
                    logger.info(
                        f"  ✓ Enrichi : surface={detail_data.get('surface_m2')}m², "
                        f"pièces={detail_data.get('nb_rooms')}, DPE={detail_data.get('dpe_rating')}"
                    )
                else:
                    error_count += 1
                    logger.warning(
                        f"  ✗ Erreur enrichissement : {detail_data.get('error_detail', 'inconnu')}"
                    )

            browser.close()

    except Exception as e:
        logger.error(f"Erreur critique dans l'enrichissement : {e}", exc_info=True)
        raise

    finally:
        if chrome_proc is not None:
            try:
                chrome_proc.terminate()
                chrome_proc.wait(timeout=5)
            except Exception:
                pass

    total = len(pending)
    logger.info(
        f"Enrichissement terminé : {enriched_count}/{total} enrichis, {error_count} erreurs"
    )
    return {"total": total, "enriched": enriched_count, "errors": error_count}
