# main.py
# =========================
# Point d'entrée CLI
#
#   python main.py scrape [--site leboncoin] [--profile blagnac] [--enrich] [--export csv]
#   python main.py enrich [--site seloger] [--limit 20]
#   python main.py check-links [--limit 50]
#   python main.py purge
#   python main.py export csv|json
#   python main.py ui [--port 5000]
#
# Les anciennes options (--seloger, --ui, --check-links…) restent acceptées.
# Imports paresseux : `ui`, `export`, `purge` fonctionnent sans Playwright.
# =========================

import argparse
import sys
from typing import List, Optional

from config import SEARCH_PROFILES, ENRICHMENT_DEFAULT_LIMIT, enabled_profiles
from scrapers import SCRAPER_PATHS, SITE_NAMES
from utils.logger import setup_logger

logger = setup_logger("main")

COMMANDS = ("scrape", "enrich", "check-links", "purge", "export", "ui")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scraper d'annonces immobilières Toulouse (profils ENAC, Blagnac…)"
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMANDE")

    site_opt = dict(action="append", choices=sorted(SCRAPER_PATHS), dest="sites",
                    help="Site à traiter (répétable). Défaut : tous")

    scrape = sub.add_parser("scrape", help="Scraper les sites (commande par défaut)")
    scrape.add_argument("--site", **site_opt)
    scrape.add_argument("--profile", action="append", choices=sorted(SEARCH_PROFILES),
                        help="Profil de recherche (répétable). Défaut : tous les profils actifs")
    scrape.add_argument("--enrich", action="store_true", help="Enrichir les annonces après le scraping")
    scrape.add_argument("--limit", type=int, help="Nombre max d'annonces à enrichir (avec --enrich)")
    scrape.add_argument("--export", choices=["csv", "json"], help="Exporter après le scraping")
    scrape.add_argument("--purge", action="store_true",
                        help="Vérifier les annonces expirées après le scraping (requêtes HEAD)")

    enrich = sub.add_parser("enrich", help="Enrichir les annonces en attente (surface, DPE…)")
    enrich.add_argument("--site", **site_opt)
    enrich.add_argument("--limit", type=int, help=f"Nombre max d'annonces (défaut {ENRICHMENT_DEFAULT_LIMIT})")

    check = sub.add_parser("check-links", help="Vérifier les liens via navigateur headless")
    check.add_argument("--limit", type=int, help="Nombre max d'annonces à vérifier")

    sub.add_parser("purge", help="Marquer les annonces expirées (requêtes HEAD, peu fiable sur les SPA)")

    export = sub.add_parser("export", help="Exporter les annonces actives")
    export.add_argument("format", choices=["csv", "json"])

    ui = sub.add_parser("ui", help="Lancer l'interface web")
    ui.add_argument("--port", type=int, default=5000)
    ui.add_argument("--no-browser", action="store_true", help="Ne pas ouvrir le navigateur")

    return parser


def translate_legacy_args(argv: List[str]) -> List[str]:
    """
    Convertit l'ancienne syntaxe (options seules) en sous-commande.
    Sans argument : `scrape` (comportement historique).
    """
    if not argv:
        return ["scrape"]
    if argv[0] in COMMANDS or argv[0] in ("-h", "--help"):
        return argv

    def take_value(flag: str) -> List[str]:
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv):
                return [flag, argv[i + 1]]
        return []

    def take_all(flag: str) -> List[str]:
        out = []
        for i, a in enumerate(argv):
            if a == flag and i + 1 < len(argv):
                out += [flag, argv[i + 1]]
        return out

    has = lambda flag: flag in argv  # noqa: E731
    explicit_sites = has("--seloger") or has("--leboncoin") or has("--all")

    if has("--ui"):
        new = ["ui"] + take_value("--port")
    elif has("--check-links"):
        new = ["check-links"] + take_value("--limit")
    elif has("--enrich") and not explicit_sites:
        new = ["enrich"] + take_value("--limit")
    else:
        new = ["scrape"]
        if has("--seloger"):
            new += ["--site", "seloger"]
        if has("--leboncoin"):
            new += ["--site", "leboncoin"]
        new += take_all("--profile") + take_value("--export") + take_value("--limit")
        if has("--enrich"):
            new.append("--enrich")
        if has("--purge"):
            new.append("--purge")

    print(f"⚠ Syntaxe obsolète : utiliser « python main.py {' '.join(new)} »", file=sys.stderr)
    return new


def selected_profiles(keys: Optional[List[str]]):
    """Profils demandés via --profile, ou tous les profils actifs."""
    if keys:
        return [SEARCH_PROFILES[k] for k in dict.fromkeys(keys)]
    return enabled_profiles()


def _site_filter(site_keys: Optional[List[str]]) -> Optional[str]:
    # L'enrichissement filtre sur un seul site (nom stocké en base) ou aucun
    if site_keys and len(set(site_keys)) == 1:
        return SITE_NAMES[site_keys[0]]
    return None


def cmd_enrich(site_keys, limit) -> dict:
    from scrapers.enricher import enrich_annonces

    summary = enrich_annonces(
        site_filter=_site_filter(site_keys),
        limit=limit if limit is not None else ENRICHMENT_DEFAULT_LIMIT,
    )
    logger.info(
        f"Enrichissement terminé : {summary['enriched']}/{summary['total']} enrichis, "
        f"{summary['errors']} erreurs"
    )
    return summary


def cmd_check_links(limit):
    from storage.cleaner import check_links_playwright

    summary = check_links_playwright(limit=limit)
    logger.info(
        f"Vérification terminée : {summary['checked']} vérifiées, "
        f"{summary['expired']} expirées, "
        f"{summary['network_errors']} erreurs réseau (non vérifiées), "
        f"{summary['page_errors']} erreurs de page"
    )


def cmd_purge():
    from storage.cleaner import check_expired_annonces
    from storage.sqlite import init_db

    init_db()
    summary = check_expired_annonces()
    logger.info(f"Purge : {summary['expired']} expirées / {summary['checked']} vérifiées")


def cmd_export(fmt: str):
    from reporting.exporter import run_export
    from storage.sqlite import init_db

    init_db()
    path = run_export(fmt)
    logger.info(f"📦 Export {fmt.upper()} généré : {path}")


def cmd_scrape(args):
    from pipeline import run_scraping

    site_keys = list(dict.fromkeys(args.sites)) if args.sites else list(SCRAPER_PATHS)
    profiles = selected_profiles(args.profile)
    logger.info(
        "Démarrage du scraper — profils: "
        + ", ".join(p.label for p in profiles)
        + " — sites: " + ", ".join(SITE_NAMES[k] for k in site_keys)
    )

    try:
        run_scraping(profiles, site_keys)
        if args.enrich:
            cmd_enrich(args.sites, args.limit)
        if args.purge:
            cmd_purge()
        if args.export:
            cmd_export(args.export)
    except Exception as e:
        logger.error(f"❌ Erreur critique dans le pipeline : {e}", exc_info=True)
        raise


def main(argv: Optional[List[str]] = None):
    argv = translate_legacy_args(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(argv)

    if args.command == "ui":
        from ui import run_ui
        run_ui(port=args.port, open_browser=not args.no_browser)
    elif args.command == "enrich":
        cmd_enrich(args.sites, args.limit)
    elif args.command == "check-links":
        cmd_check_links(args.limit)
    elif args.command == "purge":
        cmd_purge()
    elif args.command == "export":
        cmd_export(args.format)
    else:
        cmd_scrape(args)


if __name__ == "__main__":
    main()
