# main.py
# =========================
# Pipeline principal du projet
# =========================

import argparse
import sys
from datetime import datetime

from config import SEARCH_PROFILES, enabled_profiles
from utils.logger import setup_logger

# Configuration du logger
logger = setup_logger('main')


def parse_args():
    parser = argparse.ArgumentParser(description="Scraper d'annonces immobilieres Toulouse (profils ENAC, Blagnac…)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seloger", action="store_true", help="Scanner uniquement SeLoger")
    group.add_argument("--leboncoin", action="store_true", help="Scanner uniquement LeBonCoin")
    group.add_argument("--all", action="store_true", default=True, help="Scanner tous les sites (defaut)")
    parser.add_argument("--export", choices=["csv", "json"], help="Exporter les annonces en CSV ou JSON")
    parser.add_argument("--purge", action="store_true", help="Vérifier et marquer les annonces expirées")
    parser.add_argument("--ui", action="store_true", help="Lancer l'interface web de navigation des annonces")
    parser.add_argument("--port", type=int, default=5000, help="Port pour l'interface web (defaut: 5000)")
    parser.add_argument("--check-links", action="store_true", dest="check_links",
                        help="Vérifier les liens via navigateur et marquer les annonces expirées")
    parser.add_argument("--enrich", action="store_true",
                        help="Enrichir les annonces avec les données de détail (surface, DPE, etc.)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Nombre max d'annonces à traiter (--check-links ou --enrich)")
    parser.add_argument("--profile", action="append", choices=sorted(SEARCH_PROFILES),
                        help="Profil de recherche (répétable). Défaut : tous les profils actifs")
    return parser.parse_args()


def selected_profiles(keys):
    """Profils demandés via --profile, ou tous les profils actifs."""
    if keys:
        return [SEARCH_PROFILES[k] for k in dict.fromkeys(keys)]
    return enabled_profiles()


