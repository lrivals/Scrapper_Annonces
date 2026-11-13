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
                geo_precision = COALESCE(geo_precision, CASE WHEN ? IS NOT NULL THEN 'approx' END),
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
                annonce.get("lat"),
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
            lon,
            geo_precision
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        "approx" if annonce.get("lat") is not None else None,
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
            SELECT a.id, a.price, a.charges, a.charges_included, a.surface_m2, a.furnished, a.dpe_rating,
                   a.scam_risk, a.floor, a.available_from, a.apl_ok, a.colocation, a.lease_type,
                   a.enrichment_status,
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
    """
    Titre, prix, distance et score des annonces d'un profil, indexés par URL
    (actives et non exclues par les critères du profil — 15.5 ; jamais les 👎, toujours
    les ⭐ — 15.6).
    """
    if not urls:
        return {}
    placeholders = ",".join("?" * len(urls))
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT a.url, a.title, a.price, a.location_raw, a.surface_m2, a.nb_rooms, a.dpe_rating,
                   a.scam_risk, a.available_from, ap.distance_km, ap.score, f.feedback
            FROM annonces a
            JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
            LEFT JOIN annonce_feedback f ON f.annonce_id = a.id AND f.profile = ap.profile
            WHERE a.url IN ({placeholders}) AND COALESCE(a.status, 'active') = 'active'
              AND (ap.excluded_reasons IS NULL OR f.feedback = 'favorite')
              AND COALESCE(f.feedback, '') != 'dislike'
            """,
            [profile] + list(urls),
        ).fetchall()
    return {r["url"]: dict(r) for r in rows}


def save_scores(profile: str, updates) -> None:
    """
    updates : itérable de (annonce_id, score, detail_json[, excluded_reasons_json]).
    Sans 4ᵉ élément, l'annonce est considérée comme conservée (exclusion levée).
    """
    rows = []
    for update in updates:
        annonce_id, score, detail = update[:3]
        excluded = update[3] if len(update) > 3 else None
        rows.append((score, detail, excluded, annonce_id, profile))
    with connect() as conn:
        conn.executemany(
            "UPDATE annonce_profiles SET score = ?, score_detail = ?, excluded_reasons = ? "
            "WHERE annonce_id = ? AND profile = ?",
            rows,
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
    cur.execute("DELETE FROM annonce_feedback")
    conn.commit()
    conn.close()
    return count


def update_annonce_enrichment(url: str, data: Dict) -> bool:
    """
    Met à jour une annonce avec les données d'enrichissement.
    Les listes et dictionnaires (photos, field_sources, extra_attributes) sont sérialisés en JSON.

    Coordonnées : un point `exact` (fourni par l'annonce) remplace le géocodage de
    l'adresse ; un point `approx` ne sert que si l'annonce n'en avait aucun.
    """
    data = dict(data)
    for key in ("photos", "field_sources", "extra_attributes"):
        if isinstance(data.get(key), (list, dict)):
            data[key] = json.dumps(data[key], ensure_ascii=False)

    allowed_fields = {
        "surface_m2", "nb_rooms", "nb_bedrooms", "floor",
        "description", "charges", "deposit", "furnished",
        "dpe_rating", "photos", "publisher_type", "published_at",
        "enriched_at", "enrichment_status", "enrichment_attempts", "error_detail",
        # Sprint 15.1
        "ges_rating", "elevator", "charges_included", "extraction_source",
        "field_sources", "extra_attributes",
    }
    fields_to_update = {k: v for k, v in data.items() if k in allowed_fields}

    set_parts = [f"{k} = ?" for k in fields_to_update]
    values = list(fields_to_update.values())

    lat, lon, precision = data.get("lat"), data.get("lon"), data.get("geo_precision")
    if lat is not None and lon is not None:
        if precision == "exact":
            set_parts += ["lat = ?", "lon = ?", "geo_precision = 'exact'"]
            values += [lat, lon]
        else:
            set_parts += [
                "geo_precision = CASE WHEN lat IS NULL THEN 'approx' ELSE geo_precision END",
                "lat = COALESCE(lat, ?)",
                "lon = COALESCE(lon, ?)",
            ]
            values += [lat, lon]

    if not set_parts:
        return False

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE annonces SET {', '.join(set_parts)} WHERE url = ?", values + [url])
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_enrichment_status(url: str) -> Optional[str]:
    """Statut d'enrichissement de l'annonce, ou None si elle n'existe pas."""
    with connect() as conn:
        row = conn.execute("SELECT enrichment_status FROM annonces WHERE url = ?", (url,)).fetchone()
    return row["enrichment_status"] if row else None


def get_coordinates(url: str) -> Optional[Dict]:
    """{id, lat, lon, geo_precision} de l'annonce, ou None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, lat, lon, geo_precision FROM annonces WHERE url = ?", (url,)
        ).fetchone()
    return dict(row) if row else None


def set_distances(annonce_id: int, distance_enac_km: Optional[float], by_profile: Dict[str, float]) -> int:
    """
    Met à jour la distance historique ENAC et la distance de chaque profil DÉJÀ rattaché
    (une annonce n'est jamais rattachée à un nouveau profil ici). Retourne le nombre de profils mis à jour.
    """
    conn = get_connection()
    cur = conn.cursor()
    if distance_enac_km is not None:
        cur.execute("UPDATE annonces SET distance_enac_km = ? WHERE id = ?", (distance_enac_km, annonce_id))
    count = 0
    for profile, dist in by_profile.items():
        cur.execute(
            "UPDATE annonce_profiles SET distance_km = ? WHERE annonce_id = ? AND profile = ?",
            (dist, annonce_id, profile),
        )
        count += cur.rowcount
    conn.commit()
    conn.close()
    return count


# ---------------------------------------------------------------------------
# Analyse LLM (Sprint 15.4)
# ---------------------------------------------------------------------------

def annonces_for_llm(include_errors: bool = False) -> List[Dict]:
    """
    Annonces actives avec une description et JAMAIS passées par l'analyse (llm_status NULL),
    des plus récentes aux plus anciennes. `include_errors` : aussi celles en erreur
    (relance explicite, `analyze --retry-errors`). Avec le texte de l'annonce d'origine
    pour les doublons inter-sites (réutilisation de son analyse).
    """
    statuses = "a.llm_status IS NULL" + (" OR a.llm_status = 'error'" if include_errors else "")
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT a.id, a.url, a.site, a.title, a.price, a.surface_m2, a.location_raw,
                   a.publisher_type, a.description, a.duplicate_of, a.llm_status,
                   o.description AS original_description,
                   COALESCE(o.status, 'active') AS original_status
            FROM annonces a
            LEFT JOIN annonces o ON o.id = a.duplicate_of
            WHERE COALESCE(a.status, 'active') = 'active'
              AND a.description IS NOT NULL AND length(a.description) > 20
              AND ({statuses})
            ORDER BY (a.duplicate_of IS NOT NULL), a.created_at DESC, a.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def active_price_rows() -> List[Dict]:
    """Prix et surface des annonces actives (médiane €/m² du signal « prix très bas »)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT price, surface_m2 FROM annonces WHERE COALESCE(status, 'active') = 'active'"
        ).fetchall()
    return [dict(r) for r in rows]


# --- Registre des lectures LLM (un texte = une lecture) ---

def get_llm_entry(content_hash: str) -> Optional[Dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM llm_analyses WHERE content_hash = ?", (content_hash,)).fetchone()
    return dict(row) if row else None


def claim_llm_entry(content_hash: str, model: str, max_calls: int) -> bool:
    """
    Réserve le texte AVANT l'appel (atomique) : True si ce process peut appeler le modèle.
    Nouveau texte → insertion ; texte rouvert par `--retry-errors` → seulement s'il reste un
    appel autorisé. Un autre process (bouton de l'UI + run planifié) ne peut pas le réserver aussi.
    """
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO llm_analyses (content_hash, status, model, calls, first_call_at, last_call_at) "
            "VALUES (?, 'running', ?, 1, ?, ?)",
            (content_hash, model, now, now),
        )
        if cur.rowcount:
            return True
        cur = conn.execute(
            "UPDATE llm_analyses SET status = 'running', model = ?, calls = calls + 1, last_call_at = ? "
            "WHERE content_hash = ? AND status = 'retry' AND calls < ?",
            (model, now, content_hash, max_calls),
        )
        return cur.rowcount > 0


def release_llm_entry(content_hash: str) -> None:
    """Appel non effectué (service indisponible, rien de facturé) : la réservation est annulée."""
    with connect() as conn:
        conn.execute("DELETE FROM llm_analyses WHERE content_hash = ? AND status = 'running' AND calls = 1",
                     (content_hash,))
        conn.execute("UPDATE llm_analyses SET status = 'error', calls = calls - 1 "
                     "WHERE content_hash = ? AND status = 'running'", (content_hash,))


def finish_llm_entry(content_hash: str, status: str, model: Optional[str], data: Optional[Dict],
                     error: Optional[str], input_tokens: int, output_tokens: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE llm_analyses SET status = ?, model = COALESCE(?, model), data = ?, error = ?, "
            "input_tokens = input_tokens + ?, output_tokens = output_tokens + ? WHERE content_hash = ?",
            (status, model, json.dumps(data, ensure_ascii=False) if data is not None else None,
             error, input_tokens, output_tokens, content_hash),
        )


def llm_calls_since(since: str) -> int:
    """Textes envoyés au modèle depuis `since` (ISO) — plafond journalier."""
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM llm_analyses WHERE last_call_at >= ? AND calls > 0", (since,)
        ).fetchone()[0]


def reopen_llm_errors(max_calls: int, stale_before: str) -> int:
    """
    `--retry-errors` : rouvre les textes en erreur (et les réservations orphelines d'un run
    interrompu, plus anciennes que `stale_before`) qui n'ont pas atteint `max_calls`.
    Les annonces concernées repassent à analyser.
    """
    with connect() as conn:
        cur = conn.execute(
            "UPDATE llm_analyses SET status = 'retry' WHERE calls < ? AND "
            "(status = 'error' OR (status = 'running' AND last_call_at < ?))",
            (max_calls, stale_before),
        )
        reopened = cur.rowcount
        conn.execute(
            "UPDATE annonces SET llm_status = NULL WHERE llm_status IN ('error', 'running') "
            "AND llm_input_hash IN (SELECT content_hash FROM llm_analyses WHERE status = 'retry')"
        )
    return reopened


def llm_stats() -> Dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS texts, COALESCE(SUM(calls), 0) AS calls, "
            "COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
            "SUM(status = 'done') AS done, SUM(status = 'error') AS errors, SUM(status = 'refused') AS refused, "
            "SUM(calls > 1) AS retried FROM llm_analyses"
        ).fetchone()
        annonces = conn.execute(
            "SELECT COUNT(*) FROM annonces WHERE llm_input_hash IS NOT NULL"
        ).fetchone()[0]
    stats = {k: (row[k] or 0) for k in row.keys()}
    stats["annonces"] = annonces
    return stats


_LLM_COLUMNS = (
    "llm_status", "llm_input_hash", "llm_model", "llm_analyzed_at", "llm_error", "llm_data",
    "summary", "available_from", "lease_type", "colocation", "apl_ok", "visale_ok",
    "agency_fees", "scam_risk", "scam_flags",
)


def save_llm_analysis(annonce_id: int, result: Dict) -> None:
    """
    Enregistre le résultat d'une analyse. Charges et dépôt de garantie trouvés dans le texte
    complètent les colonnes d'enrichissement seulement si elles sont vides.
    """
    data = {k: result.get(k) for k in _LLM_COLUMNS if k in result}
    for key in ("llm_data", "scam_flags"):
        if isinstance(data.get(key), (list, dict)):
            data[key] = json.dumps(data[key], ensure_ascii=False)
    sets = [f"{k} = ?" for k in data]
    values = list(data.values())
    for key in ("charges", "deposit"):
        if result.get(key) is not None:
            sets.append(f"{key} = COALESCE({key}, ?)")
            values.append(result[key])
    if not sets:
        return
    with connect() as conn:
        conn.execute(f"UPDATE annonces SET {', '.join(sets)} WHERE id = ?", values + [annonce_id])
