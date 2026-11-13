# scrapers/detail_extractors/seloger_json.py
# =========================
# Extraction SeLoger depuis l'état JSON embarqué (Sprint 15.3)
#
# Les pages SeLoger (micro-frontends « UFRN ») embarquent leur état dans un script :
#   <script id="…">window["NOM"]=JSON.parse("…chaîne JSON échappée…")</script>
#
# - page de recherche : window["__UFRN_FETCHER__"]
#     data["classified-serp-data"] = {"classifieds": [ids dans l'ordre], "classifiedsData": {id: {…}}}
#     → prix, surface, pièces, photos, annonceur, quartier ; description TRONQUÉE (« ... »),
#       pas de GPS ni de DPE : la page de détail reste à visiter.
# - page d'annonce : window["__UFRN_LIFECYCLE_SERVERREQUEST__"]
#     app_cldp.data.classified = {"sections": {location, description, hardFacts, energy,
#       price, features, …}, "domains": {"medias": …}, "contactSections": …, "metadata": …}
#     → tout, dont un point GPS exact quand l'adresse est publiée (sinon polygone du quartier).
#
# Structure constatée sur de vraies pages le 2026-11-13 (3 annonces, profils ENAC et Blagnac).
# Tous les champs sont optionnels : une clé absente donne None, jamais d'exception.
# =========================

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

SELOGER_BASE_URL = "https://www.seloger.com"

SEARCH_STATE = "__UFRN_FETCHER__"
DETAIL_STATE = "__UFRN_LIFECYCLE_SERVERREQUEST__"

# SeLoger met parfois ce code postal fictif (annonce sans adresse) : inutilisable pour géocoder
_FAKE_ZIPCODES = {"99000"}

# Champs remplis à partir du JSON (pour les métriques de remplissage)
JSON_FIELDS = (
    "surface_m2", "nb_rooms", "nb_bedrooms", "floor", "description", "charges",
    "charges_included", "deposit", "furnished", "dpe_rating", "ges_rating", "elevator",
    "photos", "publisher_type", "published_at", "lat", "lon",
)


# ---------------------------------------------------------------------------
# Lecture de l'état embarqué
# ---------------------------------------------------------------------------

def extract_state(html: Optional[str], name: str) -> Optional[Dict]:
    """
    Retourne l'objet de `window["name"]=JSON.parse("…")`, ou None (absent, tronqué, invalide).
    La chaîne passée à JSON.parse est elle-même un littéral JSON : double décodage.
    """
    if not isinstance(html, str) or name not in html:
        return None
    m = re.search(r'window\[\s*["\']%s["\']\s*\]\s*=\s*' % re.escape(name), html)
    if not m:
        return None
    rest = html[m.end():]
    decoder = json.JSONDecoder()
    try:
        if rest.startswith("JSON.parse("):
            literal, _ = decoder.raw_decode(rest[len("JSON.parse("):])
            data = json.loads(literal) if isinstance(literal, str) else None
        else:  # objet littéral directement assigné
            data, _ = decoder.raw_decode(rest)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _bfs(root: Any, predicate, max_depth: int = 6) -> Optional[Dict]:
    frontier: List[Any] = [root]
    for _ in range(max_depth):
        nxt: List[Any] = []
        for node in frontier:
            values: Iterable[Any] = node.values() if isinstance(node, dict) else node
            for value in values:
                if predicate(value):
                    return value
                if isinstance(value, (dict, list)):
                    nxt.append(value)
        if not nxt:
            break
        frontier = nxt
    return None


def _looks_like_detail(obj: Any) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("sections"), dict) and "hardFacts" in obj["sections"]


def find_classified(state: Optional[Dict]) -> Optional[Dict]:
    """Annonce de la page de détail : app_cldp.data.classified, sinon recherche en largeur."""
    if not isinstance(state, dict):
        return None
    classified = (((state.get("app_cldp") or {}).get("data") or {}).get("classified"))
    if _looks_like_detail(classified):
        return classified
    return _bfs(state, _looks_like_detail)


def _looks_like_serp(obj: Any) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("classifiedsData"), dict)


def find_search_classifieds(state: Optional[Dict]) -> List[Dict]:
    """
    Annonces de la page de résultats, dans l'ordre d'affichage (`classifieds`).
    Les annonces « élargies » / « suggérées » (hors critères) sont ignorées.
    """
    if not isinstance(state, dict):
        return []
    serp = ((state.get("data") or {}).get("classified-serp-data"))
    if not _looks_like_serp(serp):
        serp = _bfs(state, _looks_like_serp)
    if not serp:
        return []
    data = serp["classifiedsData"]
    order = serp.get("classifieds")
    ids = order if isinstance(order, list) and order else list(data.keys())
    return [data[i] for i in ids if isinstance(i, str) and isinstance(data.get(i), dict)]


# ---------------------------------------------------------------------------
# Conversion des valeurs
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\xa0", "").replace(" ", "").replace(" ", "")
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def _to_int(value: Any) -> Optional[int]:
    f = _to_float(value)
    return int(round(f)) if f is not None else None


def _negative(label: str) -> bool:
    return bool(re.match(r"\s*(non|sans|pas)\b", label, re.IGNORECASE))


def _floor(value: Any) -> Optional[int]:
    """« 2ème Étage » → 2, « 1er étage » → 1, « Rez-de-chaussée » → 0."""
    if not isinstance(value, str):
        return _to_int(value)
    if re.search(r"rez[\s-]*de[\s-]*chauss|\brdc\b", value, re.IGNORECASE):
        return 0
    m = re.search(r"(\d+)", value)
    return int(m.group(1)) if m else None


def _rating(value: Any) -> Optional[str]:
    if isinstance(value, str):
        text = value.strip().upper()
        if len(text) == 1 and text in "ABCDEFG":
            return text
    return None


# ---------------------------------------------------------------------------
# Champs communs recherche / détail
# ---------------------------------------------------------------------------

def _facts(hard_facts: Dict) -> Dict[str, Dict]:
    return {
        f["type"]: f for f in (hard_facts.get("facts") or [])
        if isinstance(f, dict) and f.get("type")
    }


def _fact_value(facts: Dict[str, Dict], kind: str) -> Any:
    fact = facts.get(kind)
    if not fact:
        return None
    return fact.get("splitValue") if fact.get("splitValue") not in (None, "") else fact.get("value")


def _photos(images: Any) -> Optional[List[str]]:
    """URLs des photos ; le logo de l'agence (classification LOGO) est écarté (doublons 15.8)."""
    if not isinstance(images, list):
        return None
    urls = []
    for img in images:
        if not isinstance(img, dict):
            continue
        if ((img.get("classification") or {}).get("name") or "").upper() == "LOGO":
            continue
        url = img.get("url")
        if isinstance(url, str) and url.startswith("http") and url not in urls:
            urls.append(url)
    return urls or None


def _published_at(metadata: Any) -> Optional[str]:
    if isinstance(metadata, dict):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", str(metadata.get("creationDate") or ""))
        if m:
            return m.group(1)
    return None


def _publisher_from_card(card: Any) -> Optional[str]:
    if not isinstance(card, dict):
        return None
    if card.get("isPrivateOwner") is True:
        return "individual"
    kind = str(card.get("publisherType") or "").upper()
    if kind in ("AGENCY", "PROFESSIONAL", "PRO"):
        return "agency"
    if kind in ("PRIVATE", "INDIVIDUAL"):
        return "individual"
    if card.get("isPrivateOwner") is False:
        return "agency"
    return None


def _publisher_type(classified: Dict) -> Optional[str]:
    found = (
        _publisher_from_card(classified.get("provider"))
        or _publisher_from_card((classified.get("contactSections") or {}).get("contactCard"))
    )
    if found:
        return found
    kind = str(classified.get("type") or "").upper()
    if kind == "PROFESSIONAL":
        return "agency"
    if kind == "PRIVATE":
        return "individual"
    client = str(_legacy(classified).get("client_type") or "").lower()
    return {"pro": "agency", "part": "individual", "private": "individual"}.get(client)


def _legacy(classified: Dict) -> Dict:
    """legacyTracking : à plat (recherche) ou sous products[0] (détail)."""
    legacy = classified.get("legacyTracking") or {}
    if not isinstance(legacy, dict):
        return {}
    products = legacy.get("products")
    if isinstance(products, list) and products and isinstance(products[0], dict):
        return products[0]
    return legacy


