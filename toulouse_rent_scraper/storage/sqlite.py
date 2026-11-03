# storage/sqlite.py
# =========================
# Stockage SQLite + déduplication
# =========================

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from config import (
    DB_PATH, DUPLICATE_PRICE_TOLERANCE, ENRICHMENT_MAX_ATTEMPTS, ENRICHMENT_RETRY_DELAY_HOURS,
)

# Statuts possibles d'une annonce :
#   active  — en ligne
#   expired — détectée comme retirée (--check-links / --purge), réactivée si revue
#   hidden  — masquée manuellement depuis l'UI, ne revient jamais
ANNONCE_STATUSES = {"active", "expired", "hidden"}


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


@contextmanager
def connect(row_factory=sqlite3.Row):
    """Connexion courte : commit en sortie (rollback si erreur), toujours fermée."""
    conn = get_connection()
    conn.row_factory = row_factory
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Crée/met à jour le schéma (migrations versionnées) et active le mode WAL."""
    from storage.migrations import migrate

    conn = get_connection()
    try:
        # WAL : l'UI peut lire pendant qu'un scraping écrit (réglage persistant dans le fichier)
        conn.execute("PRAGMA journal_mode=WAL")
        migrate(conn)
    finally:
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

    cur.execute("SELECT id, price, COALESCE(status, 'active') FROM annonces WHERE url = ?", (url,))
    row = cur.fetchone()

    if row is not None:
        annonce_id, existing_price, existing_status = row
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
        if price_changed:
            _record_price(cur, annonce_id, new_price, now)
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
    if annonce.get("price") is not None:
        _record_price(cur, cur.lastrowid, annonce["price"], now)

    conn.commit()
    conn.close()
    return "new"


def _record_price(cur: sqlite3.Cursor, annonce_id: int, price: int, seen_at: str):
    cur.execute(
        "INSERT INTO price_history (annonce_id, price, seen_at) VALUES (?, ?, ?)",
        (annonce_id, price, seen_at),
    )


def get_price_history(annonce_id: int) -> List[Dict]:
    """Prix successifs d'une annonce, du plus ancien au plus récent."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT price, seen_at FROM price_history WHERE annonce_id = ? ORDER BY seen_at, id",
            (annonce_id,),
        ).fetchall()
    return [dict(r) for r in rows]


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


def annonces_for_scoring(profile: str) -> List[Dict]:
    """Annonces d'un profil avec les champs utiles au score."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.price, a.charges, a.surface_m2, a.furnished, a.dpe_rating,
                   COALESCE(a.status, 'active') AS status, ap.distance_km
            FROM annonces a
            JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
            """,
            (profile,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_price(url: str) -> Optional[int]:
    """Prix actuellement en base pour cette URL (None si inconnue)."""
    with connect() as conn:
        row = conn.execute("SELECT price FROM annonces WHERE url = ?", (url,)).fetchone()
    return row[0] if row else None


def annonces_for_notification(profile: str, urls: List[str]) -> Dict[str, Dict]:
    """Titre, prix, distance et score des annonces d'un profil, indexés par URL (actives seulement)."""
    if not urls:
        return {}
    placeholders = ",".join("?" * len(urls))
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT a.url, a.title, a.price, a.location_raw, ap.distance_km, ap.score
            FROM annonces a
            JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
            WHERE a.url IN ({placeholders}) AND COALESCE(a.status, 'active') = 'active'
            """,
            [profile] + list(urls),
        ).fetchall()
    return {r["url"]: dict(r) for r in rows}


def save_scores(profile: str, updates) -> None:
    """updates : itérable de (annonce_id, score, detail_json)."""
    with connect() as conn:
        conn.executemany(
            "UPDATE annonce_profiles SET score = ?, score_detail = ? WHERE annonce_id = ? AND profile = ?",
            [(score, detail, annonce_id, profile) for annonce_id, score, detail in updates],
        )


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
    Annonces actives à enrichir : jamais tentées (`pending`), ou en `error` avec
    moins de ENRICHMENT_MAX_ATTEMPTS tentatives et un dernier essai assez ancien.
    Les `pending` passent en premier.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # enriched_at est stocké en ISO (« 2026-11-02T10:00:00 ») : seuil calculé au même format
    retry_before = (datetime.now() - timedelta(hours=ENRICHMENT_RETRY_DELAY_HOURS)).isoformat()
    query = """
        SELECT * FROM annonces
        WHERE COALESCE(status, 'active') = 'active'
          AND (
                enrichment_status = 'pending'
             OR (enrichment_status = 'error'
                 AND COALESCE(enrichment_attempts, 0) < ?
                 AND (enriched_at IS NULL OR enriched_at < ?))
          )
    """
    params = [ENRICHMENT_MAX_ATTEMPTS, retry_before]

    if site_filter:
        query += " AND site = ?"
        params.append(site_filter)

    query += " ORDER BY (enrichment_status = 'pending') DESC, created_at DESC LIMIT ?"
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
    cur.execute("DELETE FROM price_history")
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
        "enriched_at", "enrichment_status", "enrichment_attempts", "error_detail",
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
