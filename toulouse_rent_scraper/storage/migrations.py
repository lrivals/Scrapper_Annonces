# storage/migrations.py
# =========================
# Schéma SQLite versionné : chaque migration s'applique une seule fois,
# dans l'ordre, selon PRAGMA user_version.
# =========================

import sqlite3

from utils.logger import setup_logger

logger = setup_logger("storage")


def _m1_base_schema(cur: sqlite3.Cursor):
    """
    Schéma cumulé jusqu'au Sprint 14 (annonces, enrichissement, cache géo, profils).
    Idempotent : les bases antérieures au versionnage (user_version = 0) le rejouent sans perte.
    """
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



def _m2_indexes_and_price_history(cur: sqlite3.Cursor):
    """Sprint 12 — index de lecture UI + historique des prix."""
    cur.execute("CREATE INDEX IF NOT EXISTS idx_annonces_status ON annonces(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_annonces_site ON annonces(site)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_annonces_price ON annonces(price)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_annonces_created_at ON annonces(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_annonces_location ON annonces(location_raw)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            annonce_id INTEGER NOT NULL REFERENCES annonces(id) ON DELETE CASCADE,
            price      INTEGER NOT NULL,
            seen_at    TIMESTAMP NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_price_history_annonce ON price_history(annonce_id, seen_at)")

    # Point de départ : le prix connu de chaque annonce, à sa date de création
    cur.execute("""
        INSERT INTO price_history (annonce_id, price, seen_at)
        SELECT id, price, COALESCE(created_at, CURRENT_TIMESTAMP)
        FROM annonces
        WHERE price IS NOT NULL
          AND id NOT IN (SELECT annonce_id FROM price_history)
    """)


def _m3_scores_and_enrichment_retry(cur: sqlite3.Cursor):
    """Sprint 13 — score par profil, suivi des tentatives d'enrichissement."""
    ap_cols = {r[1] for r in cur.execute("PRAGMA table_info(annonce_profiles)")}
    if "score" not in ap_cols:
        cur.execute("ALTER TABLE annonce_profiles ADD COLUMN score REAL")
    if "score_detail" not in ap_cols:
        cur.execute("ALTER TABLE annonce_profiles ADD COLUMN score_detail TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_annonce_profiles_score ON annonce_profiles(profile, score)")

    a_cols = {r[1] for r in cur.execute("PRAGMA table_info(annonces)")}
    if "enrichment_attempts" not in a_cols:
        cur.execute("ALTER TABLE annonces ADD COLUMN enrichment_attempts INTEGER DEFAULT 0")
    if "error_detail" not in a_cols:
        cur.execute("ALTER TABLE annonces ADD COLUMN error_detail TEXT")
    # Les erreurs passées comptent comme une tentative
    cur.execute("""
        UPDATE annonces SET enrichment_attempts = 1
        WHERE enrichment_status = 'error' AND COALESCE(enrichment_attempts, 0) = 0
    """)


MIGRATIONS = [
    _m1_base_schema,
    _m2_indexes_and_price_history,
    _m3_scores_and_enrichment_retry,
]

SCHEMA_VERSION = len(MIGRATIONS)


def migrate(conn: sqlite3.Connection) -> int:
    """Applique les migrations manquantes. Retourne la version finale du schéma."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Base en version {version}, code en version {SCHEMA_VERSION} : mettre le code à jour"
        )
    for number, migration in enumerate(MIGRATIONS, start=1):
        if number <= version:
            continue
        cur = conn.cursor()
        migration(cur)
        cur.execute(f"PRAGMA user_version = {number}")
        conn.commit()
        logger.info(f"Migration {number} appliquée ({migration.__name__})")
    return SCHEMA_VERSION