def _location_label(address: Any) -> str:
    """Même forme que les cartes DOM : « Minimes, Toulouse (31200) »."""
    if not isinstance(address, dict):
        return ""
    city = address.get("city") or ""
    zipcode = address.get("zipCode") or ""
    district = address.get("district") or ""
    label = city
    if zipcode and zipcode not in _FAKE_ZIPCODES:
        label = f"{city} ({zipcode})" if city else zipcode
    if district and district.lower() != city.lower():
        label = f"{district}, {label}" if label else district
    return label


def _polygon_centroid(coordinates: Any) -> Optional[Tuple[float, float]]:
    """Moyenne des sommets d'un (Multi)Polygon GeoJSON → (lat, lon)."""
    points: List[Tuple[float, float]] = []

    def collect(node):
        if isinstance(node, list) and len(node) == 2 and all(isinstance(v, (int, float)) for v in node):
            points.append((float(node[1]), float(node[0])))
        elif isinstance(node, list):
            for child in node:
                collect(child)

    collect(coordinates)
    if not points:
        return None
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def _location(location: Any) -> Dict:
    """
    Point GeoJSON + adresse publiée → position exacte ; polygone (quartier affiché à la
    place de l'adresse) → son centre, approximatif.
    """
    if not isinstance(location, dict):
        return {}
    geometry = location.get("geometry") or {}
    if not isinstance(geometry, dict):
        return {}
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    point = None
    if kind == "Point" and isinstance(coords, list) and len(coords) >= 2:
        lon, lat = _to_float(coords[0]), _to_float(coords[1])
        if lat is not None and lon is not None:
            point = (lat, lon)
        precision = "exact" if location.get("isAddressPublished") else "approx"
    elif kind in ("Polygon", "MultiPolygon"):
        point = _polygon_centroid(coords)
        precision = "approx"
    if not point or not (-90 <= point[0] <= 90 and -180 <= point[1] <= 180):
        return {}
    return {"lat": round(point[0], 6), "lon": round(point[1], 6), "geo_precision": precision}


# ---------------------------------------------------------------------------
# Page de détail
# ---------------------------------------------------------------------------

def _price_lines(price_section: Any) -> List[Tuple[str, Any]]:
    """Toutes les paires (libellé, montant) de la section prix, à n'importe quelle profondeur."""
    lines: List[Tuple[str, Any]] = []

    def walk(node):
        if isinstance(node, dict):
            label = node.get("label")
            if isinstance(label, dict):
                label = label.get("main")
            value = node.get("value")
            if isinstance(label, str):
                if isinstance(value, dict):
                    main = value.get("main") or {}
                    amount = main.get("ariaLabel") or main.get("value") if isinstance(main, dict) else None
                    lines.append((label, amount))
                elif "text" in node:
                    lines.append((label, node.get("text")))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(price_section)
    return lines


def _line(lines: List[Tuple[str, Any]], pattern: str, exclude: str = r"$^") -> Optional[int]:
    for label, amount in lines:
        if re.search(pattern, label, re.IGNORECASE) and not re.search(exclude, label, re.IGNORECASE):
            value = _to_int(amount)
            if value is not None:
                return value
    return None


def _features(sections: Dict) -> Dict[str, str]:
    """{icône: libellé} de l'aperçu et des catégories détaillées (« furnished » → « Non meublé »)."""
    features = sections.get("features") or {}
    found: Dict[str, str] = {}
    elements = list(features.get("preview") or [])
    details = features.get("details") or {}
    for category in (details.get("categories") or []) if isinstance(details, dict) else []:
        elements.extend((category or {}).get("elements") or [])
    for el in elements:
        if isinstance(el, dict) and el.get("icon") and isinstance(el.get("value"), str):
            found.setdefault(str(el["icon"]), el["value"].strip())
    return found


def _energy(sections: Dict) -> Dict[str, Any]:
    energy = sections.get("energy") or {}
    result: Dict[str, Any] = {}
    for cert in energy.get("certificates") or []:
        for scale in (cert or {}).get("scales") or []:
            if not isinstance(scale, dict):
                continue
            rating = _rating((scale.get("efficiencyClass") or {}).get("rating"))
            name = f"{scale.get('name') or ''} {scale.get('type') or ''}".lower()
            if "ges" in name or "gaz" in name or "ghg" in name:
                result.setdefault("ges_rating", rating)
            elif "dpe" in name or "énergétique" in name or "energy" in name:
                result.setdefault("dpe_rating", rating)
    extra = {
        f.get("label") or f.get("type"): f.get("value")
        for f in energy.get("features") or []
        if isinstance(f, dict) and f.get("value") not in (None, "")
    }
    result["energy_features"] = extra
    return result


