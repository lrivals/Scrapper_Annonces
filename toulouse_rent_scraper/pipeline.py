# pipeline.py
# =========================
# Pipeline de scraping : recherches (profil × site) → validation → filtre
# par profil → stockage → doublons → ouverture des fiches retenues (Sprint 16)
# → dedup photo, LLM, scores → notifications → rapports.
# Utilisé par la CLI (main.py) et, via la CLI, par le bouton de l'UI.
# =========================

import random
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from config import (
    NOTIFY_PRICE_DROP_EUR,
    SEARCH_PROFILES,
    PROFILE_SWITCH_MIN_DELAY,
    PROFILE_SWITCH_MAX_DELAY,
    SearchProfile,
)
from utils.logger import setup_logger

logger = setup_logger("main")


@dataclass
class RunStats:
    """Compteurs d'un lot d'annonces (une recherche) ou d'un run complet."""
    raw: int = 0
    kept: int = 0
    rejected: int = 0
    validation_errors: int = 0
    inserted: int = 0
    reactivated: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: int = 0
    prefilled: int = 0          # fiches remplies depuis le JSON de la recherche (15.2)
    # Sprint 16 — pages de détail ouvertes pendant le run
    opened: int = 0
    enriched: int = 0
    expired: int = 0
    relocated: int = 0
    # URL des annonces conservées (≥ 1 profil) : ouvertes en priorité (16.2)
    retained_urls: List[str] = field(default_factory=list)
    new_by_profile: Counter = field(default_factory=Counter)
    # Événements à notifier : {"kind": "new" | "price_drop", "profile", "url", "old_price"?}
    events: List[Dict] = field(default_factory=list)

    def __iadd__(self, other: "RunStats") -> "RunStats":
        for name in self.__dataclass_fields__:
            if name == "new_by_profile":
                self.new_by_profile.update(other.new_by_profile)
            elif name in ("events", "retained_urls"):
                getattr(self, name).extend(getattr(other, name))
            else:
                setattr(self, name, getattr(self, name) + getattr(other, name))
        return self

    def log_summary(self, title: str):
        logger.info(f"📊 {title} :")
        logger.info(f"  - Annonces brutes : {self.raw}")
        logger.info(f"  - Erreurs de validation : {self.validation_errors}")
        logger.info(f"  - Annonces conservées : {self.kept}")
        logger.info(f"  - Annonces rejetées : {self.rejected}")
        logger.info(
            f"  - Nouvelles : {self.inserted} | Réactivées : {self.reactivated} | "
            f"Mises à jour : {self.updated} | Inchangées : {self.unchanged}"
        )
        for key, count in self.new_by_profile.items():
            label = SEARCH_PROFILES[key].label if key in SEARCH_PROFILES else key
            logger.info(f"  - Nouvelles pour {label} : {count}")
        if self.prefilled:
            logger.info(f"  - Fiches pré-remplies depuis la recherche : {self.prefilled}")
        if self.opened:
            logger.info(
                f"  - Fiches ouvertes : {self.opened} — enrichies {self.enriched}, "
                f"retirées {self.expired}, repositionnées GPS {self.relocated}"
            )
        if self.duplicates:
            logger.warning(f"  - Doublons détectés : {self.duplicates}")


def _exact_coords(annonce: Dict, get_coordinates) -> Optional[tuple]:
    """
    Point GPS exact de l'annonce, prioritaire sur le géocodage de l'adresse :
    celui fourni par la recherche (JSON LBC, 15.2), sinon celui déjà connu en base (15.1).
    """
    if annonce.get("geo_precision") == "exact" and annonce.get("lat") is not None:
        return annonce["lat"], annonce["lon"]
    known = get_coordinates(annonce.get("url", ""))
    if known and known.get("geo_precision") == "exact" and known.get("lat") is not None:
        return known["lat"], known["lon"]
    return None


