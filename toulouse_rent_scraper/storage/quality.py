# storage/quality.py
# =========================
# Santé de l'extraction (Sprint 15.1)
#
# Un site change sa page → les sélecteurs ne trouvent plus rien → les fiches se
# vident sans erreur visible. On mesure donc, par site, le taux de remplissage des
# champs clés et la part d'annonces extraites depuis le JSON embarqué, et on alerte
# quand ils tombent sous un seuil.
# =========================

from collections import defaultdict
from typing import Dict, Iterable, List, Optional

from config import QUALITY_MIN_FILL_RATES, QUALITY_MIN_JSON_RATE, QUALITY_MIN_SAMPLES

# Champs suivis dans le rapport `quality` (ordre d'affichage)
TRACKED_FIELDS = (
    "surface_m2", "nb_rooms", "nb_bedrooms", "floor", "description", "photos",
    "charges", "deposit", "furnished", "dpe_rating", "ges_rating", "elevator",
    "publisher_type", "published_at", "lat",
)

_LABELS = {
    "surface_m2": "surface", "nb_rooms": "pièces", "nb_bedrooms": "chambres", "floor": "étage",
    "description": "descr.", "photos": "photos", "charges": "charges", "deposit": "caution",
    "furnished": "meublé", "dpe_rating": "DPE", "ges_rating": "GES", "elevator": "ascens.",
    "publisher_type": "annonceur", "published_at": "date", "lat": "GPS exact",
}


def _filled(row: Dict, field: str) -> bool:
    if field == "lat":
        return row.get("lat") is not None and row.get("geo_precision") == "exact"
    value = row.get(field)
    return value not in (None, "", "[]")


def fill_rates(rows: List[Dict], fields: Iterable[str] = TRACKED_FIELDS) -> Dict[str, float]:
    """Part (0–1) des lignes où chaque champ est renseigné."""
    if not rows:
        return {f: 0.0 for f in fields}
    return {f: sum(_filled(r, f) for r in rows) / len(rows) for f in fields}


def json_rate(rows: List[Dict]) -> Optional[float]:
    """Part des lignes extraites (au moins en partie) depuis le JSON ; None si aucune info."""
    sources = [r.get("extraction_source") for r in rows if r.get("extraction_source")]
    if not sources:
        return None
    return sum(s.startswith("json") for s in sources) / len(sources)


def check_fill_rates(rows_by_site: Dict[str, List[Dict]]) -> List[str]:
    """
    Alertes lisibles pour les sites dont l'extraction semble cassée.
    Ne juge que les sites avec au moins QUALITY_MIN_SAMPLES annonces.
    """
    alerts = []
    for site, rows in sorted(rows_by_site.items()):
        if len(rows) < QUALITY_MIN_SAMPLES:
            continue
        rates = fill_rates(rows, QUALITY_MIN_FILL_RATES)
        low = [
            f"{_LABELS.get(f, f)} {rates[f]:.0%} (< {minimum:.0%})"
            for f, minimum in QUALITY_MIN_FILL_RATES.items()
            if rates[f] < minimum
        ]
        if low:
            alerts.append(f"{site} : champs peu remplis sur {len(rows)} annonces — " + ", ".join(low))
        minimum_json = QUALITY_MIN_JSON_RATE.get(site)
        rate = json_rate(rows)
        if minimum_json is not None and rate is not None and rate < minimum_json:
            alerts.append(
                f"{site} : seulement {rate:.0%} des annonces lues depuis le JSON embarqué "
                f"(< {minimum_json:.0%}) — format de page probablement modifié"
            )
    return alerts


def group_by_site(rows: Iterable[Dict]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for row in rows:
        grouped[row.get("site") or "?"].append(row)
    return dict(grouped)


def enriched_rows(days: Optional[int] = None) -> List[Dict]:
    """Annonces enrichies avec succès (optionnellement : enrichies dans les `days` derniers jours)."""
    from storage.sqlite import connect

    cols = ", ".join(("site", "extraction_source", "geo_precision") + TRACKED_FIELDS)
    query = f"SELECT {cols} FROM annonces WHERE enrichment_status = 'done'"
    params: list = []
    if days is not None:
        query += " AND enriched_at >= datetime('now', 'localtime', ?)"
        params.append(f"-{int(days)} days")
    with connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def format_report(rows_by_site: Dict[str, List[Dict]]) -> str:
    """Tableau texte : une ligne par site, une colonne par champ suivi."""
    if not rows_by_site:
        return "Aucune annonce enrichie."
    headers = ["site", "n", "JSON"] + [_LABELS.get(f, f) for f in TRACKED_FIELDS]
    lines = []
    for site, rows in sorted(rows_by_site.items()):
        rate = json_rate(rows)
        rates = fill_rates(rows)
        lines.append(
            [site, str(len(rows)), "—" if rate is None else f"{rate:.0%}"]
            + [f"{rates[f]:.0%}" for f in TRACKED_FIELDS]
        )
    widths = [max(len(h), *(len(line[i]) for line in lines)) for i, h in enumerate(headers)]
    fmt = lambda cells: "  ".join(c.rjust(w) if i else c.ljust(w) for i, (c, w) in enumerate(zip(cells, widths)))  # noqa: E731
    return "\n".join([fmt(headers), fmt(["-" * w for w in widths])] + [fmt(line) for line in lines])
