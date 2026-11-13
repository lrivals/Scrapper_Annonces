# scrapers/enricher.py
# =========================
# Enrichissement des annonces (détails via page individuelle)
# =========================

import random
import time
from datetime import datetime
from typing import Optional

from config import (
    CHALLENGE_TIMEOUT_SECONDS,
    UNATTENDED_CHALLENGE_TIMEOUT_SECONDS,
    ENRICHMENT_DEFAULT_LIMIT,
    ENRICHMENT_MAX_ATTEMPTS,
    ENRICHMENT_MAX_DELAY,
    ENRICHMENT_MIN_DELAY,
    PAGE_LOAD_TIMEOUT,
)
from scrapers.antibot import is_page_blocked, record_block, wait_for_challenge
from scrapers.browser import chrome_session, BrowserError
from storage.cleaner import is_expired_content
from storage.sqlite import (
    get_coordinates,
    get_pending_annonces,
    init_db,
    set_annonce_status,
    set_distances,
    update_annonce_enrichment,
)
from utils.logger import setup_logger

logger = setup_logger("enricher")


def _failure_status(attempts: int) -> str:
    """« error » tant qu'un nouvel essai est prévu, « failed » ensuite."""
    return "failed" if attempts >= ENRICHMENT_MAX_ATTEMPTS else "error"


def _mark_error(url: str, attempts: int, detail: str):
    update_annonce_enrichment(url, {
        "enrichment_status": _failure_status(attempts),
        "enrichment_attempts": attempts,
        "error_detail": detail[:200],
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


def _refresh_distances(url: str) -> bool:
    """
    L'annonce a maintenant un point GPS exact : distances ENAC et profils recalculées
    (elles venaient du géocodage de l'adresse texte, souvent le centre de la commune).
    """
    from config import ENAC_LATITUDE, ENAC_LONGITUDE, SEARCH_PROFILES
    from geo.distance import distance_km

    coords = get_coordinates(url)
    if not coords or coords.get("geo_precision") != "exact" or coords.get("lat") is None:
        return False
    point = (coords["lat"], coords["lon"])
    by_profile = {key: distance_km(point, p.target) for key, p in SEARCH_PROFILES.items()}
    set_distances(coords["id"], distance_km(point, (ENAC_LATITUDE, ENAC_LONGITUDE)), by_profile)
    return True


def report_extraction_health(rows_by_site: dict) -> list:
    """Alerte (log + notification) si un site renvoie des fiches anormalement vides."""
    from storage.quality import check_fill_rates

    alerts = check_fill_rates(rows_by_site)
    for alert in alerts:
        logger.warning(f"🩺 {alert}")
    if alerts:
        from notify import send
        send(
            "Extraction dégradée — sélecteurs à vérifier",
            "\n".join(alerts) + "\n\nDétail : python main.py quality",
            priority="high",
            tags=["warning"],
        )
    return alerts


def enrich_annonces(
    site_filter: Optional[str] = None,
    limit: int = ENRICHMENT_DEFAULT_LIMIT,
    unattended: bool = False,
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
        return {"total": 0, "enriched": 0, "errors": 0, "expired": 0}

    logger.info(f"Enrichissement de {len(pending)} annonce(s) (limit={limit}, site={site_filter or 'tous'})")

    enriched_count = 0
    error_count = 0
    expired_count = 0
    relocated_count = 0
    done_by_site: dict = {}

    try:
        with chrome_session() as (_browser, page):
            for idx, annonce in enumerate(pending, 1):
                url = annonce["url"]
                site = annonce.get("site", "")
                attempts = (annonce.get("enrichment_attempts") or 0) + 1
                retry = f" (tentative {attempts}/{ENRICHMENT_MAX_ATTEMPTS})" if attempts > 1 else ""
                logger.info(f"[{idx}/{len(pending)}] Enrichissement {site}{retry} : {url[:80]}")

                # Délai entre pages (sauf première)
                if idx > 1:
                    delay = random.uniform(ENRICHMENT_MIN_DELAY, ENRICHMENT_MAX_DELAY)
                    logger.debug(f"Pause {delay:.1f}s avant prochaine page")
                    time.sleep(delay)

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                except Exception as nav_err:
                    logger.warning(f"Erreur navigation {url}: {nav_err}")
                    _mark_error(url, attempts, f"navigation : {nav_err}")
                    error_count += 1
                    continue

                # Vérification challenge anti-bot
                if is_page_blocked(page):
                    from notify import notify_captcha
                    timeout = UNATTENDED_CHALLENGE_TIMEOUT_SECONDS if unattended else CHALLENGE_TIMEOUT_SECONDS
                    if not wait_for_challenge(
                        page, timeout, on_challenge=lambda: notify_captcha(site or "enrichissement", timeout)
                    ):
                        record_block(site or "enrichissement")
                        logger.error("Challenge non résolu, arrêt de l'enrichissement.")
                        break

                # Annonce retirée du site : inutile d'extraire ni de retenter
                try:
                    removed = is_expired_content(page.content())
                except Exception:
                    removed = False
                if removed:
                    logger.info(f"  ⌀ Annonce retirée du site : {url[:80]}")
                    set_annonce_status(annonce["id"], "expired")
                    update_annonce_enrichment(url, {
                        "enrichment_status": "skipped",
                        "enrichment_attempts": attempts,
                        "enriched_at": datetime.now().isoformat(),
                    })
                    expired_count += 1
                    continue

                # Sélectionner l'extracteur selon le site
                extract_detail = _extractor_for(site)
                if extract_detail is None:
                    logger.warning(f"Site inconnu '{site}' pour {url}, ignoré")
                    _mark_error(url, ENRICHMENT_MAX_ATTEMPTS, f"site inconnu : {site}")
                    error_count += 1
                    continue

                try:
                    detail_data = extract_detail(page, url)
                except Exception as extract_err:
                    logger.error(f"Erreur extracteur {site} pour {url}: {extract_err}", exc_info=True)
                    detail_data = {"enrichment_status": "error", "error_detail": str(extract_err)[:200]}

                # Toujours marquer enriched_at et la tentative
                detail_data["enriched_at"] = datetime.now().isoformat()
                detail_data["enrichment_attempts"] = attempts
                if detail_data.get("enrichment_status") != "done":
                    detail_data["enrichment_status"] = _failure_status(attempts)
                    detail_data.setdefault("error_detail", "extraction incomplète")
                update_annonce_enrichment(url, detail_data)

                if detail_data.get("enrichment_status") == "done":
                    enriched_count += 1
                    done_by_site.setdefault(site or "?", []).append(detail_data)
                    if detail_data.get("geo_precision") == "exact" and _refresh_distances(url):
                        relocated_count += 1
                    logger.info(
                        f"  ✓ Enrichi ({detail_data.get('extraction_source', '?')}) : "
                        f"surface={detail_data.get('surface_m2')}m², "
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

    report_extraction_health(done_by_site)

    # Nouvelles descriptions : analyse LLM (15.4, si activée) avant le recalcul des scores
    if enriched_count:
        from analysis.llm import maybe_analyze
        maybe_analyze("enrichissement")

    # Surface, charges, DPE, position… ont changé : les scores aussi
    if enriched_count:
        from scoring import rescore
        rescore()

    total = len(pending)
    logger.info(
        f"Enrichissement terminé : {enriched_count}/{total} enrichis, {error_count} erreurs, "
        f"{expired_count} annonces retirées, {relocated_count} repositionnées (GPS exact)"
    )
    return {
        "total": total, "enriched": enriched_count, "errors": error_count,
        "expired": expired_count, "relocated": relocated_count,
    }
