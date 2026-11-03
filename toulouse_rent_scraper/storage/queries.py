# storage/queries.py
# =========================
# Requêtes de lecture de l'interface web (liste, carte, export).
# L'UI ne contient plus de SQL : tout passe par ici.
# =========================

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from storage.sqlite import connect

# Tri autorisé → colonne SQL (liste blanche : la valeur est injectée dans ORDER BY)
SORT_COLUMNS = {
    "score": "ap.score",
    "price": "a.price",
    "distance": "ap.distance_km",
    "distance_enac_km": "ap.distance_km",  # ancien nom (URLs mémorisées)
    "created_at": "a.created_at",
    "site": "a.site",
}


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ListingFilters:
    """Filtres de la liste et de la carte (valeurs brutes de la query string)."""
    site: str = ""
    status: str = ""
    prix_min: str = ""
    prix_max: str = ""
    dups: str = ""

    @classmethod
    def from_args(cls, args) -> "ListingFilters":
        return cls(**{name: args.get(name, "") for name in cls.__dataclass_fields__})

    def cleaned(self) -> "ListingFilters":
        """Copie où les prix invalides sont vidés (pour réafficher le formulaire)."""
        return ListingFilters(
            site=self.site,
            status=self.status,
            prix_min=self.prix_min if _int_or_none(self.prix_min) is not None else "",
            prix_max=self.prix_max if _int_or_none(self.prix_max) is not None else "",
            dups=self.dups,
        )

    def where(self) -> Tuple[str, list]:
        """
        Clause WHERE sur la table aliasée « a ».
        Sans filtre de statut, les annonces masquées sont exclues.
        """
        clauses, params = [], []
        if self.status:
            clauses.append("COALESCE(a.status, 'active') = ?")
            params.append(self.status)
        else:
            clauses.append("COALESCE(a.status, 'active') != 'hidden'")
        if self.site:
            clauses.append("a.site = ?")
            params.append(self.site)
        pmin, pmax = _int_or_none(self.prix_min), _int_or_none(self.prix_max)
        if pmin is not None:
            clauses.append("a.price >= ?")
            params.append(pmin)
        if pmax is not None:
            clauses.append("a.price <= ?")
            params.append(pmax)
        if self.dups == "hide":
            clauses.append("a.duplicate_of IS NULL")
        return "WHERE " + " AND ".join(clauses), params


def list_annonces(profile: str, filters: ListingFilters, sort: str = "score", order: str = "desc") -> List[Dict]:
    """Annonces d'un profil, avec distance au profil, doublon éventuel et premier prix connu."""
    sort_sql = SORT_COLUMNS.get(sort, SORT_COLUMNS["price"])
    order_sql = "DESC" if order == "desc" else "ASC"
    where_sql, params = filters.where()
    query = f"""
        SELECT a.*,
               ap.distance_km AS distance_km,
               ap.score AS score, ap.score_detail AS score_detail,
               d.site AS dup_site, d.url AS dup_url,
               (SELECT ph.price FROM price_history ph WHERE ph.annonce_id = a.id
                ORDER BY ph.seen_at, ph.id LIMIT 1) AS first_price,
               (SELECT ph.seen_at FROM price_history ph WHERE ph.annonce_id = a.id
                ORDER BY ph.seen_at, ph.id LIMIT 1) AS first_seen
        FROM annonces a
        JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
        LEFT JOIN annonces d ON d.id = a.duplicate_of
        {where_sql}
        ORDER BY {sort_sql} {order_sql}
    """
    with connect() as conn:
        return [dict(r) for r in conn.execute(query, [profile] + params).fetchall()]


def list_sites() -> List[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT site FROM annonces WHERE site IS NOT NULL ORDER BY site"
        ).fetchall()
    return [r[0] for r in rows]


def map_listings(profile: str, filters: ListingFilters) -> List[Dict]:
    """Points de la carte : coordonnées stockées, sinon reprises du cache de géocodage."""
    where_sql, params = filters.where()
    query = f"""
        SELECT a.id, a.title, a.price, a.location_raw, ap.distance_km, ap.score, a.url,
               COALESCE(a.lat, g.latitude) AS lat,
               COALESCE(a.lon, g.longitude) AS lon
        FROM annonces a
        JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
        LEFT JOIN geocoding_cache g ON a.location_raw = g.address
        {where_sql}
        ORDER BY a.price ASC
    """
    with connect() as conn:
        return [dict(r) for r in conn.execute(query, [profile] + params).fetchall()]


def annonces_by_ids(ids: List[int], profile: str) -> List[Dict]:
    """Annonces sélectionnées pour l'export, avec leur distance au profil."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    query = f"""
        SELECT a.*, ap.distance_km AS distance_km, ap.score AS score
        FROM annonces a
        LEFT JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
        WHERE a.id IN ({placeholders})
        ORDER BY a.price ASC
    """
    with connect() as conn:
        return [dict(r) for r in conn.execute(query, [profile] + list(ids)).fetchall()]
