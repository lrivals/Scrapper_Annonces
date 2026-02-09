# reporting/exporter.py
# =========================
# Export CSV et JSON des annonces
# =========================

import csv
import json
import sqlite3
from pathlib import Path

from storage.sqlite import DB_PATH
from utils.logger import setup_logger

REPORTS_DIR = DB_PATH.parent.parent / "reports"
EXPORT_FIELDS = ["price", "distance_enac_km", "title", "url", "created_at", "site"]

logger = setup_logger("exporter")


def _fetch_all_annonces() -> list[dict]:
    """Récupère toutes les annonces depuis la DB."""
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM annonces WHERE COALESCE(status, 'active') = 'active' ORDER BY price ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def export_csv(annonces: list[dict], output_path: Path) -> Path:
    """Exporte les annonces en CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(annonces)
    logger.info(f"Export CSV : {output_path} ({len(annonces)} annonces)")
    return output_path


def export_json(annonces: list[dict], output_path: Path) -> Path:
    """Exporte les annonces en JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Ne garder que les champs utiles
    filtered = [{k: a.get(k) for k in EXPORT_FIELDS} for a in annonces]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    logger.info(f"Export JSON : {output_path} ({len(annonces)} annonces)")
    return output_path


def run_export(fmt: str) -> Path:
    """Point d'entrée : exporte depuis la DB dans le format demandé."""
    annonces = _fetch_all_annonces()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        return export_csv(annonces, REPORTS_DIR / "annonces.csv")
    elif fmt == "json":
        return export_json(annonces, REPORTS_DIR / "annonces.json")
    else:
        raise ValueError(f"Format d'export inconnu : {fmt}")
