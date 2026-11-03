# scrapers/enricher.py
# =========================
# Enrichissement des annonces (détails via page individuelle)
# =========================

import random
import time
from datetime import datetime
from typing import Optional

from config import (
    ENRICHMENT_DEFAULT_LIMIT,
    ENRICHMENT_MAX_DELAY,
    ENRICHMENT_MIN_DELAY,
    PAGE_LOAD_TIMEOUT,
)
from scrapers.antibot import is_page_blocked, wait_for_challenge
from scrapers.browser import chrome_session, BrowserError
from storage.sqlite import get_pending_annonces, init_db, update_annonce_enrichment
from utils.logger import setup_logger

logger = setup_logger("enricher")


def _mark_error(url: str):
    update_annonce_enrichment(url, {
        "enrichment_status": "error",
        "enriched_at": datetime.now().isoformat(),
    })


def _extractor_for(site: str):
    site = (site or "").lower()
    if "seloger" in site:
        from scrapers.detail_extractors.seloger_detail import extract_detail
        return extract_detail
    if "leboncoin" in site or "lbc" in site:
        from scrapers.detail_extractors.leboncoin_detail import extract_detail
        return extract_detail
    return None


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

    enriched_count = 0
    error_count = 0

    try:
        with chrome_session() as (_browser, page):
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
                except Exception as nav_err:
                    logger.warning(f"Erreur navigation {url}: {nav_err}")
                    _mark_error(url)
                    error_count += 1
                    continue

                # Vérification challenge anti-bot
                if is_page_blocked(page) and not wait_for_challenge(page, timeout_seconds=180):
                    logger.error("Challenge non résolu, arrêt de l'enrichissement.")
                    break

                # Sélectionner l'extracteur selon le site
                extract_detail = _extractor_for(site)
                if extract_detail is None:
                    logger.warning(f"Site inconnu '{site}' pour {url}, ignoré")
                    _mark_error(url)
                    error_count += 1
                    continue

                try:
                    detail_data = extract_detail(page, url)
                except Exception as extract_err:
                    logger.error(f"Erreur extracteur {site} pour {url}: {extract_err}", exc_info=True)
                    detail_data = {"enrichment_status": "error", "error_detail": str(extract_err)[:200]}

                # Toujours marquer enriched_at
                detail_data["enriched_at"] = datetime.now().isoformat()
                update_annonce_enrichment(url, detail_data)

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

    except BrowserError as e:
        logger.error(f"Navigateur indisponible : {e}")
        raise
    except Exception as e:
        logger.error(f"Erreur critique dans l'enrichissement : {e}", exc_info=True)
        raise

    total = len(pending)
    logger.info(
        f"Enrichissement terminé : {enriched_count}/{total} enrichis, {error_count} erreurs"
    )
    return {"total": total, "enriched": enriched_count, "errors": error_count}
