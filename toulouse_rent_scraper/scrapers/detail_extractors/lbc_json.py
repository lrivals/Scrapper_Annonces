# scrapers/detail_extractors/lbc_json.py
# =========================
# Extraction LeBonCoin depuis le JSON embarqué (Sprint 15.1)
#
# LeBonCoin est une application Next.js : chaque page d'annonce contient
#   <script id="__NEXT_DATA__" type="application/json">{…}</script>
# avec l'objet complet de l'annonce (props.pageProps.ad). C'est la source la plus
# fiable : valeurs typées, pas de regex sur le texte de la page, coordonnées GPS.
#
# Forme attendue de l'annonce (champs utilisés) :
#   {
#     "list_id": 123, "subject": "…", "body": "…", "price": [650],
#     "first_publication_date": "2026-11-10 08:12:44",
#     "images": {"urls_large": [...], "urls": [...]},
#     "attributes": [{"key": "square", "value": "35", "value_label": "35 m²"}, …],
#     "location": {"lat": 43.6, "lng": 1.44, "is_shape": false, "source": "address", …},
#     "owner": {"type": "pro" | "private", …}
#   }
# Les clés d'attributs varient selon les annonces : chaque champ accepte plusieurs
# clés candidates, et tous les attributs bruts sont conservés (extra_attributes)
# pour pouvoir en exploiter de nouveaux sans re-scraper.
# =========================

import json
import re
from typing import Any, Dict, Iterable, List, Optional

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

# Clés d'attributs candidates, par champ (la première trouvée gagne)
ATTRIBUTE_KEYS = {
    "surface_m2": ("square", "surface", "living_area"),
    "nb_rooms": ("rooms", "nb_rooms"),
    "nb_bedrooms": ("bedrooms", "nb_bedrooms"),
    "floor": ("floor_number", "floor"),
    "furnished": ("furnished",),
    "dpe_rating": ("energy_rate", "dpe"),
    "ges_rating": ("ges", "ghg_rate"),
    "elevator": ("elevator",),
    "charges_included": ("charges_included",),
    "charges": ("monthly_charges", "charges", "rent_charges", "charges_amount"),
    "deposit": ("security_deposit", "deposit", "guarantee_deposit"),
}

_TRUE = {"1", "true", "oui", "yes"}
_FALSE = {"0", "2", "false", "non", "no"}

# Champs remplis à partir de l'annonce JSON (pour les métriques de remplissage)
JSON_FIELDS = (
    "surface_m2", "nb_rooms", "nb_bedrooms", "floor", "description", "charges",
    "charges_included", "deposit", "furnished", "dpe_rating", "ges_rating", "elevator",
    "photos", "publisher_type", "published_at", "lat", "lon",
)


# ---------------------------------------------------------------------------
# Localisation de l'annonce dans le document
# ---------------------------------------------------------------------------

def extract_next_data(html: Optional[str]) -> Optional[Dict]:
    """Retourne le JSON de `__NEXT_DATA__`, ou None (absent, tronqué, invalide)."""
    if not isinstance(html, str) or "__NEXT_DATA__" not in html:
        return None
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _looks_like_ad(obj: Any) -> bool:
    return isinstance(obj, dict) and "list_id" in obj and (
        "attributes" in obj or "subject" in obj
    )


def find_ad(next_data: Optional[Dict], max_depth: int = 6) -> Optional[Dict]:
    """
    L'annonce est normalement en props.pageProps.ad ; à défaut on cherche, en largeur,
    le premier objet qui ressemble à une annonce (list_id + attributes/subject).
    """
    if not isinstance(next_data, dict):
        return None
    ad = (next_data.get("props") or {}).get("pageProps", {}).get("ad")
    if _looks_like_ad(ad):
        return ad

    frontier: List[Any] = [next_data]
    for _ in range(max_depth):
        nxt: List[Any] = []
        for node in frontier:
            values: Iterable[Any] = node.values() if isinstance(node, dict) else node
            for value in values:
                if _looks_like_ad(value):
                    return value
                if isinstance(value, (dict, list)):
                    nxt.append(value)
        if not nxt:
            break
        frontier = nxt
    return None


# ---------------------------------------------------------------------------
# Conversion des valeurs
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:[.,]\d+)?", str(value).replace("\xa0", "").replace(" ", "").replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def _to_int(value: Any) -> Optional[int]:
    f = _to_float(value)
    return int(round(f)) if f is not None else None


def _to_bool(value: Any, label: Any = None) -> Optional[bool]:
    for candidate in (value, label):
        if candidate is None:
            continue
        if isinstance(candidate, bool):
            return candidate
        text = str(candidate).strip().lower()
        if text.startswith("non ") or text.startswith("pas "):
            return False
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    # Libellé lisible : « Meublé », « Non meublé », « Avec ascenseur »…
    if isinstance(label, str) and label.strip():
        return not re.match(r"\s*(non|sans|pas)\b", label, re.IGNORECASE)
    return None


def _to_rating(value: Any, label: Any = None) -> Optional[str]:
    """Étiquette DPE/GES : une lettre A–G, sinon None (« Vierge », « Non renseigné »…)."""
    for candidate in (label, value):
        if isinstance(candidate, str):
            text = candidate.strip().upper()
            if len(text) == 1 and text in "ABCDEFG":
                return text
            m = re.match(r"^([A-G])\b", text)
            if m:
                return m.group(1)
    return None


def _attributes_map(ad: Dict) -> Dict[str, Dict]:
    attrs = {}
    for attr in ad.get("attributes") or []:
        if isinstance(attr, dict) and attr.get("key"):
            attrs[str(attr["key"])] = attr
    return attrs


def _attr(attrs: Dict[str, Dict], field: str) -> Optional[Dict]:
    for key in ATTRIBUTE_KEYS[field]:
        if key in attrs:
            return attrs[key]
    return None


def _first_price(ad: Dict) -> Optional[int]:
    price = ad.get("price")
    if isinstance(price, list):
        price = price[0] if price else None
    if price is None and ad.get("price_cents") is not None:
        cents = _to_int(ad.get("price_cents"))
        return cents // 100 if cents is not None else None
    return _to_int(price)


def _photos(ad: Dict) -> Optional[List[str]]:
    images = ad.get("images") or {}
    if not isinstance(images, dict):
        return None
    for key in ("urls_large", "urls", "urls_thumb"):
        urls = images.get(key)
        if isinstance(urls, list):
            clean = [u for u in dict.fromkeys(urls) if isinstance(u, str) and u.startswith("http")]
            if clean:
                return clean
    thumb = images.get("thumb_url") or images.get("small_url")
    return [thumb] if isinstance(thumb, str) and thumb.startswith("http") else None


def _published_at(ad: Dict) -> Optional[str]:
    for key in ("first_publication_date", "index_date"):
        value = ad.get(key)
        if isinstance(value, str):
            m = re.match(r"(\d{4}-\d{2}-\d{2})", value)
            if m:
                return m.group(1)
    return None


def _publisher_type(ad: Dict) -> Optional[str]:
    owner = ad.get("owner") or {}
    kind = str(owner.get("type") or "").lower() if isinstance(owner, dict) else ""
    if kind in ("pro", "professional", "agency"):
        return "agency"
    if kind in ("private", "particulier", "individual"):
        return "individual"
    return None


def _location(ad: Dict) -> Dict:
    """
    lat/lon + précision. `is_shape` (zone affichée au lieu d'un point) ou une source
    « city » signifient que le point est approximatif (centre de commune / quartier).
    """
    loc = ad.get("location") or {}
    if not isinstance(loc, dict):
        return {}
    lat, lon = _to_float(loc.get("lat")), _to_float(loc.get("lng", loc.get("lon")))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {}
    approx = bool(loc.get("is_shape")) or str(loc.get("source") or "").lower() in ("city", "zipcode")
    return {"lat": lat, "lon": lon, "geo_precision": "approx" if approx else "exact"}


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def parse_ad(ad: Dict) -> Dict:
    """
    Convertit l'annonce JSON en champs de la table `annonces`.
    Les champs introuvables valent None ; `extra_attributes` garde tous les attributs bruts.
    """
    attrs = _attributes_map(ad)

    def value(field):
        attr = _attr(attrs, field)
        return (attr.get("value"), attr.get("value_label")) if attr else (None, None)

    result: Dict[str, Any] = {}

    v, _ = value("surface_m2")
    result["surface_m2"] = _to_float(v)
    v, _ = value("nb_rooms")
    result["nb_rooms"] = _to_int(v)
    v, _ = value("nb_bedrooms")
    result["nb_bedrooms"] = _to_int(v)
    v, label = value("floor")
    if isinstance(label, str) and re.search(r"rez", label, re.IGNORECASE):
        result["floor"] = 0
    else:
        result["floor"] = _to_int(v)

    v, label = value("furnished")
    result["furnished"] = _to_bool(v, label)
    v, label = value("elevator")
    result["elevator"] = _to_bool(v, label)
    v, label = value("charges_included")
    result["charges_included"] = _to_bool(v, label)

    v, label = value("dpe_rating")
    result["dpe_rating"] = _to_rating(v, label)
    v, label = value("ges_rating")
    result["ges_rating"] = _to_rating(v, label)

    v, _ = value("charges")
    result["charges"] = _to_int(v)
    v, _ = value("deposit")
    result["deposit"] = _to_int(v)

    body = ad.get("body")
    result["description"] = body.strip() if isinstance(body, str) and len(body.strip()) > 20 else None
    result["photos"] = _photos(ad)
    result["publisher_type"] = _publisher_type(ad)
    result["published_at"] = _published_at(ad)
    result["price"] = _first_price(ad)
    result.update(_location(ad))

    result["extra_attributes"] = {
        key: attr.get("value_label") if attr.get("value_label") not in (None, "") else attr.get("value")
        for key, attr in attrs.items()
    } or None
    return result


