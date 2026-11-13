# scrapers/bienici.py
# =========================
# Bien'ici (Sprint 15.7) — agrégateur d'agences, interrogé via l'API JSON de son site.
#
# Recherche : GET https://www.bienici.com/realEstateAds.json?filters=<JSON>
#   filters = {"filterType": "rent", "propertyType": ["flat"], "maxPrice": 500,
#              "zoneIdsByTypes": {"zoneIds": ["-35735"]}, "sortBy": "publicationDate",
#              "sortOrder": "desc", "size": 50, "from": 0, "page": 1, "onTheMarket": [true], …}
#   réponse = {"total": 312, "realEstateAds": [{…annonce…}, …]}
#
# Zones : les communes du profil (bienici_places) sont converties en identifiants de
# zone via l'autocomplétion du site (res.bienici.com/suggest.json?q=Toulouse), puis
# mises en cache dans data/bienici_zones.json.
#
# Recherche par URL (bienici_search_url) : l'URL copiée du site
#   /recherche/location/toulouse-31000,blagnac-31700?chambres-min=1&balcon-ou-terrasse=oui&tri=publication-desc
# est traduite en filtres de l'API (table du site : chambres-min → minBedrooms,
# balcon-ou-terrasse → hasBalconyOrTerrace…) et paginée par 24 comme la liste du site.
#
# Chaque annonce de l'API est complète (description, surface, DPE, photos, position) :
# elle est marquée enrichie d'emblée, sans visite de page.
# =========================

import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from config import (
    BIENICI_BASE_URL,
    BIENICI_MAX_DELAY,
    BIENICI_MAX_PAGES,
    BIENICI_MIN_DELAY,
    BIENICI_PAGE_SIZE,
    BIENICI_SEARCH_API,
    BIENICI_SITE_PAGE_SIZE,
    BIENICI_SUGGEST_API,
    BIENICI_TIMEOUT,
    BIENICI_ZONE_CACHE_FILE,
    MAX_PAGES_PER_SITE,
    SearchProfile,
)
from scrapers.api_base import ApiScraper
from scrapers.listing import Listing

SITE_NAME = "Bien'ici"

# Type de bien de l'API → segment d'URL de l'annonce
_PROPERTY_SLUGS = {
    "flat": "appartement", "house": "maison", "loft": "loft",
    "townhouse": "maison", "castle": "chateau", "building": "immeuble",
}

# Attributs « bonus » conservés dans extra_attributes (filtres futurs sans re-scraper)
_EXTRA_KEYS = (
    "propertyType", "availableDate", "agencyRentalFee", "agencyFeeUrl", "heating",
    "hasBalcony", "balconyQuantity", "hasTerrace", "terracesQuantity", "hasGarden",
    "hasParking", "parkingPlacesQuantity", "hasCellar", "hasPool", "isDisabledPeopleFriendly",
    "isStudentResidence", "isInStudentResidence", "newProperty", "priceHasDecreased",
    "modificationDate", "reference", "accountType", "adCreatedByPro",
)


# ---------------------------------------------------------------------------
# Conversion d'une annonce de l'API
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def normalize_place(name: str) -> str:
    return _slug(name)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, list):           # programmes neufs : fourchette [min, max]
        value = min((v for v in value if isinstance(v, (int, float))), default=None)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    f = _number(value)
    return int(round(f)) if f is not None else None


def _bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _rating(value: Any) -> Optional[str]:
    """« D » → D ; « NS » (non soumis), « VI » (vierge), vide → None."""
    if isinstance(value, str) and len(value.strip()) == 1 and value.strip().upper() in "ABCDEFG":
        return value.strip().upper()
    return None


