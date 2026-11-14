# storage/run_stats.py
# =========================
# Sprint 5.0 — journal des runs : une ligne par (run, profil), écrite à la fin de
# pipeline.run_scraping. Sert au rapport comparatif (5.3) et aux tendances (2-bis).
# =========================

from datetime import datetime
from statistics import median
from typing import Dict, Iterable, List, Optional

from storage.sqlite import connect

# Annonces visibles d'un profil : actives, rattachées, non exclues par ses critères (15.5)
PROFILE_ACTIVE_SQL = """
    SELECT a.*, ap.distance_km AS distance_km, ap.score AS score, ap.matched_at AS matched_at
    FROM annonces a
    JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
    WHERE COALESCE(a.status, 'active') = 'active'
      AND ap.excluded_reasons IS NULL
      AND a.duplicate_of IS NULL
"""


def snapshot(rows: Iterable[Dict]) -> Dict:
    """Nombre d'annonces, loyer CC médian et €/m² médian (CC) d'un ensemble d'annonces."""
    from scoring import price_per_m2, rent_cc

    rows = list(rows)
    rents, ppm2 = [], []
    for r in rows:
        cc = rent_cc(r.get("price"), r.get("charges"), r.get("charges_included"))
        if cc:
            rents.append(cc)
            value = price_per_m2(cc, r.get("surface_m2"))
            if value:
                ppm2.append(value)
    return {
        "active_count": len(rows),
        "median_rent_cc": round(median(rents), 1) if rents else None,
        "median_ppm2": round(median(ppm2), 2) if ppm2 else None,
    }


def profile_rows(conn, profile_key: str) -> List[Dict]:
    """Annonces visibles du profil (connexion en sqlite3.Row)."""
    return [dict(r) for r in conn.execute(PROFILE_ACTIVE_SQL, (profile_key,)).fetchall()]


def record_run(
    started_at: datetime,
    profile_keys: List[str],
    site_names: List[str],
    total,
    finished_at: Optional[datetime] = None,
) -> int:
    """Enregistre une ligne par profil. `total` : pipeline.RunStats. Retourne le nombre de lignes."""
    finished_at = finished_at or datetime.now()
    with connect() as conn:
        # Annonces retirées pendant le run (dates posées par le trigger de la migration 11)
        for key in profile_keys:
            expired = conn.execute(
                """SELECT COUNT(*) FROM annonces a
                   JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
                   WHERE a.status = 'expired' AND a.expired_at >= ?""",
                (key, started_at.isoformat(timespec="seconds")),
            ).fetchone()[0]
            snap = snapshot(profile_rows(conn, key))
            conn.execute(
                """INSERT INTO run_stats (started_at, finished_at, profile, sites, new_count, updated,
                       reactivated, expired, duplicates, opened, active_count, median_rent_cc, median_ppm2)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    started_at.isoformat(), finished_at.isoformat(), key, ",".join(site_names),
                    total.new_by_profile.get(key, 0), total.updated, total.reactivated, expired,
                    total.duplicates, total.opened,
                    snap["active_count"], snap["median_rent_cc"], snap["median_ppm2"],
                ),
            )
    return len(profile_keys)


def last_runs(profile_key: str, limit: int = 2) -> List[Dict]:
    """Derniers runs d'un profil, du plus récent au plus ancien."""
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM run_stats WHERE profile = ? ORDER BY started_at DESC, id DESC LIMIT ?",
            (profile_key, limit),
        ).fetchall()]


def history(profile_key: str, since: Optional[str] = None) -> List[Dict]:
    """Runs d'un profil depuis une date ISO (tendances), du plus ancien au plus récent."""
    with connect() as conn:
        query = "SELECT * FROM run_stats WHERE profile = ?"
        params: list = [profile_key]
        if since:
            query += " AND started_at >= ?"
            params.append(since)
        return [dict(r) for r in conn.execute(query + " ORDER BY started_at, id", params).fetchall()]
