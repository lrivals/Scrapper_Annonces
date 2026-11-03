# storage/sqlite.py
# =========================
# Stockage SQLite + déduplication
# =========================

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import DB_PATH, DUPLICATE_PRICE_TOLERANCE

# Statuts possibles d'une annonce :
#   active  — en ligne
#   expired — détectée comme retirée (--check-links / --purge), réactivée si revue
#   hidden  — masquée manuellement depuis l'UI, ne revient jamais
ANNONCE_STATUSES = {"active", "expired", "hidden"}


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

    if "checked_at" not in columns:
        cur.execute("ALTER TABLE annonces ADD COLUMN checked_at TIMESTAMP")

    # Sprint 11 — lien vers l'annonce d'origine (même bien publié sur un autre site)
    if "duplicate_of" not in columns:
        cur.execute("ALTER TABLE annonces ADD COLUMN duplicate_of INTEGER")

    # Sprint 14 — coordonnées (distance recalculable vers n'importe quelle cible)
    for col in ("lat", "lon"):
        if col not in columns:
            cur.execute(f"ALTER TABLE annonces ADD COLUMN {col} REAL")

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

    # Cache géocodage persistant
    cur.execute("""
        CREATE TABLE IF NOT EXISTS geocoding_cache (
            address TEXT PRIMARY KEY,
            latitude REAL,
            longitude REAL,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Sprint 14 — pertinence d'une annonce pour chaque profil de recherche
    cur.execute("""
        CREATE TABLE IF NOT EXISTS annonce_profiles (
            annonce_id  INTEGER NOT NULL REFERENCES annonces(id) ON DELETE CASCADE,
            profile     TEXT    NOT NULL,
            distance_km REAL,
            matched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (annonce_id, profile)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_annonce_profiles_profile ON annonce_profiles(profile)")

    # Annonces antérieures aux profils : rattachées au profil historique ENAC
    cur.execute("""
        INSERT OR IGNORE INTO annonce_profiles (annonce_id, profile, distance_km, matched_at)
        SELECT a.id, 'enac', a.distance_enac_km, COALESCE(a.created_at, CURRENT_TIMESTAMP)
        FROM annonces a
        WHERE NOT EXISTS (SELECT 1 FROM annonce_profiles ap WHERE ap.annonce_id = a.id)
    """)

    # Coordonnées manquantes : reprises du cache de géocodage
    cur.execute("""
        UPDATE annonces SET
            lat = (SELECT g.latitude FROM geocoding_cache g WHERE g.address = annonces.location_raw),
            lon = (SELECT g.longitude FROM geocoding_cache g WHERE g.address = annonces.location_raw)
        WHERE lat IS NULL AND location_raw IS NOT NULL
    """)

    conn.commit()
    conn.close()


def annonce_exists(url: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM annonces WHERE url = ?", (url,))
    exists = cur.fetchone() is not None

    conn.close()
    return exists


def insert_annonce(annonce: Dict) -> str:
    """
    Insère une annonce ou met à jour une annonce existante (même URL).
    Retourne :
      "new"         — nouvelle annonce insérée
      "reactivated" — annonce marquée expirée qui réapparaît (repassée en active)
      "updated"     — annonce existante dont le prix a changé
      "unchanged"   — annonce existante, prix identique (ou masquée)
    Une annonce masquée (status 'hidden') reste masquée.
    """
    url = annonce["url"]
    now = datetime.now().isoformat()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT price, COALESCE(status, 'active') FROM annonces WHERE url = ?", (url,))
    row = cur.fetchone()

    if row is not None:
        existing_price, existing_status = row
        new_price = annonce.get("price")
        price_changed = new_price is not None and new_price != existing_price

        # Dans un UPDATE SQLite, les CASE lisent les valeurs d'avant la mise à jour.
        # Photos : COALESCE(photos, ?) pour ne pas écraser les photos complètes de l'enrichissement.
        cur.execute(
            """
            UPDATE annonces SET
                scraped_at = ?,
                checked_at = CASE WHEN status = 'expired' THEN NULL ELSE checked_at END,
                status = CASE WHEN status = 'expired' THEN 'active' ELSE status END,
                price = COALESCE(?, price),
                location_raw = COALESCE(?, location_raw),
                distance_enac_km = COALESCE(?, distance_enac_km),
                lat = COALESCE(?, lat),
                lon = COALESCE(?, lon),
                photos = COALESCE(photos, ?)
            WHERE url = ?
            """,
            (
                now,
                new_price,
                annonce.get("location_raw"),
                annonce.get("distance_enac_km"),
                annonce.get("lat"),
                annonce.get("lon"),
                annonce.get("photos"),
                url,
            ),
        )
        conn.commit()
        conn.close()

        if existing_status == "expired":
            return "reactivated"
        if price_changed:
            return "updated"
        return "unchanged"

    cur.execute("""
        INSERT INTO annonces (
            site,
            title,
            price,
            location_raw,
            distance_enac_km,
            url,
            created_at,
            photos,
            lat,
            lon
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        annonce.get("site"),
        annonce.get("title"),
        annonce.get("price"),
        annonce.get("location_raw"),
        annonce.get("distance_enac_km"),
        url,
        now,
        annonce.get("photos"),
        annonce.get("lat"),
        annonce.get("lon"),
    ))

    conn.commit()
    conn.close()
    return "new"


def upsert_annonce_profile(url: str, profile: str, distance_km: Optional[float]) -> bool:
    """
    Rattache l'annonce `url` au profil `profile` (ou met à jour sa distance).
    Retourne True si l'annonce est nouvelle POUR CE PROFIL.
    """
    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM annonces WHERE url = ?", (url,)).fetchone()
    if row is None:
        conn.close()
        return False
    cur.execute(
        "INSERT OR IGNORE INTO annonce_profiles (annonce_id, profile, distance_km, matched_at) "
        "VALUES (?, ?, ?, ?)",
        (row[0], profile, distance_km, datetime.now().isoformat()),
    )
    is_new = cur.rowcount > 0
    if not is_new and distance_km is not None:
        cur.execute(
            "UPDATE annonce_profiles SET distance_km = ? WHERE annonce_id = ? AND profile = ?",
            (distance_km, row[0], profile),
        )
    conn.commit()
    conn.close()
    return is_new


def _location_words(location: Optional[str]) -> set:
    return {w.lower().strip(",.()") for w in (location or "").split() if len(w) > 3}


def find_potential_duplicates(annonce: Dict) -> List[Dict]:
    """
    Recherche le même bien publié sur un AUTRE site :
      - site différent, URL différente
      - prix à ±DUPLICATE_PRICE_TOLERANCE €
      - surface à ±2 m² si connue des deux côtés
      - au moins 2 mots (> 3 caractères) communs dans location_raw
    Seules les annonces « racines » (duplicate_of IS NULL) sont candidates,
    triées de la plus ancienne à la plus récente.
    """
    url = annonce.get("url", "")
    price = annonce.get("price")
    site = annonce.get("site", "")

    if price is None:
        return []

    words_ref = _location_words(annonce.get("location_raw"))
    if len(words_ref) < 2:
        return []

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, url, title, price, location_raw, site, surface_m2
        FROM annonces
        WHERE site != ?
          AND price BETWEEN ? AND ?
          AND url != ?
          AND duplicate_of IS NULL
        ORDER BY id ASC
        """,
        (site, price - DUPLICATE_PRICE_TOLERANCE, price + DUPLICATE_PRICE_TOLERANCE, url),
    )
    candidates = [dict(row) for row in cur.fetchall()]
    conn.close()

    surface = annonce.get("surface_m2")
    matches = []
    for candidate in candidates:
        cand_surface = candidate.get("surface_m2")
        if surface is not None and cand_surface is not None and abs(surface - cand_surface) > 2:
            continue
        if len(words_ref & _location_words(candidate.get("location_raw"))) >= 2:
            matches.append(candidate)

    return matches


def set_duplicate_of(url: str, original_id: int) -> bool:
    """
    Rattache l'annonce `url` à l'annonce d'origine `original_id`.
    Ne fait rien si l'annonce est déjà rattachée ou si l'origine est plus récente.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE annonces SET duplicate_of = ?
        WHERE url = ? AND duplicate_of IS NULL AND id > ?
        """,
        (original_id, url, original_id),
    )
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def set_annonce_status(annonce_id: int, status: str) -> Optional[str]:
    """
    Change le statut d'une annonce. Retourne son titre, ou None si introuvable.
    """
    if status not in ANNONCE_STATUSES:
        raise ValueError(f"Statut inconnu : {status}")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT title FROM annonces WHERE id = ?", (annonce_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return None
    cur.execute("UPDATE annonces SET status = ? WHERE id = ?", (status, annonce_id))
    conn.commit()
    conn.close()
    return row[0] or f"#{annonce_id}"


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


def clear_db() -> int:
    """
    Supprime toutes les annonces de la base de données.
    Retourne le nombre d'annonces supprimées.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM annonces")
    count = cur.fetchone()[0]
    cur.execute("DELETE FROM annonces")
    cur.execute("DELETE FROM annonce_profiles")
    conn.commit()
    conn.close()
    return count


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
