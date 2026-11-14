# scrapers/detail_extractors/pap_html.py
# =========================
# PAP.fr (Sprint 4) — lecture du HTML rendu par le serveur, sans navigateur (testable).
#
# Recherche : cartes `div.search-list-item-alt` ; défilement infini qui ajoute les pages
#   …-g19307g43612-2, -3… dans la même page. Chaque carte :
#     a.item-title[href="/annonces/appartement-blagnac-31700-r466100091"]
#     span.item-price « 1.080 € » (loyer charges comprises), span.h1 « Blagnac (31700) »,
#     ul.item-tags « 2 pièces · 1 chambre · 49 m² », div.item-thumb-dpe-b, photos du carrousel,
#     p.item-description (résumé tronqué).
#   La recherche mélange bureaux, locaux, garages, colocations : seuls les types de
#   LIVING_TYPES (début du chemin de l'annonce) sont gardés.
#
# Fiche : JSON-LD `Product` (surface, pièces, type, meublé, balcon, photos, description,
#   rue + commune) ; HTML : « Dont charges », « Dépôt de garantie », DPE / GES (`li.active`),
#   chambres ; position GPS du plan : data-thunderforest="{"center":["43.63","1.38"]}".
#
# Repérage du 2026-11-14 : docs/pap_selectors.md
# =========================

import html as html_lib
import json
import re
from typing import Any, Dict, List, Optional

from scrapers.listing import Listing

SITE_NAME = "PAP"
BASE_URL = "https://www.pap.fr"

# Types de bien conservés (début du chemin /annonces/<type>-…) ; le reste
# (bureaux, local-commercial, garage-parking, colocation, terrain…) est écarté
LIVING_TYPES = ("appartement", "maison", "studio", "loft", "duplex", "villa")

_ID_RE = re.compile(r"-r(\d{6,})(?:[/?#]|$)")
_CARD_SPLIT = 'class="search-list-item-alt"'
_TAG_RE = re.compile(r"<[^>]+>")


def _text(fragment: Optional[str]) -> str:
    """HTML → texte sur une ligne (entités décodées, espaces insécables normalisés)."""
    if not fragment:
        return ""
    text = html_lib.unescape(_TAG_RE.sub(" ", fragment))
    return re.sub(r"\s+", " ", text.replace("\xa0", " ").replace(" ", " ")).strip()


