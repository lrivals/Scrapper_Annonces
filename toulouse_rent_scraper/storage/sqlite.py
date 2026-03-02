# storage/sqlite.py
# =========================
# Stockage SQLite + déduplication
# =========================

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import DB_PATH, DEDUP_KEYS


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS annonces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site TEXT,
            title TEXT,
            price INTEGER,
            location_raw TEXT,
            distance_enac_km REAL,
            url TEXT UNIQUE,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migrations
    cur.execute("PRAGMA table_info(annonces)")
    columns = [row[1] for row in cur.fetchall()]

    if "created_at" not in columns:
        cur.execute("ALTER TABLE annonces ADD COLUMN created_at TIMESTAMP")
        cur.execute("UPDATE annonces SET created_at = scraped_at WHERE created_at IS NULL")

    if "status" not in columns:
        cur.execute("ALTER TABLE annonces ADD COLUMN status TEXT DEFAULT 'active'")
        cur.execute("UPDATE annonces SET status = 'active' WHERE status IS NULL")

    # Sprint 3 — colonnes enrichissement
    enrichment_columns = {
        "surface_m2": "REAL",
        "nb_rooms": "INTEGER",
        "nb_bedrooms": "INTEGER",
        "floor": "INTEGER",
        "description": "TEXT",
        "charges": "INTEGER",
        "deposit": "INTEGER",
        "furnished": "BOOLEAN",
        "dpe_rating": "TEXT",
        "photos": "TEXT",
        "publisher_type": "TEXT",
        "published_at": "TEXT",
        "enriched_at": "TIMESTAMP",
        "enrichment_status": "TEXT DEFAULT 'pending'",
    }

    for col_name, col_type in enrichment_columns.items():
        if col_name not in columns:
            cur.execute(f"ALTER TABLE annonces ADD COLUMN {col_name} {col_type}")

    # Mettre enrichment_status à 'pending' pour les annonces existantes sans statut
    cur.execute("UPDATE annonces SET enrichment_status = 'pending' WHERE enrichment_status IS NULL")

    conn.commit()
    conn.close()


def annonce_exists(url: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM annonces WHERE url = ?", (url,))
    exists = cur.fetchone() is not None

    conn.close()
    return exists


def insert_annonce(annonce: Dict) -> bool:
    """
    Insère une annonce si elle n'existe pas déjà.
    Retourne True si insérée, False sinon.
    """
    if annonce_exists(annonce["url"]):
        return False

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO annonces (
            site,
            title,
            price,
            location_raw,
            distance_enac_km,
            url,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        annonce.get("site"),
        annonce.get("title"),
        annonce.get("price"),
        annonce.get("location_raw"),
        annonce.get("distance_enac_km"),
        annonce.get("url"),
        datetime.now().isoformat(),
    ))

    conn.commit()
    conn.close()
    return True


def get_pending_annonces(site_filter: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """
    Récupère les annonces en attente d'enrichissement.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = "SELECT * FROM annonces WHERE enrichment_status = 'pending' AND COALESCE(status, 'active') = 'active'"
    params = []

    if site_filter:
        query += " AND site = ?"
        params.append(site_filter)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = cur.execute(query, params).fetchall()
    result = [dict(row) for row in rows]

    conn.close()
    return result


def update_annonce_enrichment(url: str, data: Dict) -> bool:
    """
    Met à jour une annonce avec les données d'enrichissement.
    Les champs 'photos' (liste) sont sérialisés en JSON.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Sérialiser les photos en JSON si c'est une liste
    if "photos" in data and isinstance(data["photos"], list):
        data["photos"] = json.dumps(data["photos"])

    # Construire le SET dynamiquement
    allowed_fields = {
        "surface_m2", "nb_rooms", "nb_bedrooms", "floor",
        "description", "charges", "deposit", "furnished",
        "dpe_rating", "photos", "publisher_type", "published_at",
        "enriched_at", "enrichment_status",
    }

    fields_to_update = {k: v for k, v in data.items() if k in allowed_fields}

    if not fields_to_update:
        conn.close()
        return False

    set_clause = ", ".join(f"{k} = ?" for k in fields_to_update)
    values = list(fields_to_update.values()) + [url]

    cur.execute(f"UPDATE annonces SET {set_clause} WHERE url = ?", values)

    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated
