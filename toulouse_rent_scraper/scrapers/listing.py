# scrapers/listing.py
# =========================
# Modèle commun d'annonce (Sprint 15.7)
#
# Chaque source qui lit des données structurées (JSON d'API ou embarqué dans la page)
# produit des `Listing`. `to_annonce()` les convertit dans le format que le pipeline
# consomme depuis le début (mêmes clés que les cartes DOM), plus :
#   - lat / lon / geo_precision : position fournie par le site ;
#   - nb_rooms : pour le filtre « pièces » des profils ;
#   - details : champs d'enrichissement, enregistrés à l'insertion (pipeline._save_search_details).
# Les scrapers par cartes DOM (SeLoger, repli LBC) continuent de produire des dicts.
# =========================

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# Champs de `details` copiés tels quels (mêmes noms que les colonnes de `annonces`)
DETAIL_FIELDS = (
    "surface_m2", "nb_rooms", "nb_bedrooms", "floor", "description", "charges",
    "charges_included", "deposit", "furnished", "dpe_rating", "ges_rating", "elevator",
    "photos", "publisher_type", "published_at",
)

# Sans ces champs, l'annonce n'est pas jugée complète (la page de détail reste à visiter)
COMPLETE_FIELDS = ("description", "surface_m2")


@dataclass
class Listing:
    site: str
    url: str
    title: str
    price: Optional[int]
    location_raw: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    geo_precision: Optional[str] = None          # 'exact' | 'approx'
    surface_m2: Optional[float] = None
    nb_rooms: Optional[int] = None
    nb_bedrooms: Optional[int] = None
    floor: Optional[int] = None
    description: Optional[str] = None
    charges: Optional[int] = None
    charges_included: Optional[bool] = None
    deposit: Optional[int] = None
    furnished: Optional[bool] = None
    dpe_rating: Optional[str] = None
    ges_rating: Optional[str] = None
    elevator: Optional[bool] = None
    photos: Optional[List[str]] = None
    publisher_type: Optional[str] = None         # 'agency' | 'individual'
    published_at: Optional[str] = None           # AAAA-MM-JJ
    extra_attributes: Optional[Dict[str, Any]] = None
    source: str = "json"                         # extraction_source enregistrée
    # True : la source donne l'annonce entière (API) → jamais de visite de la page de détail
    authoritative: bool = False
    field_sources: Dict[str, str] = field(default_factory=dict)

    def is_complete(self) -> bool:
        return self.authoritative or all(getattr(self, f) is not None for f in COMPLETE_FIELDS)

    def details(self) -> Dict[str, Any]:
        d = {f: getattr(self, f) for f in DETAIL_FIELDS}
        d["extra_attributes"] = self.extra_attributes
        d["extraction_source"] = self.source
        d["field_sources"] = self.field_sources or {
            f: self.source for f in DETAIL_FIELDS if d.get(f) is not None
        }
        if self.is_complete():
            d["enrichment_status"] = "done"
        return d

    def to_annonce(self) -> Dict[str, Any]:
        """Annonce brute pour `pipeline.process_annonces`."""
        annonce: Dict[str, Any] = {
            "site": self.site,
            "title": (self.title or "").strip(),
            "price": self.price,
            "location_raw": self.location_raw or "",
            "url": self.url,
            # La carte de l'UI n'affiche que la 1re photo ; la liste complète est dans details
            "photos": json.dumps(self.photos[:1]) if self.photos else None,
        }
        if self.lat is not None and self.lon is not None:
            annonce.update(lat=self.lat, lon=self.lon, geo_precision=self.geo_precision or "approx")
        if self.nb_rooms:
            annonce["nb_rooms"] = self.nb_rooms
        annonce["details"] = self.details()
        return annonce

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)