def main():
    args = parse_args()

    if args.ui:
        from ui import run_ui
        run_ui(port=args.port)
        return

    explicit_scraping = args.seloger or args.leboncoin or "--all" in sys.argv
    if args.enrich and not explicit_scraping:
        from scrapers.enricher import enrich_annonces
        from config import ENRICHMENT_DEFAULT_LIMIT

        limit = args.limit if args.limit is not None else ENRICHMENT_DEFAULT_LIMIT
        summary = enrich_annonces(site_filter=None, limit=limit)
        print(
            f"Enrichissement terminé : {summary['enriched']}/{summary['total']} enrichis, "
            f"{summary['errors']} erreurs"
        )
        return

    if args.check_links:
        from storage.cleaner import check_links_playwright
        summary = check_links_playwright(limit=args.limit)
        print(
            f"Vérification terminée : {summary['checked']} vérifiées, "
            f"{summary['expired']} expirées, "
            f"{summary['network_errors']} erreurs réseau (non vérifiées), "
            f"{summary['page_errors']} erreurs de page"
        )
        return

    import random
    import time

    from config import SEARCH_PROFILES, PROFILE_SWITCH_MIN_DELAY, PROFILE_SWITCH_MAX_DELAY
    from scrapers import SCRAPERS
    from scrapers.seloger import SeLogerScraper
    from scrapers.leboncoin import LeBonCoinScraper
    from filters.price_and_distance import match_profiles
    from storage.sqlite import (
        init_db, insert_annonce, find_potential_duplicates, set_duplicate_of,
        upsert_annonce_profile,
    )
    from reporting.generator import generate_summary_reports
    from reporting.exporter import run_export
    from storage.cleaner import check_expired_annonces
    from utils.validation import validate_annonce

    scraper_map = {
        "seloger": SeLogerScraper,
        "leboncoin": LeBonCoinScraper,
    }

    if args.seloger:
        scrapers_to_run = [scraper_map["seloger"]]
    elif args.leboncoin:
        scrapers_to_run = [scraper_map["leboncoin"]]
    else:
        scrapers_to_run = SCRAPERS

    # Profils dont on lance les recherches ; les annonces trouvées sont
    # testées contre TOUS les profils actifs (recoupements gratuits)
    profiles_to_search = selected_profiles(args.profile)

    sites_label = ", ".join(s().site_name() for s in scrapers_to_run)
    profiles_label = ", ".join(p.label for p in profiles_to_search)
    logger.info(f"Demarrage du scraper — profils: {profiles_label} — sites: {sites_label}")

    run_start_time = datetime.now()

    try:
        # Initialisation base
        init_db()
        logger.info("Base de données initialisée")

        total_raw = 0
        total_kept = 0
        total_rejected = 0
        total_inserted = 0
        total_updated = 0
        total_unchanged = 0
        total_reactivated = 0
        total_validation_errors = 0
        total_duplicates = 0
        new_by_profile = {key: 0 for key in SEARCH_PROFILES}

        runs = [(profile, ScraperClass) for profile in profiles_to_search for ScraperClass in scrapers_to_run]

        # Boucle sur les couples (profil, site)
        for run_idx, (profile, ScraperClass) in enumerate(runs):
            scraper = ScraperClass(profile)
            site_name = scraper.site_name()

            if not scraper.search_url():
                logger.warning(f"--- {site_name} / {profile.label} : recherche non configurée, ignoré ---")
                continue

            # Changement de recherche : pause longue pour limiter la détection anti-bot
            if run_idx > 0:
                pause = random.uniform(PROFILE_SWITCH_MIN_DELAY, PROFILE_SWITCH_MAX_DELAY)
                logger.info(f"Pause de {pause:.0f}s avant la recherche suivante")
                time.sleep(pause)

            logger.info(f"--- Scraping {site_name} — profil {profile.label} ---")
            raw_annonces = scraper.scrape()
            logger.info(f"🔍 {len(raw_annonces)} annonces brutes récupérées de {site_name}")

            kept = 0
            rejected = 0
            inserted = 0
            updated = 0
            unchanged = 0
            reactivated = 0
            validation_errors = 0
            duplicates = 0

            for annonce in raw_annonces:
                # Validation des données brutes
                validation_error = validate_annonce(annonce)
                if validation_error:
                    logger.warning(f"Annonce invalide ({site_name}) : {validation_error}")
                    validation_errors += 1
                    rejected += 1
                    continue

                # Filtrage par profil : budget, pièces, rayon autour de chaque cible
                filtered, matches = match_profiles(annonce)

                if not filtered:
                    rejected += 1
                    continue

                kept += 1

                # Insertion ou mise à jour en base
                result = insert_annonce(filtered)

                matched_labels = []
                for matched_profile, dist in matches:
                    matched_labels.append(f"{matched_profile.label} {dist}km")
                    if upsert_annonce_profile(filtered["url"], matched_profile.key, dist):
                        new_by_profile[matched_profile.key] += 1

                # Détection de doublons (même bien publié sur un autre site)
                potential_dups = find_potential_duplicates(filtered)
                if potential_dups:
                    original = potential_dups[0]
                    if set_duplicate_of(filtered["url"], original["id"]):
                        duplicates += 1
                        logger.warning(
                            f"⚠ Doublon détecté ({site_name}) : "
                            f"\"{filtered['title']} {filtered['price']}€\" "
                            f"↔ \"{original['title']} {original['price']}€\" ({original['url']})"
                        )
                if result == "new":
                    inserted += 1
                    logger.info(
                        f"✨ Nouvelle annonce ({site_name}) : {filtered['title']} - "
                        f"{filtered['price']}€ - {', '.join(matched_labels)}"
                    )
                elif result == "reactivated":
                    reactivated += 1
                    logger.info(
                        f"♻ Annonce réactivée ({site_name}) : {filtered['title']} - "
                        f"{filtered['price']}€"
                    )
                elif result == "updated":
                    updated += 1
                    logger.info(
                        f"🔄 Prix mis à jour ({site_name}) : {filtered['title']} - "
                        f"{filtered['price']}€"
                    )
                else:
                    unchanged += 1

            # Résumé par site
            logger.info(f"📊 Résumé {site_name} — {profile.label} :")
            logger.info(f"  - Annonces brutes : {len(raw_annonces)}")
            logger.info(f"  - Erreurs de validation : {validation_errors}")
            logger.info(f"  - Annonces filtrées conservées : {kept}")
            logger.info(f"  - Annonces rejetées : {rejected}")
            logger.info(
                f"  - Nouvelles : {inserted} | Réactivées : {reactivated} | "
                f"Mises à jour : {updated} | Inchangées : {unchanged}"
            )
            if duplicates:
                logger.warning(f"  - Doublons détectés : {duplicates}")

            total_raw += len(raw_annonces)
            total_kept += kept
            total_rejected += rejected
            total_inserted += inserted
            total_updated += updated
            total_unchanged += unchanged
            total_reactivated += reactivated
            total_validation_errors += validation_errors
            total_duplicates += duplicates

        # Résumé global
        logger.info("=" * 50)
        logger.info("✅ Résumé global")
        logger.info(f"  - Recherches lancées : {len(runs)} ({profiles_label} × {sites_label})")
        logger.info(f"  - Annonces brutes totales : {total_raw}")
        logger.info(f"  - Erreurs de validation : {total_validation_errors}")
        logger.info(f"  - Annonces conservées : {total_kept}")
        logger.info(f"  - Annonces rejetées : {total_rejected}")
        logger.info(
            f"  - Nouvelles : {total_inserted} | Réactivées : {total_reactivated} | "
            f"Mises à jour : {total_updated} | Inchangées : {total_unchanged}"
        )
        for key, count in new_by_profile.items():
            logger.info(f"  - Nouvelles pour {SEARCH_PROFILES[key].label} : {count}")
        if total_duplicates:
            logger.warning(f"  - Doublons détectés : {total_duplicates} (vérifier les logs)")
        logger.info("🎯 Terminé.")

        # Génération des rapports Markdown
        generate_summary_reports(run_start_time)
        logger.info("📄 Rapports générés dans le dossier reports/")

        # Enrichissement post-scraping si --enrich
        if args.enrich:
            from scrapers.enricher import enrich_annonces
            from config import ENRICHMENT_DEFAULT_LIMIT

            site_filter = None
            if args.seloger:
                site_filter = "SeLoger"
            elif args.leboncoin:
                site_filter = "LeBonCoin"

            limit = args.limit if args.limit is not None else ENRICHMENT_DEFAULT_LIMIT
            summary = enrich_annonces(site_filter=site_filter, limit=limit)
            logger.info(
                f"Enrichissement : {summary['enriched']}/{summary['total']} enrichis, "
                f"{summary['errors']} erreurs"
            )

        # Purge des annonces expirées si demandé
        if args.purge:
            logger.info("Vérification des annonces expirées...")
            summary = check_expired_annonces()
            logger.info(
                f"Purge : {summary['expired']} expirées / {summary['checked']} vérifiées"
            )

        # Export CSV/JSON si demandé
        if args.export:
            export_path = run_export(args.export)
            logger.info(f"📦 Export {args.export.upper()} généré : {export_path}")

    except Exception as e:
        logger.error(f"❌ Erreur critique dans le pipeline : {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