def parse_detail(classified: Dict) -> Dict:
    """
    Annonce de la page de détail → champs de la table `annonces`.
    Les champs introuvables valent None ; `extra_attributes` garde le reste (équipements,
    disponibilité, honoraires, chauffage…) pour 15.4 / 15.5 sans re-scraper.
    """
    sections = classified.get("sections") or {}
    hard_facts = sections.get("hardFacts") or {}
    facts = _facts(hard_facts)
    legacy = _legacy(classified)
    features = _features(sections)
    energy = _energy(sections)
    price_info = hard_facts.get("price") or {}
    lines = _price_lines(sections.get("price"))

    result: Dict[str, Any] = {}
    result["surface_m2"] = _to_float(_fact_value(facts, "livingSpace")) or _to_float(legacy.get("space"))
    result["nb_rooms"] = _to_int(_fact_value(facts, "numberOfRooms")) or _to_int(legacy.get("nb_rooms"))
    result["nb_bedrooms"] = _to_int(_fact_value(facts, "numberOfBedrooms")) or _to_int(legacy.get("nb_bedrooms"))
    floor_text = (facts.get("numberOfFloors") or {}).get("value") or features.get("floors")
    result["floor"] = _floor(floor_text)

    furnished = features.get("furnished")
    result["furnished"] = (not _negative(furnished)) if furnished else None
    elevator = features.get("elevator")
    result["elevator"] = (not _negative(elevator)) if elevator else None

    charges_label = str(price_info.get("chargesLabel") or "").lower()
    result["charges_included"] = {"cc": True, "hc": False}.get(charges_label)
    result["charges"] = _line(lines, r"charges|co[uû]ts suppl", exclude=r"loyer|hors charges")
    result["deposit"] = _line(lines, r"d[ée]p[oô]t de garantie|caution")

    result["dpe_rating"] = energy.get("dpe_rating") or _rating(legacy.get("energy_letter"))
    result["ges_rating"] = energy.get("ges_rating")

    description = (sections.get("description") or {}).get("description")
    if not isinstance(description, str) or not description.strip():
        description = (sections.get("mainDescription") or {}).get("description")
    result["description"] = (
        description.replace("\r\n", "\n").strip()
        if isinstance(description, str) and len(description.strip()) > 20 else None
    )

    medias = ((classified.get("domains") or {}).get("medias") or {}).get("images")
    gallery = (sections.get("gallery") or {}).get("images")
    # La galerie de section porte la classification (logo) ; les médias sont la liste complète
    photos = _photos(gallery) or _photos(medias)
    result["photos"] = photos
    result["publisher_type"] = _publisher_type(classified)
    result["published_at"] = _published_at(classified.get("metadata"))
    result["price"] = _to_int(price_info.get("ariaLabel") or price_info.get("value")) or _to_int(legacy.get("price"))
    result.update(_location(sections.get("location")))

    extra: Dict[str, Any] = dict(features)
    extra.update(energy.get("energy_features") or {})
    fees = _line(lines, r"honoraires")
    if fees is not None:
        extra["honoraires"] = fees
    availability = (facts.get("availability") or {}).get("value")
    if availability:
        extra.setdefault("availability", availability)
    if legacy.get("year_of_construction"):
        extra["year_of_construction"] = legacy["year_of_construction"]
    district = ((sections.get("location") or {}).get("address") or {}).get("district")
    if district:
        extra["district"] = district
    result["extra_attributes"] = extra or None
    return result


def extract_from_html(html: Optional[str]) -> Optional[Dict]:
    """Raccourci : HTML de la page d'annonce → champs, ou None si pas de JSON exploitable."""
    classified = find_classified(extract_state(html, DETAIL_STATE))
    return parse_detail(classified) if classified else None


# ---------------------------------------------------------------------------
# Page de résultats de recherche
# ---------------------------------------------------------------------------

# Identifiant SeLoger, trois formes d'URL rencontrées :
#   /annonce/location/occitanie/…/toulouse-31000/26K5F58IG3TY   (actuelle)
#   /annonce/26XNKCIS6TK8
#   /266061609/detail.htm                                       (ancienne, id numérique)
_ID_RE = re.compile(r"/((?=[A-Za-z]*\d)[0-9A-Za-z]{8,})(?:/detail)?(?:\.htm)?/?$")