def _save_search_details(annonce: Dict) -> bool:
    """
    Détails lus dans la page de recherche (Sprint 15.2) : enregistrés tant que l'annonce
    n'a pas été enrichie — une fiche déjà complète (page de détail) n'est pas écrasée.
    Retourne True si des détails ont été enregistrés.
    """
    from storage.sqlite import get_enrichment_status, update_annonce_enrichment

    details = annonce.get("details")
    if not details:
        return False
    if get_enrichment_status(annonce["url"]) == "done":
        return False
    data = dict(details)
    if annonce.get("geo_precision") and annonce.get("lat") is not None:
        data.update(lat=annonce["lat"], lon=annonce["lon"], geo_precision=annonce["geo_precision"])
    if data.get("enrichment_status") == "done":
        data["enriched_at"] = datetime.now().isoformat()
    return update_annonce_enrichment(annonce["url"], data)


def search_health_rows(raw_annonces: Sequence[Dict], site_name: str) -> List[Dict]:
    """
    Lignes pour le contrôle de santé (storage.quality) à partir des annonces d'une recherche.
    Seuls les sites qui fournissent un JSON de recherche sont jugés : une annonce venue
    d'une carte DOM y compte comme extraction `dom` (le JSON a disparu ou est ignoré).
    """
    from config import QUALITY_MIN_JSON_RATE

    if site_name not in QUALITY_MIN_JSON_RATE and not any(a.get("details") for a in raw_annonces):
        return []
    rows = []
    for a in raw_annonces:
        details = a.get("details")
        if details:
            rows.append({**details, "photos": details.get("photos") or None})
        else:
            rows.append({"extraction_source": "dom", "photos": a.get("photos")})
    return rows


def process_annonces(raw_annonces: Sequence[Dict], site_name: str) -> RunStats:
    """
    Traite les annonces brutes d'une recherche : validation, filtre par profil
    (budget, pièces, rayon), insertion, rattachement aux profils, doublons.
    """
    from filters.price_and_distance import match_profiles
    from storage.sqlite import (
        insert_annonce, find_potential_duplicates, get_coordinates, get_price, set_duplicate_of,
        upsert_annonce_profile,
    )
    from utils.validation import validate_annonce

    stats = RunStats(raw=len(raw_annonces))

    for annonce in raw_annonces:
        validation_error = validate_annonce(annonce)
        if validation_error:
            logger.warning(f"Annonce invalide ({site_name}) : {validation_error}")
            stats.validation_errors += 1
            stats.rejected += 1
            continue

        filtered, matches = match_profiles(annonce, known_coords=_exact_coords(annonce, get_coordinates))
        if not filtered:
            stats.rejected += 1
            continue
        stats.kept += 1

        url = filtered["url"]
        stats.retained_urls.append(url)
        old_price = get_price(url)
        result = insert_annonce(filtered)
        if _save_search_details(filtered):
            stats.prefilled += 1
        price_drop = (
            result == "updated" and old_price is not None
            and old_price - filtered["price"] >= NOTIFY_PRICE_DROP_EUR
        )

        matched_labels = []
        for profile, dist in matches:
            matched_labels.append(f"{profile.label} {dist}km")
            if upsert_annonce_profile(url, profile.key, dist):
                stats.new_by_profile[profile.key] += 1
                stats.events.append({"kind": "new", "profile": profile.key, "url": url})
            elif price_drop:
                stats.events.append({"kind": "price_drop", "profile": profile.key, "url": url,
                                     "old_price": old_price})

        # Même bien publié sur un autre site
        # Surface, pièces et GPS des annonces lues en JSON (LBC, Bien'ici) sont dans `details`
        details = filtered.get("details") or {}
        potential_dups = find_potential_duplicates({
            **filtered,
            **{k: details.get(k) for k in ("surface_m2", "nb_rooms", "lat", "lon", "geo_precision")
               if filtered.get(k) is None},
        })
        if potential_dups:
            original = potential_dups[0]
            if set_duplicate_of(filtered["url"], original["id"]):
                stats.duplicates += 1
                logger.warning(
                    f"⚠ Doublon détecté ({site_name}) : "
                    f"\"{filtered['title']} {filtered['price']}€\" "
                    f"↔ \"{original['title']} {original['price']}€\" ({original['url']})"
                )

        title, price = filtered["title"], filtered["price"]
        if result == "new":
            stats.inserted += 1
            logger.info(f"✨ Nouvelle annonce ({site_name}) : {title} - {price}€ - {', '.join(matched_labels)}")
        elif result == "reactivated":
            stats.reactivated += 1
            logger.info(f"♻ Annonce réactivée ({site_name}) : {title} - {price}€")
        elif result == "updated":
            stats.updated += 1
            logger.info(f"🔄 Prix mis à jour ({site_name}) : {title} - {price}€")
        else:
            stats.unchanged += 1

    return stats