def extract_from_html(html: Optional[str]) -> Optional[Dict]:
    """Raccourci : HTML de la page d'annonce → champs, ou None si pas de JSON exploitable."""
    ad = find_ad(extract_next_data(html))
    return parse_ad(ad) if ad else None


# ---------------------------------------------------------------------------
# Page de résultats de recherche (Sprint 15.2)
#
# La page de recherche est elle aussi rendue par Next.js : `__NEXT_DATA__` contient
# la liste des annonces de la page (props.pageProps.searchData.ads), chacune au même
# format que l'annonce d'une page de détail.
# ⚠️ Avec une pagination côté client (bouton « suivant »), `__NEXT_DATA__` reste celui
# de la première page chargée : l'appelant doit vérifier que la liste correspond aux
# cartes affichées (voir LeBonCoinScraper.page_json_annonces).
# ---------------------------------------------------------------------------

LBC_BASE_URL = "https://www.leboncoin.fr"
_LIST_ID_RE = re.compile(r"/(\d{6,})(?:\.htm)?/?(?:[?#].*)?$")


def list_id_from_url(url: Optional[str]) -> Optional[str]:
    """« https://www.leboncoin.fr/ad/locations/2875512345 » → « 2875512345 »."""
    if not url:
        return None
    m = _LIST_ID_RE.search(url)
    return m.group(1) if m else None


def find_search_ads(next_data: Optional[Dict], max_depth: int = 6) -> List[Dict]:
    """
    Annonces d'une page de résultats : props.pageProps.searchData.ads, sinon la plus
    longue liste d'objets ressemblant à des annonces trouvée dans l'arbre.
    """
    if not isinstance(next_data, dict):
        return []
    search = ((next_data.get("props") or {}).get("pageProps") or {}).get("searchData") or {}
    ads = search.get("ads") if isinstance(search, dict) else None
    if isinstance(ads, list) and any(_looks_like_ad(a) for a in ads):
        return [a for a in ads if _looks_like_ad(a)]

    best: List[Dict] = []
    frontier: List[Any] = [next_data]
    for _ in range(max_depth):
        nxt: List[Any] = []
        for node in frontier:
            values: Iterable[Any] = node.values() if isinstance(node, dict) else node
            for value in values:
                if isinstance(value, list):
                    found = [v for v in value if _looks_like_ad(v)]
                    if len(found) > len(best):
                        best = found
                if isinstance(value, (dict, list)):
                    nxt.append(value)
        if not nxt:
            break
        frontier = nxt
    return best


def ad_url(ad: Dict) -> Optional[str]:
    url = ad.get("url")
    if isinstance(url, str) and url:
        return url if url.startswith("http") else LBC_BASE_URL + url
    if ad.get("list_id"):
        return f"{LBC_BASE_URL}/ad/locations/{ad['list_id']}"
    return None


def _location_label(ad: Dict) -> Optional[str]:
    loc = ad.get("location") or {}
    if not isinstance(loc, dict):
        return None
    if loc.get("city_label"):
        return str(loc["city_label"])
    parts = [str(loc[k]) for k in ("city", "zipcode") if loc.get(k)]
    return " ".join(parts) or None


def search_ad_to_listing(ad: Dict):
    """Annonce de la recherche → `Listing` (modèle commun, Sprint 15.7), ou None sans URL/prix."""
    from scrapers.listing import Listing

    url = ad_url(ad)
    price = _first_price(ad)
    if not url or price is None:
        return None
    d = parse_ad(ad)
    d.pop("price", None)
    return Listing(
        site="LeBonCoin",
        url=url,
        title=ad.get("subject") or "",
        price=price,
        location_raw=_location_label(ad) or "",
        source="search_json",
        **{k: v for k, v in d.items() if k in Listing.__dataclass_fields__},
    )


def search_ad_to_annonce(ad: Dict) -> Optional[Dict]:
    """
    Annonce de la recherche → annonce brute du pipeline (mêmes clés que les cartes DOM),
    plus `details` : les champs d'enrichissement déjà connus.
    `details["enrichment_status"] == "done"` si la fiche est assez complète (description +
    surface) pour se passer de la visite de la page de détail.
    """
    listing = search_ad_to_listing(ad)
    return listing.to_annonce() if listing else None


def search_annonces_from_html(html: Optional[str]) -> List[Dict]:
    """HTML d'une page de résultats → annonces du pipeline (vide si pas de JSON exploitable)."""
    annonces = []
    for ad in find_search_ads(extract_next_data(html)):
        try:
            annonce = search_ad_to_annonce(ad)
        except Exception:  # une annonce inattendue ne doit pas faire perdre les autres
            continue
        if annonce:
            annonces.append(annonce)
    return annonces
