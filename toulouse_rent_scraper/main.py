# main.py
# =========================
# Pipeline principal du projet
# =========================

import argparse
from datetime import datetime

from scrapers import SCRAPERS
from scrapers.seloger import SeLogerScraper
from scrapers.leboncoin import LeBonCoinScraper
from filters.price_and_distance import apply_price_and_distance_filter
from storage.sqlite import init_db, insert_annonce
from reporting.generator import generate_summary_reports
from reporting.exporter import run_export
from storage.cleaner import check_expired_annonces
from utils.logger import setup_logger
from utils.validation import validate_annonce

# Configuration du logger
logger = setup_logger('main')

SCRAPER_MAP = {
    "seloger": SeLogerScraper,
    "leboncoin": LeBonCoinScraper,
}


def parse_args():
    parser = argparse.ArgumentParser(description="Scraper d'annonces immobilieres Toulouse / ENAC")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seloger", action="store_true", help="Scanner uniquement SeLoger")
    group.add_argument("--leboncoin", action="store_true", help="Scanner uniquement LeBonCoin")
    group.add_argument("--all", action="store_true", default=True, help="Scanner tous les sites (defaut)")
    parser.add_argument("--export", choices=["csv", "json"], help="Exporter les annonces en CSV ou JSON")
    parser.add_argument("--purge", action="store_true", help="Vérifier et marquer les annonces expirées")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.seloger:
        scrapers_to_run = [SCRAPER_MAP["seloger"]]
    elif args.leboncoin:
        scrapers_to_run = [SCRAPER_MAP["leboncoin"]]
    else:
        scrapers_to_run = SCRAPERS

    sites_label = ", ".join(s().site_name() for s in scrapers_to_run)
    logger.info(f"Demarrage du scraper Toulouse / ENAC — sites: {sites_label}")

    run_start_time = datetime.now()

    try:
        # Initialisation base
        init_db()
        logger.info("Base de données initialisée")

        total_raw = 0
        total_kept = 0
        total_rejected = 0
        total_inserted = 0
        total_validation_errors = 0

        # Boucle sur les scrapers sélectionnés
        for ScraperClass in scrapers_to_run:
            scraper = ScraperClass()
            site_name = scraper.site_name()

            logger.info(f"--- Scraping {site_name} ---")
            raw_annonces = scraper.scrape()
            logger.info(f"🔍 {len(raw_annonces)} annonces brutes récupérées de {site_name}")

            kept = 0
            rejected = 0
            inserted = 0
            validation_errors = 0

            for annonce in raw_annonces:
                # Validation des données brutes
                validation_error = validate_annonce(annonce)
                if validation_error:
                    logger.warning(f"Annonce invalide ({site_name}) : {validation_error}")
                    validation_errors += 1
                    rejected += 1
                    continue

                # Filtrage par prix et distance
                filtered = apply_price_and_distance_filter(annonce)

                if not filtered:
                    rejected += 1
                    continue

                kept += 1

                # Insertion en base
                if insert_annonce(filtered):
                    inserted += 1
                    logger.info(
                        f"✨ Nouvelle annonce ({site_name}) : {filtered['title']} - "
                        f"{filtered['price']}€ - {filtered['distance_enac_km']}km"
                    )

            # Résumé par site
            logger.info(f"📊 Résumé {site_name} :")
            logger.info(f"  - Annonces brutes : {len(raw_annonces)}")
            logger.info(f"  - Erreurs de validation : {validation_errors}")
            logger.info(f"  - Annonces filtrées conservées : {kept}")
            logger.info(f"  - Annonces rejetées : {rejected}")
            logger.info(f"  - Nouvelles annonces insérées : {inserted}")

            total_raw += len(raw_annonces)
            total_kept += kept
            total_rejected += rejected
            total_inserted += inserted
            total_validation_errors += validation_errors

        # Résumé global
        logger.info("=" * 50)
        logger.info("✅ Résumé global")
        logger.info(f"  - Sites scrapes : {len(scrapers_to_run)}")
        logger.info(f"  - Annonces brutes totales : {total_raw}")
        logger.info(f"  - Erreurs de validation : {total_validation_errors}")
        logger.info(f"  - Annonces conservées : {total_kept}")
        logger.info(f"  - Annonces rejetées : {total_rejected}")
        logger.info(f"  - Nouvelles annonces insérées : {total_inserted}")
        logger.info("🎯 Terminé.")

        # Génération des rapports Markdown
        generate_summary_reports(run_start_time)
        logger.info("📄 Rapports générés dans le dossier reports/")

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
