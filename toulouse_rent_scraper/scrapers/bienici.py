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
# Chaque annonce de l'API est complète (description, surface, DPE, photos, position) :
# elle est marquée enrichie d'emblée, sans visite de page.
# =========================

import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import (
    BIENICI_BASE_URL,
    BIENICI_MAX_DELAY,
    BIENICI_MAX_PAGES,
    BIENICI_MIN_DELAY,
    BIENICI_PAGE_SIZE,
    BIENICI_SEARCH_API,
    BIENICI_SUGGEST_API,
    BIENICI_TIMEOUT,
    BIENICI_ZONE_CACHE_FILE,
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

def build_filters(profile: SearchProfile, zone_ids: List[str], page: int) -> Dict[str, Any]:
    """Filtres de recherche de l'API pour un profil (budget, pièces, types, zones)."""
    filters: Dict[str, Any] = {
        "size": BIENICI_PAGE_SIZE,
        "from": (page - 1) * BIENICI_PAGE_SIZE,
        "page": page,
        "showAllModels": False,
        "filterType": "rent",
        "propertyType": list(profile.bienici_property_types),
        "sortBy": "publicationDate",
        "sortOrder": "desc",
        "onTheMarket": [True],
        "zoneIdsByTypes": {"zoneIds": list(zone_ids)},
    }
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


def pick_zone_ids(place: str, suggestions: Any) -> List[str]:
    """
    Identifiants de zone d'une commune parmi les suggestions de l'autocomplétion :
    la suggestion dont le nom correspond exactement, sinon la première.
    """
    if not isinstance(suggestions, list):
        return []
    candidates = [s for s in suggestions if isinstance(s, dict) and s.get("zoneIds")]
    wanted = normalize_place(place)
    for s in candidates:
        if normalize_place(str(s.get("name") or "")) == wanted:
            return [str(z) for z in s["zoneIds"]]
    return [str(z) for z in candidates[0]["zoneIds"]] if candidates else []


class BienIciScraper(ApiScraper):
    """Recherche Bien'ici d'un profil, via l'API JSON du site."""

    def site_name(self) -> str:
        return SITE_NAME

    def search_url(self) -> Optional[str]:
        if not (self.profile.bienici_zone_ids or self.profile.bienici_places):
            return None
        return BIENICI_SEARCH_API

    def headers(self) -> Dict[str, str]:
        return {**super().headers(), "Referer": f"{BIENICI_BASE_URL}/"}

    # --- Zones ---

    def zone_ids(self, cache_file: Path = BIENICI_ZONE_CACHE_FILE) -> List[str]:
        """Zones du profil : identifiants fournis, sinon communes résolues (cache disque)."""
        if self.profile.bienici_zone_ids:
            return list(self.profile.bienici_zone_ids)
        cache = _read_zone_cache(cache_file)
        ids: List[str] = []
        changed = False
        for place in self.profile.bienici_places:
            key = normalize_place(place)
            if key not in cache:
                self.polite_delay(BIENICI_MIN_DELAY, BIENICI_MAX_DELAY)
                found = pick_zone_ids(
                    place, self.get_json(BIENICI_SUGGEST_API, {"q": place}, timeout=BIENICI_TIMEOUT)
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
        for page in range(1, BIENICI_MAX_PAGES + 1):
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
            if len(ads) < BIENICI_PAGE_SIZE or (isinstance(total, int) and page * BIENICI_PAGE_SIZE >= total):
                break
