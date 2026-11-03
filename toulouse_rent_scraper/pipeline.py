# pipeline.py
# =========================
# Pipeline de scraping : recherches (profil × site) → validation → filtre
# par profil → stockage → doublons → rapports.
# Utilisé par la CLI (main.py) et, via la CLI, par le bouton de l'UI.
# =========================

import random
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from config import (
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
    new_by_profile: Counter = field(default_factory=Counter)

    def __iadd__(self, other: "RunStats") -> "RunStats":
        for name in self.__dataclass_fields__:
            if name == "new_by_profile":
                self.new_by_profile.update(other.new_by_profile)
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
        if self.duplicates:
            logger.warning(f"  - Doublons détectés : {self.duplicates}")


def process_annonces(raw_annonces: Sequence[Dict], site_name: str) -> RunStats:
    """
    Traite les annonces brutes d'une recherche : validation, filtre par profil
    (budget, pièces, rayon), insertion, rattachement aux profils, doublons.
    """
    from filters.price_and_distance import match_profiles
    from storage.sqlite import (
        insert_annonce, find_potential_duplicates, set_duplicate_of, upsert_annonce_profile,
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

        filtered, matches = match_profiles(annonce)
        if not filtered:
            stats.rejected += 1
            continue
        stats.kept += 1

        result = insert_annonce(filtered)

        matched_labels = []
        for profile, dist in matches:
            matched_labels.append(f"{profile.label} {dist}km")
            if upsert_annonce_profile(filtered["url"], profile.key, dist):
                stats.new_by_profile[profile.key] += 1

        # Même bien publié sur un autre site
        potential_dups = find_potential_duplicates(filtered)
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


def run_scraping(
    profiles: List[SearchProfile],
    site_keys: List[str],
    sleep=time.sleep,
) -> RunStats:
    """
    Lance une recherche par couple (profil, site), traite les résultats et génère
    les rapports. Les annonces trouvées sont testées contre TOUS les profils actifs.
    """
    from reporting.generator import generate_summary_reports
    from scrapers import get_scraper_class
    from storage.sqlite import init_db

    run_start = datetime.now()
    init_db()

    total = RunStats()
    runs = [(p, key) for p in profiles for key in site_keys]
    launched = 0

    for profile, site_key in runs:
        scraper = get_scraper_class(site_key)(profile)
        site_name = scraper.site_name()

        if not scraper.search_url():
            logger.warning(f"--- {site_name} / {profile.label} : recherche non configurée, ignoré ---")
            continue

        # Changement de recherche : pause longue pour limiter la détection anti-bot
        if launched:
            pause = random.uniform(PROFILE_SWITCH_MIN_DELAY, PROFILE_SWITCH_MAX_DELAY)
            logger.info(f"Pause de {pause:.0f}s avant la recherche suivante")
            sleep(pause)
        launched += 1

        logger.info(f"--- Scraping {site_name} — profil {profile.label} ---")
        raw_annonces = scraper.scrape()
        logger.info(f"🔍 {len(raw_annonces)} annonces brutes récupérées de {site_name}")

        stats = process_annonces(raw_annonces, site_name)
        stats.log_summary(f"Résumé {site_name} — {profile.label}")
        total += stats

    logger.info("=" * 50)
    logger.info(f"Recherches lancées : {launched}/{len(runs)}")
    total.log_summary("✅ Résumé global")
    logger.info("🎯 Terminé.")

    generate_summary_reports(run_start)
    logger.info("📄 Rapports générés dans le dossier reports/")
    return total