def open_retained(
    total: RunStats,
    site_names: List[str],
    unattended: bool = False,
    limit: Optional[int] = None,
    since: Optional[datetime] = None,
) -> Dict[str, List[Dict]]:
    """
    Sprint 16 — ouvre les fiches des annonces retenues (celles du run d'abord, par score),
    dans la limite du budget par site. Met à jour `total` ; retourne les fiches lues par
    site (contrôle de santé). Les favoris retirés sont notifiés.
    """
    from scoring import rescore
    from scrapers.enricher import open_annonces, select_annonces_to_open

    # Score provisoire (et critères éliminatoires connus) pour choisir les fiches à ouvrir
    rescore()
    to_open = select_annonces_to_open(total.retained_urls, site_names, limit=limit)
    if not to_open:
        logger.info("Ouverture des fiches : aucune annonce retenue à compléter")
        return {}
    in_run = sum(1 for a in to_open if a.get("in_run"))
    logger.info(
        f"Ouverture des fiches : {len(to_open)} annonce(s) "
        f"({in_run} de ce run, {len(to_open) - in_run} en attente d'avant)"
    )
    try:
        stats = open_annonces(to_open, unattended=unattended, blocked_since=since)
    except Exception as e:
        # Les annonces de la recherche sont enregistrées : on notifie quand même
        logger.error(f"Ouverture des fiches impossible ({e}) — notifications avec les cartes seules")
        return {}
    total.opened += stats.opened
    total.enriched += stats.enriched
    total.expired += stats.expired
    total.relocated += stats.relocated
    if stats.gone:
        from storage.cleaner import _notify_gone
        _notify_gone(stats.gone)
    return stats.done_by_site


