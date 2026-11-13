# filters/price_and_distance.py
# =========================
# Filtres métier : prix + distance ENAC
# =========================

import re
from typing import Dict, List, Optional, Tuple

from config import (
    MAX_RENT_EUR, MIN_RENT_EUR, MAX_DISTANCE_KM,
    ENAC_LATITUDE, ENAC_LONGITUDE, SearchProfile, enabled_profiles,
)
from geo.distance import distance_from_enac_km, geocode_address, distance_km


# Séparateur de milliers : espace (normale, insécable, fine) ou point,
# entre un chiffre et un groupe d'exactement 3 chiffres ("1 200", "1.050")
_THOUSANDS_SEP = re.compile(r"(?<=\d)[   .](?=\d{3}(?!\d))")


def parse_price(price_raw) -> Optional[int]:
    """
    Nettoie un prix brut et retourne un entier en euros.
    Exemples :
        "430€" -> 430
        "430 € cc" -> 430
        "1 200 €" -> 1200
        "450,50 €" -> 450
        480 -> 480
        None -> None
    """
    if price_raw is None or isinstance(price_raw, bool):
        return None
    if isinstance(price_raw, (int, float)):
        return int(price_raw)
    if not price_raw:
        return None

    cleaned = _THOUSANDS_SEP.sub("", price_raw)

    # Premier nombre entier (les décimales après la virgule sont ignorées)
    match = re.search(r"\d+", cleaned)
    if match:
        return int(match.group())

    return None


def apply_price_and_distance_filter(annonce: Dict) -> Optional[Dict]:
    """
    Applique les filtres :
    - loyer <= MAX_RENT_EUR
    - distance ENAC <= MAX_DISTANCE_KM

    Retourne l'annonce enrichie ou None si rejetée.
    """

    # ---- PRIX ----
    price = parse_price(annonce.get("price"))
    if price is None or price < MIN_RENT_EUR or price > MAX_RENT_EUR:
        return None

    # ---- LOCALISATION ----
    location_raw = annonce.get("location_raw")
    if not location_raw:
        return None

    distance_km = distance_from_enac_km(location_raw)
    if distance_km is None or distance_km > MAX_DISTANCE_KM:
        return None

    # ---- ENRICHISSEMENT ----
    annonce_enriched = annonce.copy()
    annonce_enriched["price"] = price
    annonce_enriched["distance_enac_km"] = distance_km

    return annonce_enriched


# =========================
# Multi-profils (Sprint 14)
# =========================

_ROOMS_PATTERNS = [
    re.compile(r"\bT(\d)\b", re.IGNORECASE),
    re.compile(r"\bF(\d)\b"),
    re.compile(r"(\d)\s*pi[eè]ces?", re.IGNORECASE),
]


def guess_rooms(annonce: Dict) -> Optional[int]:
    """Nombre de pièces : donnée enrichie si dispo, sinon déduit du titre. None si inconnu."""
    if annonce.get("nb_rooms"):
        return int(annonce["nb_rooms"])
    title = annonce.get("title") or ""
    if re.search(r"\bstudio\b", title, re.IGNORECASE):
        return 1
    for pattern in _ROOMS_PATTERNS:
        match = pattern.search(title)
        if match:
            return int(match.group(1))
    return None


def _price_ok(price: int, profile: SearchProfile) -> bool:
    if profile.min_rent_eur is not None and price < profile.min_rent_eur:
        return False
    if profile.max_rent_eur is not None and price > profile.max_rent_eur:
        return False
    return True


def _rooms_ok(rooms: Optional[int], profile: SearchProfile) -> bool:
    # Pièces inconnues : on garde (mieux vaut un faux positif qu'une annonce ratée)
    if profile.rooms is None or rooms is None:
        return True
    return profile.rooms[0] <= rooms <= profile.rooms[1]


def match_profiles(
    annonce: Dict,
    profiles: Optional[List[SearchProfile]] = None,
    known_coords: Optional[Tuple[float, float]] = None,
) -> Tuple[Optional[Dict], List[Tuple[SearchProfile, float]]]:
    """
    Teste une annonce brute contre chaque profil (budget, pièces, rayon).

    Retourne (annonce_enrichie, [(profil, distance_km), ...]).
    L'annonce enrichie (prix entier, lat/lon, distance_enac_km) vaut None si aucun profil ne matche.
    Le géocodage n'est fait que si au moins un profil accepte le prix et les pièces.
    `known_coords` (point exact déjà connu, ex. GPS de l'annonce LBC) remplace le géocodage.
    """
    profiles = profiles if profiles is not None else enabled_profiles()

    price = parse_price(annonce.get("price"))
    location_raw = annonce.get("location_raw")
    if price is None or not location_raw:
        return None, []

    rooms = guess_rooms(annonce)
    candidates = [
        p for p in profiles
        if _price_ok(price, p) and _rooms_ok(rooms, p)
    ]
    if not candidates:
        return None, []

    coords = known_coords or geocode_address(location_raw)
    if not coords and annonce.get("lat") is not None and annonce.get("lon") is not None:
        # Adresse introuvable : position approximative fournie par le site (JSON LBC, 15.2)
        coords = (annonce["lat"], annonce["lon"])
    if not coords:
        return None, []

    matches = []
    for profile in candidates:
        dist = distance_km(coords, profile.target)
        if dist <= profile.max_distance_km:
            matches.append((profile, dist))
    if not matches:
        return None, []

    enriched = annonce.copy()
    enriched["price"] = price
    enriched["lat"], enriched["lon"] = coords
    enriched["distance_enac_km"] = distance_km(coords, (ENAC_LATITUDE, ENAC_LONGITUDE))
    return enriched, matches
