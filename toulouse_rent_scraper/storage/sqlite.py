# storage/sqlite.py
# =========================
# Stockage SQLite + déduplication
# =========================

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict

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

    # Migration : ajout de created_at si la colonne n'existe pas
    cur.execute("PRAGMA table_info(annonces)")
    columns = [row[1] for row in cur.fetchall()]
    if "created_at" not in columns:
        cur.execute("ALTER TABLE annonces ADD COLUMN created_at TIMESTAMP")
        cur.execute("UPDATE annonces SET created_at = scraped_at WHERE created_at IS NULL")

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
