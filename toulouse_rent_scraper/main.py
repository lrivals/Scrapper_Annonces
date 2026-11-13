# main.py
# =========================
# Point d'entrée CLI
#
#   python main.py scrape [--site leboncoin] [--profile blagnac] [--enrich] [--export csv]
#   python main.py enrich [--site seloger] [--limit 20]
#   python main.py check-links [--limit 50]
#   python main.py purge
#   python main.py export csv|json
#   python main.py rescore
#   python main.py notify-test
#   python main.py ui [--port 5000]
#
# Les anciennes options (--seloger, --ui, --check-links…) restent acceptées.
# Imports paresseux : `ui`, `export`, `purge` fonctionnent sans Playwright.
# =========================

import argparse
import sys
from contextlib import contextmanager
from typing import List, Optional

from config import SEARCH_PROFILES, ENRICHMENT_DEFAULT_LIMIT, enabled_profiles
from scrapers import SCRAPER_PATHS, SITE_NAMES
from utils.logger import setup_logger

logger = setup_logger("main")

COMMANDS = ("scrape", "enrich", "check-links", "purge", "export", "rescore", "notify-test", "quality", "analyze", "ui")

# Code de sortie quand un autre run tient le verrou (EX_TEMPFAIL)
EXIT_ALREADY_RUNNING = 75


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
    scrape.add_argument("--unattended", action="store_true",
                        help="Run planifié : captcha notifié et attendu 10 min, sites bloqués récemment sautés")

    enrich = sub.add_parser("enrich", help="Enrichir les annonces en attente (surface, DPE…)")
    enrich.add_argument("--site", **site_opt)
    enrich.add_argument("--limit", type=int, help=f"Nombre max d'annonces (défaut {ENRICHMENT_DEFAULT_LIMIT})")
    enrich.add_argument("--unattended", action="store_true", help="Run planifié (captcha notifié)")

    check = sub.add_parser("check-links", help="Vérifier les liens via navigateur headless")
    check.add_argument("--limit", type=int, help="Nombre max d'annonces à vérifier")

    sub.add_parser("purge", help="Marquer les annonces expirées (requêtes HEAD, peu fiable sur les SPA)")

    sub.add_parser("rescore", help="Recalculer les scores d'intérêt (après un changement de poids)")
    sub.add_parser("notify-test", help="Envoyer une notification de test (vérifier .env)")

    analyze = sub.add_parser("analyze", help="Analyser les nouvelles descriptions par LLM (une seule lecture par texte)")
    analyze.add_argument("--limit", type=int, help="Appels au modèle au plus (défaut LLM_MAX_PER_RUN)")
    analyze.add_argument("--retry-errors", action="store_true",
                         help="Relancer UNE fois les textes en erreur (appel facturé)")
    analyze.add_argument("--stats", action="store_true", help="Afficher le registre des lectures, sans appel")

    quality = sub.add_parser("quality", help="Taux de remplissage des champs par site (santé de l'extraction)")
    quality.add_argument("--days", type=int, help="Seulement les annonces enrichies ces N derniers jours")

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


def cmd_enrich(site_keys, limit, unattended: bool = False) -> dict:
    from scrapers.enricher import enrich_annonces

    summary = enrich_annonces(
        site_filter=_site_filter(site_keys),
        limit=limit if limit is not None else ENRICHMENT_DEFAULT_LIMIT,
        unattended=unattended,
    )
    logger.info(
        f"Enrichissement terminé : {summary['enriched']}/{summary['total']} enrichis, "
        f"{summary['errors']} erreurs, {summary.get('expired', 0)} annonces retirées"
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


def cmd_rescore():
    from scoring import rescore
    from storage.sqlite import init_db

    init_db()
    logger.info(f"Scores recalculés : {rescore()} annonce(s)")


def cmd_notify_test() -> bool:
    import config
    import notify

    if not notify.is_enabled():
        logger.error("Notifications désactivées : définir NOTIFY_BACKEND (et ses secrets) dans .env — voir .env.example")
        return False
    ok = notify.send(
        "Test — Scrapper Annonces",
        "Les notifications fonctionnent. Profils : "
        + ", ".join(p.label for p in enabled_profiles()),
        tags=["white_check_mark"],
    )
    if ok:
        logger.info(f"Notification de test envoyée via {config.NOTIFY_BACKEND}")
    return ok


def cmd_analyze(limit: Optional[int] = None, retry_errors: bool = False, stats: bool = False) -> dict:
    """Analyse LLM à la demande (indépendante de l'option « automatique »)."""
    from analysis.llm import analyze_pending
    from analysis.providers import load_settings
    from scoring import rescore
    from storage.sqlite import init_db, llm_stats

    init_db()
    if stats:
        st = llm_stats()
        settings = load_settings()
        print(f"Fournisseur : {settings.label() if settings.provider else 'non configuré'}"
              f"{' (' + settings.source + ')' if settings.source else ''}")
        print(f"Textes lus : {st['texts']} (réussis {st['done']}, erreurs {st['errors']}, refus {st['refused']})")
        print(f"Appels facturables : {st['calls']} — dont relances : {st['retried']}")
        print(f"Annonces couvertes : {st['annonces']} (une analyse peut servir à plusieurs annonces)")
        print(f"Jetons : {st['input_tokens']} en entrée, {st['output_tokens']} en sortie")
        return st
    summary = analyze_pending(limit=limit, retry_errors=retry_errors)
    if summary["done"] or summary["reused"]:
        rescore()
    return summary


def cmd_quality(days: Optional[int] = None) -> List[str]:
    from storage.quality import check_fill_rates, enriched_rows, format_report, group_by_site
    from storage.sqlite import init_db

    init_db()
    by_site = group_by_site(enriched_rows(days))
    scope = f"enrichies ces {days} derniers jours" if days else "enrichies"
    print(f"Taux de remplissage — annonces {scope}\n")
    print(format_report(by_site))
    alerts = check_fill_rates(by_site)
    print()
    for alert in alerts:
        print(f"⚠ {alert}")
    if not alerts:
        print("✓ Aucun champ clé sous son seuil")
    return alerts


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
        run_scraping(profiles, site_keys, unattended=args.unattended)
        if args.enrich:
            cmd_enrich(args.sites, args.limit, unattended=args.unattended)
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
        with _exclusive():
            cmd_enrich(args.sites, args.limit, unattended=args.unattended)
    elif args.command == "check-links":
        cmd_check_links(args.limit)
    elif args.command == "purge":
        cmd_purge()
    elif args.command == "export":
        cmd_export(args.format)
    elif args.command == "rescore":
        cmd_rescore()
    elif args.command == "analyze":
        cmd_analyze(args.limit, args.retry_errors, args.stats)
    elif args.command == "quality":
        cmd_quality(args.days)
    elif args.command == "notify-test":
        sys.exit(0 if cmd_notify_test() else 1)
    else:
        with _exclusive():
            cmd_scrape(args)


@contextmanager
def _exclusive():
    """Un seul scraping / enrichissement à la fois (ils partagent le profil Chrome)."""
    from utils.lock import AlreadyRunning, run_lock

    try:
        with run_lock():
            yield
    except AlreadyRunning as e:
        logger.error(f"⏸ {e} — abandon")
        sys.exit(EXIT_ALREADY_RUNNING)


if __name__ == "__main__":
    main()
