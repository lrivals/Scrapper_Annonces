# filters/price_and_distance.py
# =========================
# Filtres métier : prix + distance ENAC
# =========================

import re
from typing import Dict, Optional

from config import MAX_RENT_EUR, MIN_RENT_EUR, MAX_DISTANCE_KM
from geo.distance import distance_from_enac_km


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
