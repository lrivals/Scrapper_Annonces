# geo/distance.py
# =========================
# Géolocalisation et calcul de distance
# =========================

from functools import lru_cache
from typing import Optional

from geopy.geocoders import Nominatim
from geopy.distance import geodesic

from config import (
    ENAC_LATITUDE,
    ENAC_LONGITUDE
)
from utils.logger import setup_logger

# Initialisation du géocodeur
geolocator = Nominatim(user_agent="toulouse_rent_scraper")

# Logger
logger = setup_logger('geo')


@lru_cache(maxsize=512)
def geocode_address(address: str) -> Optional[tuple]:
    """
    Convertit une adresse ou un quartier en coordonnées GPS.

    Retourne (latitude, longitude) ou None si échec.
    Le cache évite de refaire les mêmes requêtes.
    """
    if not address:
        return None

    try:
        full_address = f"{address}, Toulouse, France"
        logger.debug(f"Géocodage de : {full_address}")
        
        location = geolocator.geocode(
            full_address,
            timeout=10
        )
        
        if location:
            coords = (location.latitude, location.longitude)
            logger.debug(f"  ✅ Coordonnées trouvées : {coords}")
            return coords
        else:
            logger.warning(f"  ⚠️  Aucune coordonnée trouvée pour : {address}")
            return None
            
    except Exception as e:
        logger.error(f"  ❌ Erreur géocodage pour '{address}' : {e}")
        return None


def distance_from_enac_km(address_or_district: str) -> Optional[float]:
    """
    Calcule la distance en kilomètres entre l'ENAC
    et une adresse/quartier donné.
    """
    coords = geocode_address(address_or_district)
    if not coords:
        logger.debug(f"Impossible de calculer la distance pour : {address_or_district}")
        return None

    enac_coords = (ENAC_LATITUDE, ENAC_LONGITUDE)

    try:
        distance = round(geodesic(enac_coords, coords).km, 2)
        logger.debug(f"Distance ENAC ↔ {address_or_district} : {distance} km")
        return distance
    except Exception as e:
        logger.error(f"Erreur calcul distance pour '{address_or_district}' : {e}")
        return None
