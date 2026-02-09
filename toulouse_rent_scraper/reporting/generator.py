# toulouse_rent_scraper/reporting/generator.py

import sqlite3
from datetime import datetime
from pathlib import Path

from utils.logger import setup_logger
from storage.sqlite import DB_PATH

REPORTS_DIR = DB_PATH.parent.parent / "reports"
logger = setup_logger("reporting")


def _generate_new_ads_report(annonces: list):
    """Génère un rapport Markdown pour les nouvelles annonces."""
    report_path = REPORTS_DIR / "nouvelles_annonces.md"
    
    content = [f"# 🚀 Nouvelles Annonces ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"]
    if not annonces:
        content.append("Aucune nouvelle annonce trouvée lors de cette exécution.\n")
    else:
        content.append(f"**{len(annonces)}** nouvelle(s) annonce(s) ajoutée(s) :\n\n")
        for ad in sorted(annonces, key=lambda x: x['price']):
            content.append(f"## {ad['title']}\n")
            content.append(f"- **Prix :** {ad['price']} €\n")
            if ad['distance_enac_km'] is not None:
                content.append(f"- **Distance ENAC :** {ad['distance_enac_km']:.2f} km\n")
            content.append(f"- **Lieu :** {ad['location_raw']}\n")
            content.append(f"- **Lien :** [Voir l'annonce]({ad['url']})\n")
            content.append(f"- **Source :** {ad['site']}\n\n---\n\n")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("".join(content))
    logger.info(f"Rapport des nouvelles annonces créé : {report_path}")


def _generate_all_ads_report(annonces: list):
    """Génère un rapport Markdown pour toutes les annonces en base."""
    report_path = REPORTS_DIR / "toutes_les_annonces.md"

    content = ["# 📚 Toutes les Annonces en Base de Données\n\n"]
    if not annonces:
        content.append("Aucune annonce dans la base de données.\n")
    else:
        content.append(f"Total de **{len(annonces)}** annonce(s) en base.\n\n")
        content.append("| Prix | Distance (km) | Titre | Ajouté le | Lien |\n")
        content.append("|------|---------------|-------|-----------|------|\n")
        for ad in annonces:
            title = ad['title'][:40].strip() + '...' if len(ad['title']) > 40 else ad['title'].strip()
            distance = f"{ad['distance_enac_km']:.2f}" if ad['distance_enac_km'] is not None else "N/A"
            created_date = datetime.fromisoformat(ad['created_at']).strftime('%d/%m/%Y %H:%M')
            content.append(f"| {ad['price']} € | {distance} | {title} | {created_date} | [lien]({ad['url']}) |\n")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("".join(content))
    logger.info(f"Rapport de toutes les annonces créé : {report_path}")


def generate_summary_reports(run_start_time: datetime):
    """
    Génère les rapports de synthèse (nouvelles annonces et toutes les annonces).
    """
    REPORTS_DIR.mkdir(exist_ok=True)
    
    try:
        with sqlite3.connect(DB_PATH) as con:
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            new_annonces = cur.execute("SELECT * FROM annonces WHERE created_at >= ?", (run_start_time,)).fetchall()
            all_annonces = cur.execute("SELECT * FROM annonces ORDER BY created_at DESC").fetchall()

        _generate_new_ads_report(new_annonces)
        _generate_all_ads_report(all_annonces)

    except Exception as e:
        logger.error(f"Erreur lors de la génération des rapports : {e}", exc_info=True)
        raise