def _text(value: Any) -> Optional[str]:
    """Description de l'API : HTML léger (<br>, entités) → texte."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"<br\s*/?>|</p>", "\n", value, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text if len(text) > 20 else None


def _photos(ad: Dict) -> Optional[List[str]]:
    urls = []
    for photo in ad.get("photos") or []:
        url = photo.get("url") or photo.get("url_photo") if isinstance(photo, dict) else photo
        if isinstance(url, str) and url.startswith("http") and url not in urls:
            urls.append(url)
    return urls or None


def _publisher(ad: Dict) -> Optional[str]:
    if isinstance(ad.get("adCreatedByPro"), bool):
        return "agency" if ad["adCreatedByPro"] else "individual"
    kind = str(ad.get("accountType") or "").lower()
    if kind in ("agency", "professional", "pro"):
        return "agency"
    if kind in ("particulier", "particular", "private", "individual"):
        return "individual"
    return None


def _position(ad: Dict) -> Dict:
    """
    `blurInfo` : position affichée par le site. type « exact » = adresse du bien ;
    sinon (disque, commune…) le point est le centre d'une zone floutée → approximatif.
    """
    blur = ad.get("blurInfo") or {}
    point = blur.get("position") or blur.get("centroid") or ad.get("position") or {}
    if not isinstance(point, dict):
        return {}
    lat, lon = _number(point.get("lat")), _number(point.get("lon", point.get("lng")))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return {}
    exact = str(blur.get("type") or "").lower() == "exact"
    return {"lat": lat, "lon": lon, "geo_precision": "exact" if exact else "approx"}


def ad_url(ad: Dict) -> Optional[str]:
    """URL publique : /annonce/location/<commune>/<type>/<n>pieces/<id>."""
    ad_id = ad.get("id")
    if not ad_id:
        return None
    city, rooms = _slug(ad.get("city") or ""), _int(ad.get("roomsQuantity"))
    kind = _PROPERTY_SLUGS.get(str(ad.get("propertyType") or ""), "")
    if city and kind and rooms:
        return f"{BIENICI_BASE_URL}/annonce/location/{city}/{kind}/{rooms}pieces/{ad_id}"
    return f"{BIENICI_BASE_URL}/annonce/{ad_id}"


def _title(ad: Dict) -> str:
    if ad.get("title"):
        return str(ad["title"]).strip()
    kind = _PROPERTY_SLUGS.get(str(ad.get("propertyType") or ""), "logement").capitalize()
    parts = [kind]
    if ad.get("roomsQuantity"):
        parts.append(f"{_int(ad['roomsQuantity'])} pièces")
    if ad.get("surfaceArea"):
        parts.append(f"{_number(ad['surfaceArea']):g} m²")
    return " ".join(parts)


def _location_label(ad: Dict) -> str:
    district = (ad.get("district") or {}).get("name") if isinstance(ad.get("district"), dict) else None
    parts = [p for p in (ad.get("city"), ad.get("postalCode")) if p]
    label = " ".join(str(p) for p in parts)
    return f"{label} ({district})" if district and label else label


def parse_ad(ad: Dict) -> Optional[Listing]:
    """Annonce de l'API → Listing, ou None (pas d'identifiant ou pas de prix)."""
    url, price = ad_url(ad), _int(ad.get("price"))
    if not url or price is None:
        return None
    published = ad.get("publicationDate")
    floor = _int(ad.get("floor"))
    return Listing(
        site=SITE_NAME,
        url=url,
        title=_title(ad),
        price=price,
        location_raw=_location_label(ad),
        surface_m2=_number(ad.get("surfaceArea")),
        nb_rooms=_int(ad.get("roomsQuantity")),
        nb_bedrooms=_int(ad.get("bedroomsQuantity")),
        floor=floor,
        description=_text(ad.get("description")),
        charges=_int(ad.get("charges")),
        # Location : l'affichage du loyer charges comprises est obligatoire (loi ALUR) ;
        # « charges » est alors la part incluse. Un indicateur explicite de l'API prime.
        charges_included=next(
            (ad[k] for k in ("isPriceIncludingCharges", "priceIncludingCharges", "chargesIncluded")
             if isinstance(ad.get(k), bool)),
            True,
        ),
        deposit=_int(ad.get("safetyDeposit")),
        furnished=_bool(ad.get("isFurnished")),
        dpe_rating=_rating(ad.get("energyClassification")),
        ges_rating=_rating(ad.get("greenhouseGazClassification")),
        elevator=_bool(ad.get("hasElevator")),
        photos=_photos(ad),
        publisher_type=_publisher(ad),
        published_at=published[:10] if isinstance(published, str) and len(published) >= 10 else None,
        extra_attributes={k: ad[k] for k in _EXTRA_KEYS if ad.get(k) not in (None, "", [])} or None,
        source="api",
        authoritative=True,
        **_position(ad),
    )


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------

# Paramètres d'URL du site → filtres de l'API (extrait de la table du JS de bienici.com)
_URL_NUMBER_PARAMS = {
    "prix-min": "minPrice", "prix-max": "maxPrice",
    "surface-min": "minArea", "surface-max": "maxArea",
    "chambres-min": "minBedrooms", "chambres-max": "maxBedrooms",
}
_URL_FLAG_PARAMS = {
    "balcon": "hasBalcony", "terrasse": "hasTerrace", "balcon-ou-terrasse": "hasBalconyOrTerrace",
    "jardin": "hasGarden", "parking": "hasParking", "cave": "hasCellar", "ascenseur": "hasElevator",
    "piscine": "hasPool", "meuble": "isFurnished", "non-meuble": "isNotFurnished",
    "dernier-etage": "isOnLastFloor", "rez-de-chaussee": "isGroundFloor",
    "pas-au-rez-de-chaussee": "isNotGroundFloor", "colocation-autorisee": "flatSharing",
    "duplex": "isDuplex", "toilettes-separees": "hasSeparateToilet", "pmr": "isDisabledPeopleFriendly",
    "residence-etudiants": "isInStudentResidence", "pas-en-residence": "isNotInResidence",
    "photo": "hasPhoto",
}
_URL_SORTS = {
    "publication": "publicationDate", "modification": "modificationDate", "prix": "price",
    "prixm2": "pricePerSquareMeter", "surface": "surfaceArea", "pieces": "roomsQuantity",
    "pertinence": "relevance",
}
# Segment de type de bien de l'URL (/recherche/location/<lieux>/<types>) → types de l'API
_URL_PROPERTY_TYPES = {
    "appartement": "flat", "maisonvilla": "house", "loft": "loft", "chateau": "castle",
    "hotel-particulier": "townhouse", "batiment": "building",
}
# Types interrogés par le site quand l'URL n'en précise aucun
_DEFAULT_URL_PROPERTY_TYPES = ("flat", "house", "loft", "castle", "townhouse")


def parse_search_url(url: str) -> Tuple[List[Tuple[str, Optional[str]]], Dict[str, Any]]:
    """
    URL de recherche du site → ([(commune, code postal), …], filtres de l'API hors
    zones et pagination). Les paramètres inconnus (mode, carte, page…) sont ignorés.
    """
    parsed = urlparse(url)
    segments = [unquote(s) for s in parsed.path.split("/") if s]
    if len(segments) < 3 or segments[0] != "recherche":
        raise ValueError(f"URL Bien'ici inattendue : {url}")
    filter_type = {"location": "rent", "achat": "buy"}.get(segments[1])
    if not filter_type:
        raise ValueError(f"URL Bien'ici : type de transaction inconnu « {segments[1]} »")

    places: List[Tuple[str, Optional[str]]] = []
    for raw in segments[2].split(","):
        m = re.fullmatch(r"(.+?)-(\d{5})", raw.strip())
        name, postal = (m.group(1), m.group(2)) if m else (raw.strip(), None)
        if name:
            places.append((name.replace("-", " "), postal))

    types: List[str] = []
    if len(segments) > 3:
        for slug in segments[3].split(","):
            t = _URL_PROPERTY_TYPES.get(slug)
            if t and t not in types:
                types.append(t)

    filters: Dict[str, Any] = {
        "filterType": filter_type,
        "propertyType": types or list(_DEFAULT_URL_PROPERTY_TYPES),
        "sortBy": "publicationDate",
        "sortOrder": "desc",
    }
    query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    for key, value in query.items():
        if key in _URL_NUMBER_PARAMS:
            number = _number(value)
            if number is not None:
                filters[_URL_NUMBER_PARAMS[key]] = int(number) if number.is_integer() else number
        elif key in _URL_FLAG_PARAMS and value.lower() == "oui":
            filters[_URL_FLAG_PARAMS[key]] = True
    sort = query.get("tri")
    if sort:
        field, _, order = sort.partition("-")
        if field in _URL_SORTS:
            filters["sortBy"] = _URL_SORTS[field]
            filters["sortOrder"] = "asc" if order == "asc" else "desc"
    return places, filters


def page_size(profile: SearchProfile) -> int:
    return BIENICI_SITE_PAGE_SIZE if profile.bienici_search_url else BIENICI_PAGE_SIZE


def max_pages(profile: SearchProfile) -> int:
    if profile.bienici_max_pages:
        return profile.bienici_max_pages
    return MAX_PAGES_PER_SITE if profile.bienici_search_url else BIENICI_MAX_PAGES


def build_filters(profile: SearchProfile, zone_ids: List[str], page: int) -> Dict[str, Any]:
    """
    Filtres de recherche de l'API pour un profil : ceux de bienici_search_url s'il
    est fourni, sinon budget, pièces et types du profil.
    """
    size = page_size(profile)
    filters: Dict[str, Any] = {
        "size": size,
        "from": (page - 1) * size,
        "page": page,
        "showAllModels": False,
        "filterType": "rent",
        "propertyType": list(profile.bienici_property_types),
        "sortBy": "publicationDate",
        "sortOrder": "desc",
        "onTheMarket": [True],
        "zoneIdsByTypes": {"zoneIds": list(zone_ids)},
    }
    if profile.bienici_search_url:
        filters.update(parse_search_url(profile.bienici_search_url)[1])
        return filters
    if profile.min_rent_eur is not None:
        filters["minPrice"] = profile.min_rent_eur
    if profile.max_rent_eur is not None:
        filters["maxPrice"] = profile.max_rent_eur
    if profile.rooms:
        filters["minRooms"], filters["maxRooms"] = profile.rooms
    return filters


def _read_zone_cache(path: Path) -> Dict[str, List[str]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def pick_zone_ids(place: str, suggestions: Any, postal_code: Optional[str] = None) -> List[str]:
    """
    Identifiants de zone d'une commune parmi les suggestions de l'autocomplétion :
    la suggestion dont le nom (et le code postal, s'il est connu) correspond exactement,
    sinon celle dont le nom correspond, sinon la première.
    """
    if not isinstance(suggestions, list):
        return []
    candidates = [s for s in suggestions if isinstance(s, dict) and s.get("zoneIds")]
    wanted = normalize_place(place)
    named = [s for s in candidates if normalize_place(str(s.get("name") or "")) == wanted]
    if postal_code:
        for s in named:
            if postal_code in [str(c) for c in s.get("postalCodes") or []]:
                return [str(z) for z in s["zoneIds"]]
    if named:
        return [str(z) for z in named[0]["zoneIds"]]
    return [str(z) for z in candidates[0]["zoneIds"]] if candidates else []


class BienIciScraper(ApiScraper):
    """Recherche Bien'ici d'un profil, via l'API JSON du site."""

    def site_name(self) -> str:
        return SITE_NAME

    def search_url(self) -> Optional[str]:
        if self.profile.bienici_search_url:
            return self.profile.bienici_search_url
        if not (self.profile.bienici_zone_ids or self.profile.bienici_places):
            return None
        return BIENICI_SEARCH_API

    def headers(self) -> Dict[str, str]:
        return {**super().headers(), "Referer": f"{BIENICI_BASE_URL}/"}

    # --- Zones ---

    def zone_ids(self, cache_file: Path = BIENICI_ZONE_CACHE_FILE) -> List[str]:
        """
        Zones du profil : identifiants fournis, sinon communes de bienici_search_url,
        sinon bienici_places — résolues via l'autocomplétion (cache disque).
        """
        if self.profile.bienici_zone_ids:
            return list(self.profile.bienici_zone_ids)
        if self.profile.bienici_search_url:
            places = parse_search_url(self.profile.bienici_search_url)[0]
        else:
            places = [(p, None) for p in self.profile.bienici_places]
        cache = _read_zone_cache(cache_file)
        ids: List[str] = []
        changed = False
        for place, postal in places:
            key = normalize_place(f"{place} {postal}" if postal else place)
            if key not in cache:
                self.polite_delay(BIENICI_MIN_DELAY, BIENICI_MAX_DELAY)
                found = pick_zone_ids(
                    place, self.get_json(BIENICI_SUGGEST_API, {"q": place}, timeout=BIENICI_TIMEOUT),
                    postal_code=postal,
                )
                if not found:
                    self.logger.warning(f"Bien'ici : commune introuvable « {place} », ignorée")
                    continue
                cache[key], changed = found, True
            ids.extend(z for z in cache[key] if z not in ids)
        if changed:
            Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_file).write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
        return ids

    # --- Recherche ---

    def fetch_annonces(self) -> None:
        zones = self.zone_ids()
        if not zones:
            self.logger.error("Bien'ici : aucune zone de recherche résolue, recherche annulée")
            return
        seen = set()
        size = page_size(self.profile)
        for page in range(1, max_pages(self.profile) + 1):
            self.polite_delay(BIENICI_MIN_DELAY, BIENICI_MAX_DELAY)
            data = self.get_json(
                BIENICI_SEARCH_API,
                {"filters": json.dumps(build_filters(self.profile, zones, page), separators=(",", ":"))},
                timeout=BIENICI_TIMEOUT,
            )
            ads = data.get("realEstateAds") if isinstance(data, dict) else None
            if not isinstance(ads, list):
                raise ValueError("réponse sans « realEstateAds » (format de l'API modifié ?)")
            added = 0
            for ad in ads:
                try:
                    listing = parse_ad(ad) if isinstance(ad, dict) else None
                except Exception as e:  # une annonce inattendue ne fait pas perdre la page
                    self.logger.warning(f"Annonce Bien'ici illisible ({ad.get('id')}): {e}")
                    continue
                if listing and listing.url not in seen:
                    seen.add(listing.url)
                    self.results.append(listing.to_annonce())
                    added += 1
            total = data.get("total")
            self.logger.info(f"  Page {page} : {added} annonces (total annoncé : {total})")
            if len(ads) < size or (isinstance(total, int) and page * size >= total):
                break