def run_scraping(
    profiles: List[SearchProfile],
    site_keys: List[str],
    sleep=time.sleep,
    unattended: bool = False,
    enrich: bool = True,
    limit: Optional[int] = None,
) -> RunStats:
    """
    Lance une recherche par couple (profil, site), traite les résultats, ouvre les fiches
    des annonces retenues (`enrich`, Sprint 16), recalcule les scores, notifie et génère
    les rapports. Les annonces trouvées sont testées contre TOUS les profils actifs.
    `unattended` (run planifié) : captcha notifié et attendu plus longtemps, et un site
    bloqué récemment est sauté (anti-ban).
    `limit` : plafond global de fiches ouvertes (en plus de DETAIL_VISITS_PER_RUN par site).
    """
    from scrapers.antibot import recently_blocked
    from reporting.generator import generate_summary_reports
    from scrapers import get_scraper_class
    from storage.sqlite import init_db

    run_start = datetime.now()
    init_db()

    total = RunStats()
    runs = [(p, key) for p in profiles for key in site_keys]
    launched = 0
    health_rows: Dict[str, List[Dict]] = {}
    searched_sites: List[str] = []

    for profile, site_key in runs:
        scraper = get_scraper_class(site_key)(profile, unattended=unattended)
        site_name = scraper.site_name()

        if not scraper.search_url():
            logger.warning(f"--- {site_name} / {profile.label} : recherche non configurée, ignoré ---")
            continue

        blocked_at = recently_blocked(site_name)
        if blocked_at:
            if unattended:
                logger.warning(
                    f"--- {site_name} / {profile.label} : bloqué le {blocked_at:%d/%m %H:%M}, "
                    f"site sauté (anti-ban) ---"
                )
                continue
            logger.warning(f"{site_name} a été bloqué le {blocked_at:%d/%m %H:%M} : risque de nouveau blocage")

        # Changement de recherche : pause longue pour limiter la détection anti-bot
        # (inutile avant une source API, qui n'ouvre pas de navigateur)
        if launched and getattr(scraper, "requires_cooldown", True):
            pause = random.uniform(PROFILE_SWITCH_MIN_DELAY, PROFILE_SWITCH_MAX_DELAY)
            logger.info(f"Pause de {pause:.0f}s avant la recherche suivante")
            sleep(pause)
        launched += 1
        if site_name not in searched_sites:
            searched_sites.append(site_name)

        logger.info(f"--- Scraping {site_name} — profil {profile.label} ---")
        raw_annonces = scraper.scrape()
        logger.info(f"🔍 {len(raw_annonces)} annonces brutes récupérées de {site_name}")

        health_rows.setdefault(site_name, []).extend(search_health_rows(raw_annonces, site_name))
        stats = process_annonces(raw_annonces, site_name)
        stats.log_summary(f"Résumé {site_name} — {profile.label}")
        total += stats

    # Ouverture des fiches retenues (Sprint 16) : avant dedup photo, LLM, score et
    # notifications, pour que les alertes portent la fiche complète et respectent les
    # critères qu'elle révèle (DPE, surface…)
    detail_rows: Dict[str, List[Dict]] = {}
    if enrich:
        detail_rows = open_retained(total, searched_sites, unattended, limit, since=run_start)
    elif total.retained_urls:
        logger.info("Ouverture des fiches désactivée (--no-enrich)")

    # Santé de l'extraction : JSON des recherches (15.2), sans juger les champs absents du
    # JSON de recherche (description LBC), et pages de détail ouvertes ci-dessus
    from config import QUALITY_SEARCH_SKIP_FIELDS
    from scrapers.enricher import report_extraction_health
    report_extraction_health(
        {site: rows for site, rows in health_rows.items() if rows},
        skip_fields=QUALITY_SEARCH_SKIP_FIELDS,
        detail_rows_by_site=detail_rows,
    )

    # Doublons inter-sites par empreinte photo (15.8) : avant l'analyse LLM (un doublon
    # réutilise l'analyse de l'original) et les notifications (un bien déjà connu n'est
    # pas annoncé comme nouveau)
    from filters.photo_duplicates import run_photo_dedup
    total.duplicates += run_photo_dedup()["linked"]

    # Analyse LLM des nouvelles descriptions (15.4, si activée) : avant le score et les
    # notifications, pour que le malus « risque d'arnaque » filtre les alertes
    from analysis.llm import maybe_analyze
    maybe_analyze("scraping")

    from scoring import rescore
    from notify import notify_events
    rescore()
    sent = notify_events(total.events)
    if total.events:
        logger.info(f"🔔 {sent} notification(s) pour {len(total.events)} événement(s)")

    logger.info("=" * 50)
    logger.info(f"Recherches lancées : {launched}/{len(runs)}")
    total.log_summary("✅ Résumé global")
    logger.info("🎯 Terminé.")

    # Journal du run (Sprint 5.0) : rapport comparatif et tendances
    try:
        from storage.run_stats import record_run
        record_run(run_start, list(dict.fromkeys(p.key for p in profiles)), searched_sites, total)
    except Exception as e:
        logger.warning(f"Journal du run non enregistré : {e}")

    generate_summary_reports(run_start, profiles=profiles)
    logger.info("📄 Rapports générés dans le dossier reports/")

    # Top 10 par profil (Sprint 5.6, NOTIFY_TOP10)
    from notify import notify_top10
    notify_top10(p.key for p in profiles)
    return total