def _int(text: Optional[str]) -> Optional[int]:
    """« 1.080 € » → 1080 ; « 620 € » → 620."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text.split(",")[0])
    return int(digits) if digits else None


def _float(text: Optional[str]) -> Optional[float]:
    """« 35,21 m² » → 35.21 ; « 49.00 » → 49.0."""
    if text is None:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", str(text).replace("\xa0", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def annonce_id(url: Optional[str]) -> Optional[str]:
    """Identifiant PAP (« 466100091 ») à partir de l'URL de l'annonce."""
    if not url:
        return None
    m = _ID_RE.search(url)
    return m.group(1) if m else None


def canonical_url(url: str) -> str:
    """URL absolue sans paramètres ni ancre."""
    if url.startswith("/"):
        url = BASE_URL + url
    return url.split("#")[0].split("?")[0]


def property_type(url: Optional[str]) -> Optional[str]:
    """« /annonces/appartement-blagnac-31700-r466100091 » → « appartement »."""
    m = re.search(r"/annonces/([a-z]+)", url or "")
    return m.group(1) if m else None


def is_living(url: Optional[str]) -> bool:
    return property_type(url) in LIVING_TYPES


def _tags(fragment: str) -> Dict[str, Any]:
    """ul.item-tags → pièces, chambres, surface."""
    out: Dict[str, Any] = {}
    for li in re.findall(r"<li[^>]*>(.*?)</li>", fragment, re.S):
        t = _text(li).lower()
        if "pièce" in t:
            out["nb_rooms"] = _int(t)
        elif "chambre" in t and "colocation" not in t:
            out["nb_bedrooms"] = _int(t)
        elif "m²" in t or "m2" in t:
            out["surface_m2"] = _float(t)
    return out


def _photos(fragment: str) -> List[str]:
    """Photos du carrousel, sans les doublons des diapositives « cloned »."""
    seen: List[str] = []
    for src in re.findall(r'<img[^>]+src="(https://cdn\.pap\.fr/photos/[^"]+)"', fragment):
        if src not in seen:
            seen.append(src)
    return seen


def parse_card(fragment: str) -> Optional[Listing]:
    """Une carte de résultat → Listing (None si ce n'est pas un logement ou si illisible)."""
    m = re.search(r'<a class="item-title"[^>]*href="([^"]+)"', fragment)
    if not m:
        return None
    url = canonical_url(html_lib.unescape(m.group(1)))
    if not is_living(url) or not annonce_id(url):
        return None

    price_m = re.search(r'<span class="item-price[^"]*">(.*?)</span>', fragment, re.S)
    loc_m = re.search(r'<span class="h1">(.*?)</span>', fragment, re.S)
    tags_m = re.search(r'<ul class="item-tags[^"]*">(.*?)</ul>', fragment, re.S)
    dpe_m = re.search(r"item-thumb-dpe-([a-g])\b", fragment)

    location = _text(loc_m.group(1)) if loc_m else ""
    tags = _tags(tags_m.group(1)) if tags_m else {}
    price = _int(_text(price_m.group(1))) if price_m else None
    if price is None:
        return None

    kind = property_type(url) or "logement"
    title_bits = [kind.capitalize()]
    if tags.get("nb_rooms"):
        title_bits.append(f"{tags['nb_rooms']} pièce{'s' if tags['nb_rooms'] > 1 else ''}")
    if tags.get("surface_m2"):
        title_bits.append(f"{tags['surface_m2']:g} m²")
    if location:
        title_bits.append(location)

    return Listing(
        site=SITE_NAME,
        url=url,
        title=" ".join(title_bits),
        price=price,
        location_raw=location,
        surface_m2=tags.get("surface_m2"),
        nb_rooms=tags.get("nb_rooms"),
        nb_bedrooms=tags.get("nb_bedrooms"),
        # Prix affiché = loyer charges comprises (vérifié sur les fiches)
        charges_included=True,
        dpe_rating=dpe_m.group(1).upper() if dpe_m else None,
        photos=_photos(fragment) or None,
        publisher_type="individual",
        source="html",
        extra_attributes={"property_type": kind, "pap_id": annonce_id(url)},
    )


def search_listings(page_html: str) -> List[Listing]:
    """Toutes les cartes logement de la page (pages ajoutées par le défilement comprises), sans doublon."""
    listings: List[Listing] = []
    seen = set()
    for fragment in page_html.split(_CARD_SPLIT)[1:]:
        listing = parse_card(fragment)
        if listing and listing.url not in seen:
            seen.add(listing.url)
            listings.append(listing)
    return listings


def search_total(page_html: str) -> Optional[int]:
    """Nombre total d'annonces annoncé par le site (`annonces_total` de data-infinite-scroll)."""
    m = re.search(r'data-infinite-scroll="([^"]+)"', page_html)
    if not m:
        return None
    try:
        return int(json.loads(html_lib.unescape(m.group(1)))["piano"]["annonces_total"])
    except (ValueError, KeyError, TypeError):
        return None


def count_cards(page_html: str) -> int:
    """Nombre de cartes (tous types) présentes dans la page."""
    return len(set(re.findall(r'<a class="item-title"[^>]*href="([^"]+)"', page_html)))


# ---------------------------------------------------------------------------
# Fiche détaillée
# ---------------------------------------------------------------------------

def _product_jsonld(page_html: str) -> Optional[Dict[str, Any]]:
    for raw in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html, re.S):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return None


def _property(product: Dict[str, Any], name: str) -> Any:
    for prop in product.get("additionalProperty") or []:
        if isinstance(prop, dict) and (prop.get("name") or "").lower() == name.lower():
            return prop.get("value")
    return None


