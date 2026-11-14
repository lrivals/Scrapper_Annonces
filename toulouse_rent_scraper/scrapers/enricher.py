# scrapers/enricher.py
# =========================
# Enrichissement des annonces (détails via page individuelle)
# =========================

import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from config import (
    CHALLENGE_TIMEOUT_SECONDS,
    UNATTENDED_CHALLENGE_TIMEOUT_SECONDS,
    ENRICHMENT_DEFAULT_LIMIT,
    ENRICHMENT_MAX_ATTEMPTS,
    ENRICHMENT_MAX_DELAY,
    ENRICHMENT_MIN_DELAY,
    PAGE_LOAD_TIMEOUT,
    PROFILE_SWITCH_MAX_DELAY,
    PROFILE_SWITCH_MIN_DELAY,
)
from scrapers.antibot import is_page_blocked, recently_blocked, record_block, wait_for_challenge
from scrapers.browser import chrome_session, BrowserError
from storage.cleaner import page_shows_expired
from storage.sqlite import (
    correct_price,
    get_annonces_by_ids,
    get_annonces_to_open,
    get_coordinates,
    get_pending_annonces,
    linked_profiles,
    unlink_profiles,
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
    if site == "pap":
        from scrapers.detail_extractors.pap_detail import extract_detail
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


def _browser_gone(page, error: Exception) -> bool:
    """True si l'onglet ou le navigateur n'existe plus (inutile de continuer)."""
    try:
        if page.is_closed() is True:
            return True
    except Exception:
        return True
    return "has been closed" in str(error) or "Browser closed" in str(error)


def _apply_detail_price(annonce: dict, price) -> bool:
    """
    Prix lu sur la page de l'annonce (SeLoger) différent de la base : la base est corrigée
    (historique compris) et l'annonce quitte les profils dont elle dépasse maintenant le budget.
    Corrige les prix de cartes mal lus (« 1 004 € » enregistré 4 € le 2026-11-04).
    """
    from config import SEARCH_PROFILES
    from filters.price_and_distance import _price_ok

    if not isinstance(price, int) or price <= 0:
        return False
    old = correct_price(annonce["id"], price)
    if old is None:
        return False
    out = [k for k in linked_profiles(annonce["id"])
           if k in SEARCH_PROFILES and not _price_ok(price, SEARCH_PROFILES[k])]
    unlink_profiles(annonce["id"], out)
    logger.info(f"  💶 Prix corrigé : {old} € → {price} €" + (f" — retirée de {', '.join(out)} (budget)" if out else ""))
    return True


def report_extraction_health(
    rows_by_site: dict, skip_fields: Optional[dict] = None, detail_rows_by_site: Optional[dict] = None,
) -> list:
    """
    Alerte (log + notification) si un site renvoie des fiches anormalement vides.
    `detail_rows_by_site` (Sprint 16) : fiches ouvertes pendant le même run, jugées sans
    `skip_fields` (la page de détail doit tout fournir) ; une seule notification pour les deux.
    """
    from storage.quality import check_fill_rates

    alerts = check_fill_rates(rows_by_site, skip_fields) if rows_by_site else []
    if detail_rows_by_site:
        alerts += [f"Pages de détail — {a}" for a in check_fill_rates(detail_rows_by_site)]
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




@dataclass
class EnrichStats:
    """Résultat d'une phase d'ouverture des fiches (sans post-traitement)."""
    total: int = 0              # annonces à ouvrir
    opened: int = 0             # pages effectivement visitées
    enriched: int = 0
    errors: int = 0
    expired: int = 0
    relocated: int = 0          # point GPS exact → distances recalculées
    repriced: int = 0
    skipped_sites: List[str] = field(default_factory=list)   # bloqués / challenge non résolu
    done_by_site: Dict[str, List[Dict]] = field(default_factory=dict)
    gone: List[Dict] = field(default_factory=list)            # annonces retirées (favoris ⭐ notifiés)

    def as_dict(self) -> dict:
        return {
            "total": self.total, "opened": self.opened, "enriched": self.enriched, "errors": self.errors,
            "expired": self.expired, "relocated": self.relocated, "repriced": self.repriced,
        }


def _by_site(annonces: List[Dict]) -> List[tuple]:
    """[(site, [annonces…])] dans l'ordre de première apparition, ordre conservé dans chaque site."""
    groups: Dict[str, List[Dict]] = {}
    for a in annonces:
        groups.setdefault(a.get("site") or "", []).append(a)
    return list(groups.items())


def _site_blocked(site: str, unattended: bool, blocked_since: Optional[datetime]) -> Optional[datetime]:
    """
    Date du blocage qui interdit d'ouvrir les fiches de `site` :
    en mode planifié, tout blocage récent (même règle que la recherche) ; sinon un blocage
    survenu pendant ce run (`blocked_since` = début du run).
    """
    blocked_at = recently_blocked(site) if site else None
    if not blocked_at:
        return None
    if unattended or (blocked_since is not None and blocked_at >= blocked_since.replace(microsecond=0)):
        return blocked_at
    return None


def open_annonces(
    annonces: List[Dict],
    unattended: bool = False,
    budget: Optional[Dict[str, int]] = None,
    blocked_since: Optional[datetime] = None,
    label: str = "Ouverture des fiches",
) -> EnrichStats:
    """
    Ouvre la page de chaque annonce et enregistre ce que l'extracteur du site y lit
    (navigation, challenge, annonce retirée, prix corrigé, distances GPS) — sans
    post-traitement (santé, dedup photo, LLM, rescore : à la charge de l'appelant).

    Visites groupées par site, pause longue entre deux sites. `budget` : plafond de
    visites par site (absent = illimité). Un challenge non résolu arrête le site
    concerné seulement ; un navigateur fermé arrête tout.
    """
    stats = EnrichStats(total=len(annonces))
    if not annonces:
        return stats

    plan = []
    for site, items in _by_site(annonces):
        blocked_at = _site_blocked(site, unattended, blocked_since)
        if blocked_at:
            logger.warning(f"{label} — {site} : bloqué le {blocked_at:%d/%m %H:%M}, fiches non ouvertes (anti-ban)")
            stats.skipped_sites.append(site)
            continue
        cap = (budget or {}).get(site)
        if cap is not None and len(items) > cap:
            logger.info(f"{label} — {site} : {len(items)} à ouvrir, {cap} ce run (le reste au suivant)")
            items = items[:cap]
        plan.append((site, items))

    count = sum(len(items) for _, items in plan)
    idx = 0
    try:
        with chrome_session() as (_browser, page):
            for site_idx, (site, items) in enumerate(plan):
                if site_idx:
                    pause = random.uniform(PROFILE_SWITCH_MIN_DELAY, PROFILE_SWITCH_MAX_DELAY)
                    logger.info(f"Pause de {pause:.0f}s avant les fiches {site}")
                    time.sleep(pause)
                for site_pos, annonce in enumerate(items):
                    idx += 1
                    if site_pos:
                        delay = random.uniform(ENRICHMENT_MIN_DELAY, ENRICHMENT_MAX_DELAY)
                        logger.debug(f"Pause {delay:.1f}s avant prochaine page")
                        time.sleep(delay)
                    outcome = _open_one(page, annonce, idx, count, unattended, stats, label)
                    if outcome == "browser_gone":
                        logger.error(
                            f"Navigateur fermé — ouverture des fiches interrompue ({idx - 1}/{count} "
                            "traitées) ; les annonces restantes ne sont pas comptées en erreur."
                        )
                        return stats
                    if outcome == "blocked":
                        logger.error(f"Challenge non résolu : arrêt des fiches {site} (les autres sites continuent)")
                        stats.skipped_sites.append(site)
                        break
    except BrowserError as e:
        logger.error(f"Navigateur indisponible : {e}")
        raise
    except Exception as e:
        logger.error(f"Erreur critique pendant l'ouverture des fiches : {e}", exc_info=True)
        raise
    return stats


def _open_one(page, annonce: Dict, idx: int, count: int, unattended: bool, stats: EnrichStats, label: str) -> str:
    """Visite une annonce. Retourne 'ok', 'blocked' (challenge non résolu) ou 'browser_gone'."""
    url = annonce["url"]
    site = annonce.get("site", "")
    attempts = (annonce.get("enrichment_attempts") or 0) + 1
    retry = f" (tentative {attempts}/{ENRICHMENT_MAX_ATTEMPTS})" if attempts > 1 else ""
    logger.info(f"{label} {idx}/{count} ({site}){retry} : {url[:80]}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
    except Exception as nav_err:
        if _browser_gone(page, nav_err):
            # Fenêtre fermée ou Chrome planté : toutes les annonces suivantes
            # échoueraient et seraient pénalisées à tort (constaté le 2026-11-13)
            return "browser_gone"
        logger.warning(f"Erreur navigation {url}: {nav_err}")
        _mark_error(url, attempts, f"navigation : {nav_err}")
        stats.opened += 1
        stats.errors += 1
        return "ok"
    stats.opened += 1

    # Vérification challenge anti-bot
    if is_page_blocked(page):
        from notify import notify_captcha
        timeout = UNATTENDED_CHALLENGE_TIMEOUT_SECONDS if unattended else CHALLENGE_TIMEOUT_SECONDS
        if not wait_for_challenge(
            page, timeout, on_challenge=lambda: notify_captcha(site or "enrichissement", timeout)
        ):
            record_block(site or "enrichissement")
            return "blocked"

    # Annonce retirée du site : inutile d'extraire ni de retenter
    try:
        removed = page_shows_expired(page)
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
        stats.expired += 1
        stats.gone.append(annonce)
        return "ok"

    # Sélectionner l'extracteur selon le site
    extract_detail = _extractor_for(site)
    if extract_detail is None:
        logger.warning(f"Site inconnu '{site}' pour {url}, ignoré")
        _mark_error(url, ENRICHMENT_MAX_ATTEMPTS, f"site inconnu : {site}")
        stats.errors += 1
        return "ok"

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
        stats.enriched += 1
        if _apply_detail_price(annonce, detail_data.get("detail_price")):
            stats.repriced += 1
        stats.done_by_site.setdefault(site or "?", []).append(detail_data)
        if detail_data.get("geo_precision") == "exact" and _refresh_distances(url):
            stats.relocated += 1
        logger.info(
            f"  ✓ Enrichi ({detail_data.get('extraction_source', '?')}) : "
            f"surface={detail_data.get('surface_m2')}m², "
            f"pièces={detail_data.get('nb_rooms')}, DPE={detail_data.get('dpe_rating')}"
        )
    else:
        stats.errors += 1
        logger.warning(f"  ✗ Erreur enrichissement : {detail_data.get('error_detail', 'inconnu')}")
    return "ok"


def select_annonces_to_open(
    run_urls: List[str],
    sites: List[str],
    limit: Optional[int] = None,
    budget: Optional[Dict[str, int]] = None,
) -> List[Dict]:
    """
    Sprint 16.2 — annonces à ouvrir pendant le scraping : au plus `budget[site]` par site
    (sites sans page de détail écartés), puis au plus `limit` en tout, en gardant les
    annonces du run et les meilleurs scores.
    """
    from config import DETAIL_VISITS_PER_RUN

    budget = DETAIL_VISITS_PER_RUN if budget is None else budget
    chosen: List[Dict] = []
    for site in dict.fromkeys(sites):
        cap = budget.get(site, 0)
        if cap > 0 and _extractor_for(site) is not None:
            chosen += get_annonces_to_open(run_urls, cap, [site])
    if limit is not None and len(chosen) > limit:
        chosen.sort(key=lambda a: (-(a.get("in_run") or 0), a.get("best_score") is None,
                                   -(a.get("best_score") or 0)))
        chosen = chosen[:max(limit, 0)]
    return chosen


def post_process_details(done_by_site: dict, gone: List[Dict], enriched: int, origin: str = "enrichissement"):
    """Après une ouverture de fiches hors pipeline : santé, favoris retirés, dedup photo, LLM, scores."""
    report_extraction_health(done_by_site)

    if gone:
        from storage.cleaner import _notify_gone
        _notify_gone(gone)

    if not enriched:
        return
    # Photos complètes : empreintes et doublons par photo (15.8), avant l'analyse LLM
    from filters.photo_duplicates import run_photo_dedup
    run_photo_dedup()
    # Nouvelles descriptions : analyse LLM (15.4, si activée) avant le recalcul des scores
    from analysis.llm import maybe_analyze
    maybe_analyze(origin)
    # Surface, charges, DPE, position… ont changé : les scores aussi
    from scoring import rescore
    rescore()


def enrich_annonces(
    site_filter: Optional[str] = None,
    limit: int = ENRICHMENT_DEFAULT_LIMIT,
    unattended: bool = False,
    ids: Optional[list] = None,
) -> dict:
    """
    Commande `enrich` : ouvre les annonces en attente (ou `ids`) puis fait le post-traitement.

    Args:
        site_filter: 'SeLoger' ou 'LeBonCoin' pour filtrer par site, None = tous
        limit: nombre max d'annonces à traiter par session

    Returns:
        dict avec les clés 'total', 'enriched', 'errors', 'expired', 'relocated', 'repriced'
    """
    init_db()

    # ids : annonces précises, revisitées même déjà enrichies (ex. prix à vérifier)
    pending = get_annonces_by_ids(ids) if ids else get_pending_annonces(site_filter=site_filter, limit=limit)
    if not pending:
        logger.info("Aucune annonce à enrichir.")
        return {"total": 0, "enriched": 0, "errors": 0, "expired": 0}

    logger.info(f"Enrichissement de {len(pending)} annonce(s) (limit={limit}, site={site_filter or 'tous'})")
    stats = open_annonces(pending, unattended=unattended, label="Enrichissement")
    post_process_details(stats.done_by_site, stats.gone, stats.enriched)

    logger.info(
        f"Enrichissement terminé : {stats.enriched}/{stats.total} enrichis, {stats.errors} erreurs, "
        f"{stats.expired} annonces retirées, {stats.relocated} repositionnées (GPS exact), "
        f"{stats.repriced} prix corrigé(s)"
    )
    result = stats.as_dict()
    result.pop("opened")
    return result
