# config.py
# =========================
# Configuration globale du projet
# =========================

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

# =========================
# 📍 LOCALISATION DE RÉFÉRENCE
# =========================

ENAC_ADDRESS = "7 Avenue Édouard Belin, 31400 Toulouse"

# Coordonnées GPS approximatives de l'ENAC
# (évite un géocodage inutile à chaque run)
ENAC_LATITUDE = 43.5643
ENAC_LONGITUDE = 1.4800

# Rayon maximal autour de l'ENAC (en kilomètres)
MAX_DISTANCE_KM = 10


# =========================
# 💰 CRITÈRES DE RECHERCHE
# =========================

MAX_RENT_EUR = 500
MIN_RENT_EUR = 50

# =========================
# 🗺️ GÉOCODAGE
# =========================

# Communes de l'agglomération : si l'une apparaît dans l'adresse, on n'ajoute
# pas « Toulouse » à la requête Nominatim (sinon « Ramonville …, Toulouse » échoue)
KNOWN_COMMUNES = [
    "Toulouse", "Ramonville", "Labège", "Labege", "Castanet", "Balma", "L'Union",
    "Blagnac", "Beauzelle", "Cornebarrieu", "Aussonne", "Colomiers", "Tournefeuille",
    "Cugnaux", "Portet", "Muret", "Saint-Orens", "Quint-Fonsegrives", "Auzeville",
    "Escalquens", "Pechbonnieu", "Launaguet", "Seilh", "Mondonville", "Plaisance-du-Touch",
]

# Zone de recherche Nominatim (évite les homonymes ailleurs en France) :
# ((lat_sud, lon_ouest), (lat_nord, lon_est)) — agglomération toulousaine élargie
GEOCODE_VIEWBOX = ((43.35, 1.10), (43.85, 1.75))

# Une adresse non trouvée n'est pas re-demandée à Nominatim pendant ce délai
GEOCODE_NEGATIVE_TTL_DAYS = 30


# =========================
# 🌐 SELOGER
# =========================

SELOGER_BASE_URL = "https://www.seloger.com"

# URL de recherche avec filtres pré-appliqués (pages 1 à 3).
# Budget injecté depuis MAX_RENT_EUR ; particuliers ET professionnels.
# ⚠️ `estateSubTypes` : valeurs T1/T2 à capturer depuis le site avant de les ajouter.
_SELOGER_LOCATIONS = (
    "eyJwbGFjZUlkIjoiQUQwOEZSMTI1MzUiLCJyYWRpdXMiOjEwLCJwb2x5bGluZSI6In1obGlH"
    "cV9fSHhJanZDfl5wcEN8ckBgZUN6ZEFsdEJkdEFoX0JiYEJuZkFqaEJ6akBwbEJ0TW5sQmNO"
    "aGhCaWtAfl9CdWZBfnNBa19CdGRBa3RCeHJAeWRDfF5lcEN2SX11Q3dJfXVDfV5jcEN5ckB5"
    "ZEN1ZEFrdEJfdEFtX0JfYEJ1ZkFpaEJpa0BvbEJhTnFsQnJNa2hCfGpAY2BCbGZBZXRBaF9C"
    "e2RBbnRCfXJAYGVDX19AbnBDeUlqdkMiLCJjb29yZGluYXRlcyI6eyJsYXQiOjQzLjU1OTc1"
    "ODY0ODI4NDgsImxuZyI6MS40NzQ2NDgyNzM1OTg0MzN9fQ"
)

SELOGER_PAGES = 3


def build_seloger_search_url(locations: str, max_rent: int, sub_types: str = "Studio") -> str:
    return (
        "https://www.seloger.com/classified-search"
        "?distributionTypes=Rent"
        f"&estateSubTypes={sub_types}"
        "&estateTypes=Apartment"
        f"&locations={locations}"
        f"&priceMax={max_rent}"
        "&order=PriceAsc"
    )


SELOGER_SEARCH_URL = build_seloger_search_url(_SELOGER_LOCATIONS, MAX_RENT_EUR)

SELOGER_SEARCH_URLS = [SELOGER_SEARCH_URL] + [
    f"{SELOGER_SEARCH_URL}&page={n}" for n in range(2, SELOGER_PAGES + 1)
]


# =========================
# 🌐 LEBONCOIN
# =========================

LEBONCOIN_BASE_URL = "https://www.leboncoin.fr"

# URL finale avec tous les filtres — budget dérivé de MIN/MAX_RENT_EUR,
# plus récentes d'abord (les nouveautés passent avant la limite de pages)
_LEBONCOIN_LOCATION_TOULOUSE = "Toulouse__43.599373754597394_1.435619856703149_9864_10000"


def build_leboncoin_search_url(
    location: str, min_rent: int, max_rent: int, rooms: Optional[Tuple[int, int]] = None
) -> str:
    url = (
        "https://www.leboncoin.fr/recherche"
        "?category=10"
        f"&locations={location}"
        f"&price={min_rent}-{max_rent}"
        "&real_estate_type=2"
    )
    if rooms:
        url += f"&rooms={rooms[0]}-{rooms[1]}"
    return url + "&sort=time&order=desc"


LEBONCOIN_SEARCH_URL = build_leboncoin_search_url(
    _LEBONCOIN_LOCATION_TOULOUSE, MIN_RENT_EUR, MAX_RENT_EUR
)

# =========================
# 🎯 PROFILS DE RECHERCHE (Sprint 14)
# =========================