def _yes_no(value: Any) -> Optional[bool]:
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in ("oui", "yes", "true", "1"):
        return True
    if v in ("non", "no", "false", "0"):
        return False
    return None


def _financial(page_html: str, label: str) -> Optional[int]:
    """« <b>Dont charges</b><br>60 € / mois » → 60."""
    m = re.search(r"<b>\s*" + re.escape(label) + r"\s*</b>(.*?)</div>", page_html, re.S | re.I)
    return _int(_text(m.group(1))) if m else None


def _energy(page_html: str, block: str) -> Optional[str]:
    m = re.search(r'class="' + block + r'".*?<li class="active">\s*([A-G])\s*</li>', page_html, re.S)
    return m.group(1) if m else None


def _gps(page_html: str) -> Optional[Dict[str, float]]:
    m = re.search(r'data-thunderforest="([^"]+)"', page_html)
    if not m:
        return None
    try:
        center = json.loads(html_lib.unescape(m.group(1))).get("center") or []
        lat, lon = float(center[0]), float(center[1])
    except (ValueError, TypeError, IndexError, AttributeError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"lat": lat, "lon": lon}


def parse_detail(page_html: str) -> Optional[Dict[str, Any]]:
    """
    Fiche PAP → champs d'enrichissement (noms des colonnes de `annonces`).
    None si la page n'a pas le JSON-LD `Product` (annonce retirée, page inattendue).
    """
    product = _product_jsonld(page_html)
    if not product:
        return None

    offers = product.get("offers") or {}
    address = product.get("address") or {}
    description = html_lib.unescape(product.get("description") or "").strip() or None
    photos = [p for p in (product.get("image") or []) if isinstance(p, str)]
    if not photos:
        photos = _photos(page_html)

    tags_m = re.search(r'<ul class="item-tags[^"]*">(.*?)</ul>', page_html, re.S)
    tags = _tags(tags_m.group(1)) if tags_m else {}

    surface = _float(_property(product, "Surface")) or tags.get("surface_m2")
    rooms = _property(product, "Nombre de pièces")
    rooms = int(rooms) if isinstance(rooms, (int, float)) or (isinstance(rooms, str) and rooms.isdigit()) \
        else tags.get("nb_rooms")

    cc_rent = _financial(page_html, "Loyer charges comprises")
    price = cc_rent or _int(str(offers.get("price") or ""))

    floor = None
    if description:
        if re.search(r"\b(rdc|rez[- ]de[- ]chauss[ée]e)\b", description, re.I):
            floor = 0
        else:
            fm = re.search(r"\b(\d{1,2})\s*(?:er|e|ème|eme)\s+étage", description, re.I)
            floor = int(fm.group(1)) if fm else None

    street = (address.get("streetAddress") or "").strip()
    result: Dict[str, Any] = {
        "surface_m2": surface,
        "nb_rooms": rooms,
        "nb_bedrooms": tags.get("nb_bedrooms"),
        "floor": floor,
        "description": description,
        "charges": _financial(page_html, "Dont charges"),
        "charges_included": True if cc_rent else None,
        "deposit": _financial(page_html, "Dépôt de garantie"),
        "furnished": _yes_no(_property(product, "Meublé")),
        "dpe_rating": _energy(page_html, "energy-indice"),
        "ges_rating": _energy(page_html, "ges-indice"),
        "photos": photos or None,
        "publisher_type": "individual",
        "detail_price": price,
        "extra_attributes": {
            "property_type": _property(product, "Type de bien"),
            "balcony_or_terrace": _yes_no(_property(product, "Balcon / Terrasse")),
            "street": street or None,
            "city": address.get("addressLocality"),
            "postal_code": address.get("postalCode"),
            "pap_ref": (product.get("sku") or "").replace("location-", "") or None,
        },
    }
    gps = _gps(page_html)
    if gps:
        # Le plan est centré sur l'adresse saisie : exact si une rue est donnée, sinon la commune
        result.update(gps, geo_precision="exact" if street else "approx")
    return result