def canonical_url(url: Optional[str]) -> Optional[str]:
    """
    URL d'annonce sans paramètres ni ancre. Les liens des cartes SeLoger portent toute la
    recherche (dont le numéro de page) : sans normalisation, une même annonce revue sur une
    autre page devenait une nouvelle ligne en base (dédoublonnage par URL exacte).
    """
    if not url:
        return url
    return re.split(r"[?#]", url, maxsplit=1)[0]


def classified_id_from_url(url: Optional[str]) -> Optional[str]:
    """« …/toulouse-31000/26K5F58IG3TY?serp_view=list… » → « 26K5F58IG3TY »."""
    path = canonical_url(url)
    if not path or ("seloger" not in path and not path.startswith("/")):
        return None
    m = _ID_RE.search(path)
    return m.group(1) if m else None


def search_classified_url(classified: Dict) -> Optional[str]:
    url = classified.get("url")
    if isinstance(url, str) and url:
        return canonical_url(url if url.startswith("http") else SELOGER_BASE_URL + url)
    return None


def parse_search_classified(classified: Dict) -> Dict:
    """Annonce de la recherche → champs connus (la description y est tronquée : ignorée)."""
    hard_facts = classified.get("hardFacts") or {}
    facts = _facts(hard_facts)
    raw = classified.get("rawData") or {}
    legacy = _legacy(classified)
    price_info = hard_facts.get("price") or {}

    surface = (raw.get("surface") or {}).get("main") if isinstance(raw.get("surface"), dict) else None
    result: Dict[str, Any] = {
        "surface_m2": _to_float(surface) or _to_float(_fact_value(facts, "livingSpace")),
        "nb_rooms": _to_int(raw.get("nbroom")) or _to_int(_fact_value(facts, "numberOfRooms")),
        "nb_bedrooms": _to_int(_fact_value(facts, "numberOfBedrooms")),
        "floor": _floor((facts.get("numberOfFloors") or {}).get("value")),
        "charges_included": {"cc": True, "hc": False}.get(str(price_info.get("chargesLabel") or "").lower()),
        "photos": _photos((classified.get("gallery") or {}).get("images")),
        "publisher_type": _publisher_type(classified),
        "published_at": _published_at(classified.get("metadata")),
        "price": _to_int(raw.get("price")) or _to_int(legacy.get("price"))
        or _to_int(price_info.get("ariaLabel") or price_info.get("value")),
        # Résumé de la recherche, coupé par SeLoger (« … ») : la vraie description est sur la
        # page de détail. On ne l'enregistre pas pour ne pas figer un texte incomplet.
        "description": None,
    }
    extra: Dict[str, Any] = {}
    availability = (facts.get("availability") or {}).get("value")
    if availability:
        extra["availability"] = availability
    district = ((classified.get("location") or {}).get("address") or {}).get("district")
    if district:
        extra["district"] = district
    if raw.get("propertySubType"):
        extra["property_sub_type"] = raw["propertySubType"]
    result["extra_attributes"] = extra or None
    return result


def search_classified_to_listing(classified: Dict):
    """Annonce de la recherche → `Listing` (modèle commun, Sprint 15.7), ou None sans URL/prix."""
    from scrapers.listing import Listing

    url = search_classified_url(classified)
    d = parse_search_classified(classified)
    price = d.pop("price", None)
    if not url or price is None:
        return None
    title = (classified.get("hardFacts") or {}).get("title") or ""
    address = (classified.get("location") or {}).get("address")
    return Listing(
        site="SeLoger",
        url=url,
        title=title,
        price=price,
        location_raw=_location_label(address),
        source="search_json",
        **{k: v for k, v in d.items() if k in Listing.__dataclass_fields__},
    )


def search_annonces_from_html(html: Optional[str]) -> List[Dict]:
    """HTML d'une page de résultats → annonces du pipeline (vide si pas de JSON exploitable)."""
    annonces = []
    for classified in find_search_classifieds(extract_state(html, SEARCH_STATE)):
        try:
            listing = search_classified_to_listing(classified)
        except Exception:  # une annonce inattendue ne doit pas faire perdre les autres
            continue
        if listing:
            annonces.append(listing.to_annonce())
    return annonces
