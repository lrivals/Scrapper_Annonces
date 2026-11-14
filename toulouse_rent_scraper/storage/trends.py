# storage/trends.py
# =========================
# Sprint 2-bis.4 — séries de tendances d'un profil (page « Tendances », /api/v1/stats).
#   - par jour, depuis annonce_profiles.matched_at (disponible pour tout l'historique) :
#     nouvelles annonces par site, loyer CC médian et €/m² médian des nouvelles ;
#   - par run, depuis run_stats (Sprint 5.0) : annonces visibles et médianes du stock.
# Les annonces exclues par les critères du profil et les doublons d'un autre site ne comptent pas.
# =========================

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Dict, List, Optional

from storage.sqlite import connect

DEFAULT_DAYS = 90
MAX_DAYS = 730
ROLLING_DAYS = 7


def clamp_days(value, default: int = DEFAULT_DAYS) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(days, MAX_DAYS))


def daily_series(profile_key: str, days: int = DEFAULT_DAYS, now: Optional[datetime] = None) -> Dict:
    """
    {"days": ["2026-11-01", …], "new_by_site": {site: [n, …]}, "median_rent_cc": [… | None],
     "median_ppm2": [… | None], "median_rent_cc_7d": [… | None]} — un point par jour, jours sans
    annonce compris. La médiane sur 7 jours glissants lisse les jours à une ou deux annonces.
    """
    from scoring import price_per_m2, rent_cc

    now = now or datetime.now()
    start = (now - timedelta(days=days - 1)).date()
    # 6 jours de plus en tête : la médiane glissante du premier jour affiché est complète
    query_start = start - timedelta(days=ROLLING_DAYS - 1)
    labels = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    with connect() as conn:
        rows = conn.execute(
            """SELECT substr(ap.matched_at, 1, 10) AS day, a.site, a.price, a.charges,
                      a.charges_included, a.surface_m2
               FROM annonce_profiles ap JOIN annonces a ON a.id = ap.annonce_id
               WHERE ap.profile = ? AND ap.matched_at >= ?
                 AND ap.excluded_reasons IS NULL AND a.duplicate_of IS NULL""",
            (profile_key, query_start.isoformat()),
        ).fetchall()

    counts = defaultdict(lambda: defaultdict(int))
    rents, ppm2 = defaultdict(list), defaultdict(list)
    for r in rows:
        if r["day"] >= start.isoformat():
            counts[r["site"] or "?"][r["day"]] += 1
        cc = rent_cc(r["price"], r["charges"], r["charges_included"])
        if cc:
            rents[r["day"]].append(cc)
            value = price_per_m2(cc, r["surface_m2"])
            if value:
                ppm2[r["day"]].append(value)
    return {
        "days": labels,
        "new_by_site": {site: [by_day.get(d, 0) for d in labels] for site, by_day in sorted(counts.items())},
        "median_rent_cc": [round(median(rents[d])) if rents[d] else None for d in labels],
        "median_ppm2": [round(median(ppm2[d]), 1) if ppm2[d] else None for d in labels],
        "median_rent_cc_7d": [_rolling_median(rents, d) for d in labels],
    }


def _rolling_median(values_by_day: Dict[str, List[float]], day: str) -> Optional[int]:
    end = datetime.fromisoformat(day).date()
    window = [v for i in range(ROLLING_DAYS)
              for v in values_by_day.get((end - timedelta(days=i)).isoformat(), [])]
    return round(median(window)) if window else None


def run_series(profile_key: str, days: int = DEFAULT_DAYS, now: Optional[datetime] = None) -> List[Dict]:
    """Runs journalisés du profil sur la période (du plus ancien au plus récent)."""
    from storage.run_stats import history

    since = ((now or datetime.now()) - timedelta(days=days)).isoformat()
    return history(profile_key, since)


def profile_summary(profile_key: str) -> Dict:
    """Stock actuel : nombre d'annonces par site, médianes, nouvelles sur 24 h et 7 jours."""
    from storage.run_stats import profile_rows, snapshot

    now = datetime.now()
    with connect() as conn:
        rows = profile_rows(conn, profile_key)
    by_site = defaultdict(int)
    for r in rows:
        by_site[r.get("site") or "?"] += 1

    def new_since(delta: timedelta) -> int:
        limit = (now - delta).isoformat()
        return sum(1 for r in rows if (r.get("matched_at") or "") >= limit)

    return {
        **snapshot(rows),
        "by_site": dict(sorted(by_site.items())),
        "new_24h": new_since(timedelta(days=1)),
        "new_7d": new_since(timedelta(days=7)),
    }