@dataclass(frozen=True)
class SearchProfile:
    """Un cas d'usage : une cible, un budget, un rayon, et les recherches associées."""
    key: str
    label: str                                  # affiché dans l'UI / les rapports
    target_address: str
    target_lat: float
    target_lon: float
    max_distance_km: float
    min_rent_eur: int
    max_rent_eur: int
    rooms: Optional[Tuple[int, int]] = None     # (min, max) pièces ; None = pas de contrainte
    lbc_location: Optional[str] = None          # paramètre `locations` LeBonCoin
    seloger_locations: Optional[str] = None     # paramètre `locations` SeLoger (base64, à capturer)
    seloger_sub_types: str = "Studio"
    enabled: bool = True

    @property
    def target(self) -> Tuple[float, float]:
        return (self.target_lat, self.target_lon)

    def leboncoin_search_url(self) -> Optional[str]:
        if not self.lbc_location:
            return None
        return build_leboncoin_search_url(
            self.lbc_location, self.min_rent_eur, self.max_rent_eur, self.rooms
        )

    def seloger_search_urls(self):
        if not self.seloger_locations:
            return []
        first = build_seloger_search_url(
            self.seloger_locations, self.max_rent_eur, self.seloger_sub_types
        )
        return [first] + [f"{first}&page={n}" for n in range(2, SELOGER_PAGES + 1)]


SEARCH_PROFILES: Dict[str, SearchProfile] = {
    "enac": SearchProfile(
        key="enac",
        label="ENAC",
        target_address=ENAC_ADDRESS,
        target_lat=ENAC_LATITUDE,
        target_lon=ENAC_LONGITUDE,
        max_distance_km=MAX_DISTANCE_KM,
        min_rent_eur=MIN_RENT_EUR,
        max_rent_eur=MAX_RENT_EUR,
        lbc_location=_LEBONCOIN_LOCATION_TOULOUSE,
        seloger_locations=_SELOGER_LOCATIONS,
    ),
    "blagnac": SearchProfile(
        key="blagnac",
        label="Blagnac — Pl. Marcel Dassault",
        target_address="14 Place Marcel Dassault, 31700 Blagnac",
        # Géocodé via Nominatim le 2026-11-03 (bâtiment ARCYS, quartier Font-Grasse)
        target_lat=43.6417,
        target_lon=1.3693,
        max_distance_km=8,
        min_rent_eur=550,
        max_rent_eur=750,
        rooms=(1, 3),
        # Format LBC : Ville_CP__lat_lon_rayonDefaut_rayon(m) — à vérifier au premier run
        lbc_location="Blagnac_31700__43.6417_1.3693_5000_8000",
        # ⚠️ À capturer sur seloger.com (Blagnac, rayon 8 km, T1–T3, 750 € max) :
        # tant que c'est None, SeLoger est ignoré pour ce profil.
        seloger_locations=None,
    ),
}

DEFAULT_PROFILE = "enac"


def enabled_profiles():
    return [p for p in SEARCH_PROFILES.values() if p.enabled]


# Pause entre deux recherches d'un même run (changement de profil/site), en secondes
PROFILE_SWITCH_MIN_DELAY = 60
PROFILE_SWITCH_MAX_DELAY = 120


# Timeout Playwright (ms)
PAGE_LOAD_TIMEOUT = 90_000  # Augmenté à 90s


# =========================
# 🧠 SCRAPING & ANTI-BLOCAGE
# =========================

# User-Agent du Chromium headless de --check-links (le scraping utilise le vrai Chrome)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Chrome « réel » piloté via CDP avec profil persistant (scraping + enrichissement).
# Pas de mode headless : DataDome (LeBonCoin) le détecte et bloque.
CHROME_BINARY = None          # None = recherche google-chrome / chromium dans le PATH
CHROME_DEBUG_PORT = 9222      # 0 = port libre choisi automatiquement
CHROME_STARTUP_TIMEOUT = 15   # secondes d'attente max du port CDP

# Délais entre requêtes (secondes) - plus longs pour simuler un humain
MIN_DELAY_BETWEEN_REQUESTS = 3.0
MAX_DELAY_BETWEEN_REQUESTS = 7.0

# Délai supplémentaire entre les actions sur une même page
MIN_ACTION_DELAY = 0.5
MAX_ACTION_DELAY = 1.5

MAX_PAGES_PER_SITE = 10

# =========================
# 💾 STOCKAGE
# =========================

BASE_DIR = Path(__file__).resolve().parent

# Profil navigateur persistant (conserve cookies entre sessions)
BROWSER_PROFILE_DIR = BASE_DIR / "data" / "browser_profile"

DATA_DIR = BASE_DIR / "data"

DB_PATH = BASE_DIR / "data" / "annonces.sqlite"


# =========================
# 🧾 LOGS
# =========================

LOG_DIR = BASE_DIR / "logs"
LOG_LEVEL = "INFO"


# =========================
# 🔁 DÉDUPLICATION
# =========================

# Même bien publié sur deux sites : écart de prix toléré (en euros)
DUPLICATE_PRICE_TOLERANCE = 5


# =========================
# 🕒 PLANIFICATION
# =========================

# Utilisé par la planification systemd (Sprint 13)
SCRAPE_FREQUENCY_HOURS = 8


# =========================
# 🔍 ENRICHISSEMENT
# =========================

ENRICHMENT_MIN_DELAY = 5.0
ENRICHMENT_MAX_DELAY = 10.0
ENRICHMENT_DEFAULT_LIMIT = 50
