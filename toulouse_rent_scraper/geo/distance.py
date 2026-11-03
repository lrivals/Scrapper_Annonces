# geo/distance.py
# =========================
# Géolocalisation et calcul de distance
# =========================

import re
import time
from datetime import datetime, timedelta
from typing import List, Optional

from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

from config import (
    ENAC_LATITUDE,
    ENAC_LONGITUDE,
    KNOWN_COMMUNES,
    GEOCODE_VIEWBOX,
    GEOCODE_NEGATIVE_TTL_DAYS,
)
import storage.sqlite
from storage.sqlite import get_connection
from utils.logger import setup_logger
from utils.retry import retry_with_backoff

# Initialisation du géocodeur
geolocator = Nominatim(user_agent="toulouse_rent_scraper")

# Logger
logger = setup_logger('geo')

# Mentions fréquentes dans les localisations d'annonces, inconnues de Nominatim
_NOISE_PATTERNS = [
    r"\bcentre[- ]ville\b",
    r"\bproche\b.*$",
    r"\bsecteur\b",
    r"\bquartier\b",
]

_cache_table_ready_for = None  # chemin de la base pour laquelle la table existe


def _ensure_cache_table():
    """Crée la table de cache si besoin (une seule fois par base et par processus)."""
    global _cache_table_ready_for
    if _cache_table_ready_for == storage.sqlite.DB_PATH:
        return
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS geocoding_cache (
                address TEXT PRIMARY KEY,
                latitude REAL,
                longitude REAL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()
    _cache_table_ready_for = storage.sqlite.DB_PATH


def _mentions_commune(address: str) -> bool:
    lowered = address.lower()
    if re.search(r"\b\d{5}\b", address):
        return True
    return any(commune.lower() in lowered for commune in KNOWN_COMMUNES)


def build_queries(address: str) -> List[str]:
    """
    Requêtes Nominatim à essayer, de la plus précise à la plus large :
      1. l'adresse brute (+ « Toulouse » si aucune commune / code postal n'est cité)
      2. l'adresse débarrassée des mentions non géocodables (« Centre-ville », « proche … »)
      3. le code postal seul
    """
    address = " ".join(address.split())
    suffix = ", France" if _mentions_commune(address) else ", Toulouse, France"
    queries = [address + suffix]

    cleaned = address
    for pattern in _NOISE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.replace(" ,", ",").split()).strip(" ,-")
    if cleaned and cleaned != address:
        queries.append(cleaned + suffix)

    postcode = re.search(r"\b(\d{5})\b", address)
    if postcode:
        queries.append(f"{postcode.group(1)}, France")

    # Dédoublonnage en conservant l'ordre
    return list(dict.fromkeys(queries))


@retry_with_backoff(max_attempts=3, base_delay=2.0, exceptions=(GeocoderTimedOut, GeocoderUnavailable))
def _nominatim(query: str):
    try:
        return geolocator.geocode(
            query,
            timeout=10,
            viewbox=GEOCODE_VIEWBOX,
            bounded=True,
            country_codes="fr",
        )
    finally:
        # Respecter le rate limit Nominatim : 1 req/s selon les ToS
        time.sleep(1.0)


def _read_cache(address: str):
    """
    Retourne (hit, coords) :
      (True, (lat, lon))  — adresse connue
      (True, None)        — échec récent mis en cache (cache négatif)
      (False, None)       — rien en cache, ou échec expiré
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT latitude, longitude, cached_at FROM geocoding_cache WHERE address = ?",
            (address,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return False, None
    lat, lon, cached_at = row
    if lat is not None and lon is not None:
        return True, (lat, lon)

    try:
        cached = datetime.fromisoformat(str(cached_at))
    except (TypeError, ValueError):
        return False, None
    if datetime.now() - cached < timedelta(days=GEOCODE_NEGATIVE_TTL_DAYS):
        return True, None
    return False, None


def _write_cache(address: str, coords: Optional[tuple]):
    lat, lon = coords if coords else (None, None)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO geocoding_cache (address, latitude, longitude, cached_at) "
            "VALUES (?, ?, ?, ?)",
            (address, lat, lon, datetime.now().isoformat(sep=" ", timespec="seconds"))
        )
        conn.commit()
    finally:
        conn.close()


def geocode_address(address: str) -> Optional[tuple]:
    """
    Convertit une adresse ou un quartier en coordonnées GPS.

    Retourne (latitude, longitude) ou None si échec.
    Utilise un cache persistant SQLite (succès ET échecs) pour éviter
    les appels répétés à Nominatim.
    """
    if not address or not address.strip():
        return None

    _ensure_cache_table()

    # 1. Vérifier le cache persistant
    hit, coords = _read_cache(address)
    if hit:
        logger.debug(f"Cache {'hit' if coords else 'négatif'} géocodage : {address}")
        return coords

    # 2. Appeler Nominatim, de la requête la plus précise à la plus large
    try:
        for query in build_queries(address):
            logger.debug(f"Géocodage de : {query}")
            location = _nominatim(query)
            if location:
                coords = (location.latitude, location.longitude)
                logger.debug(f"Coordonnées trouvées : {coords} (requête : {query})")
                _write_cache(address, coords)
                return coords
    except Exception as e:
        # Erreur réseau / service : transitoire, on ne met PAS en cache négatif
        logger.error(f"  ❌ Erreur géocodage pour '{address}' : {e}")
        return None

    logger.warning(f"Aucune coordonnée trouvée pour : {address}")
    _write_cache(address, None)
    return None


def distance_km(coords: tuple, target: tuple) -> float:
    """Distance à vol d'oiseau (km, 2 décimales) entre deux points (lat, lon)."""
    return round(geodesic(target, coords).km, 2)


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
