# toulouse_rent_scraper/reporting/generator.py

import sqlite3
from datetime import datetime
from pathlib import Path

from config import enabled_profiles
from utils.logger import setup_logger
import storage.sqlite

REPORTS_DIR = storage.sqlite.DB_PATH.parent.parent / "reports"
logger = setup_logger("reporting")


def _generate_new_ads_report(annonces: list, out_dir: Path, label: str):
    """Génère un rapport Markdown pour les nouvelles annonces."""
    report_path = out_dir / "nouvelles_annonces.md"

    content = [f"# 🚀 Nouvelles Annonces ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"]
    if not annonces:
        content.append("Aucune nouvelle annonce trouvée lors de cette exécution.\n")
    else:
        content.append(f"**{len(annonces)}** nouvelle(s) annonce(s) ajoutée(s) :\n\n")
        for ad in sorted(annonces, key=lambda x: x['price']):
            content.append(f"## {ad['title']}\n")
            content.append(f"- **Prix :** {ad['price']} €\n")
            if ad['distance_km'] is not None:
                content.append(f"- **Distance {label} :** {ad['distance_km']:.2f} km\n")
            content.append(f"- **Lieu :** {ad['location_raw']}\n")
            content.append(f"- **Lien :** [Voir l'annonce]({ad['url']})\n")
            content.append(f"- **Source :** {ad['site']}\n\n---\n\n")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("".join(content))
    logger.info(f"Rapport des nouvelles annonces créé : {report_path}")


def _generate_all_ads_report(annonces: list, out_dir: Path, label: str):
    """Génère un rapport Markdown pour toutes les annonces en base."""
    report_path = out_dir / "toutes_les_annonces.md"

    content = ["# 📚 Toutes les Annonces en Base de Données\n\n"]
    if not annonces:
        content.append("Aucune annonce dans la base de données.\n")
    else:
        content.append(f"Total de **{len(annonces)}** annonce(s) en base.\n\n")
        content.append(f"| Prix | Surface | Pièces | DPE | Distance {label} (km) | Titre | Ajouté le | Lien |\n")
        content.append("|------|---------|--------|-----|---------------|-------|-----------|------|\n")
        for ad in annonces:
            title = ad['title'][:40].strip() + '...' if len(ad['title']) > 40 else ad['title'].strip()
            distance = f"{ad['distance_km']:.2f}" if ad['distance_km'] is not None else "N/A"
            created_date = datetime.fromisoformat(ad['created_at']).strftime('%d/%m/%Y %H:%M')
            surface = f"{int(ad['surface_m2'])} m²" if ad.get('surface_m2') else "-"
            rooms = str(ad['nb_rooms']) if ad.get('nb_rooms') else "-"
            dpe = ad.get('dpe_rating') or "-"
            content.append(
                f"| {ad['price']} € | {surface} | {rooms} | {dpe} | {distance} | {title} | {created_date} | [lien]({ad['url']}) |\n"
            )

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("".join(content))
    logger.info(f"Rapport de toutes les annonces créé : {report_path}")


def _generate_detailed_ads_report(annonces: list, out_dir: Path, label: str):
    """Génère un rapport Markdown pour les annonces enrichies (surface, DPE, description, etc.)."""
    report_path = out_dir / "annonces_detaillees.md"

    enriched = [ad for ad in annonces if ad.get('enrichment_status') == 'done']

    content = [f"# 🔍 Annonces Détaillées ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"]
    if not enriched:
        content.append("Aucune annonce enrichie disponible.\n")
    else:
        content.append(f"**{len(enriched)}** annonce(s) avec données détaillées :\n\n")
        for ad in sorted(enriched, key=lambda x: x['price']):
            title = ad.get('title', 'Sans titre')
            content.append(f"## {title}\n\n")
            content.append(f"- **Prix :** {ad['price']} €\n")
            if ad.get('surface_m2'):
                content.append(f"- **Surface :** {int(ad['surface_m2'])} m²\n")
            if ad.get('nb_rooms'):
                content.append(f"- **Pièces :** {ad['nb_rooms']}\n")
            if ad.get('nb_bedrooms'):
                content.append(f"- **Chambres :** {ad['nb_bedrooms']}\n")
            if ad.get('floor') is not None:
                content.append(f"- **Étage :** {ad['floor']}\n")
            if ad.get('dpe_rating'):
                content.append(f"- **DPE :** {ad['dpe_rating']}\n")
            if ad.get('charges'):
                content.append(f"- **Charges :** {ad['charges']} €\n")
            if ad.get('deposit'):
                content.append(f"- **Dépôt de garantie :** {ad['deposit']} €\n")
            if ad.get('furnished') is not None:
                content.append(f"- **Meublé :** {'Oui' if ad['furnished'] else 'Non'}\n")
            if ad.get('distance_km') is not None:
                content.append(f"- **Distance {label} :** {ad['distance_km']:.2f} km\n")
            content.append(f"- **Lieu :** {ad.get('location_raw', 'N/A')}\n")
            content.append(f"- **Source :** {ad.get('site', 'N/A')}\n")
            if ad.get('publisher_type'):
                content.append(f"- **Contact :** {ad['publisher_type']}\n")
            if ad.get('description'):
                desc = ad['description'][:300]
                if len(ad['description']) > 300:
                    desc += "..."
                content.append(f"- **Description :** {desc}\n")
            content.append(f"- **Lien :** [Voir l'annonce]({ad['url']})\n")
            content.append("\n---\n\n")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("".join(content))
    logger.info(f"Rapport détaillé créé : {report_path}")


_PROFILE_QUERY = """
    SELECT a.*, ap.distance_km AS distance_km
    FROM annonces a
    JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
    WHERE COALESCE(a.status, 'active') = 'active'
      AND ap.excluded_reasons IS NULL   -- critères éliminatoires du profil (15.5)
"""


def generate_summary_reports(run_start_time: datetime):
    """
    Génère les rapports de synthèse, un dossier par profil :
    reports/<profil>/{nouvelles_annonces, toutes_les_annonces, annonces_detaillees}.md
    """
    try:
        with sqlite3.connect(storage.sqlite.DB_PATH) as con:
            con.row_factory = sqlite3.Row
            for profile in enabled_profiles():
                out_dir = REPORTS_DIR / profile.key
                out_dir.mkdir(parents=True, exist_ok=True)

                # « Nouvelle » = rattachée au profil pendant ce run
                new_annonces = [dict(row) for row in con.execute(
                    _PROFILE_QUERY + " AND ap.matched_at >= ?",
                    (profile.key, run_start_time.isoformat()),
                ).fetchall()]
                all_annonces = [dict(row) for row in con.execute(
                    _PROFILE_QUERY + " ORDER BY a.created_at DESC",
                    (profile.key,),
                ).fetchall()]

                _generate_new_ads_report(new_annonces, out_dir, profile.label)
                _generate_all_ads_report(all_annonces, out_dir, profile.label)
                _generate_detailed_ads_report(all_annonces, out_dir, profile.label)

    except Exception as e:
        logger.error(f"Erreur lors de la génération des rapports : {e}", exc_info=True)
        raise
