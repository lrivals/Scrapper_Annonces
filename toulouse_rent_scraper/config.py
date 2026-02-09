# config.py
# =========================
# Configuration globale du projet
# =========================

from pathlib import Path

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

PROPERTY_TYPES = [
    "studio",
    "chambre",
    "appartement"
]

# Quartiers ciblés (indicatifs, filtrage final par distance)
TARGET_DISTRICTS = [
    "Rangueil",
    "Ramonville-Saint-Agne",
    "Saouzelong",
    "Pont des Demoiselles",
    "Pech-David",
    "Saint-Agne"
]


# =========================
# 🌐 SELOGER
# =========================

SELOGER_BASE_URL = "https://www.seloger.com"

# URL de recherche avec filtres pré-appliqués (pages 1 à 3)
_SELOGER_LOCATIONS = (
    "eyJwbGFjZUlkIjoiQUQwOEZSMTI1MzUiLCJyYWRpdXMiOjEwLCJwb2x5bGluZSI6In1obGlH"
    "cV9fSHhJanZDfl5wcEN8ckBgZUN6ZEFsdEJkdEFoX0JiYEJuZkFqaEJ6akBwbEJ0TW5sQmNO"
    "aGhCaWtAfl9CdWZBfnNBa19CdGRBa3RCeHJAeWRDfF5lcEN2SX11Q3dJfXVDfV5jcEN5ckB5"
    "ZEN1ZEFrdEJfdEFtX0JfYEJ1ZkFpaEJpa0BvbEJhTnFsQnJNa2hCfGpAY2BCbGZBZXRBaF9C"
    "e2RBbnRCfXJAYGVDX19AbnBDeUlqdkMiLCJjb29yZGluYXRlcyI6eyJsYXQiOjQzLjU1OTc1"
    "ODY0ODI4NDgsImxuZyI6MS40NzQ2NDgyNzM1OTg0MzN9fQ"
)

SELOGER_SEARCH_URL = (
    "https://www.seloger.com/classified-search"
    "?classifiedBusiness=Professional"
    "&distributionTypes=Rent"
    "&estateSubTypes=Studio"
    "&estateTypes=Apartment"
    f"&locations={_SELOGER_LOCATIONS}"
    "&order=PriceAsc"
)

SELOGER_SEARCH_URLS = [
    SELOGER_SEARCH_URL,
    SELOGER_SEARCH_URL + "&page=2",
    SELOGER_SEARCH_URL + "&page=3",
]


# =========================
# 🌐 LEBONCOIN
# =========================

LEBONCOIN_BASE_URL = "https://www.leboncoin.fr"

# Navigation progressive (étapes intermédiaires pour simuler un vrai utilisateur)
LEBONCOIN_STEP_IMMOBILIER = "https://www.leboncoin.fr/c/locations"
LEBONCOIN_STEP_LOCATION = "https://www.leboncoin.fr/c/locations/real_estate_type:2"
LEBONCOIN_STEP_TOULOUSE = (
    "https://www.leboncoin.fr/recherche"
    "?category=10"
    "&locations=Toulouse__43.599373754597394_1.435619856703149_9864_10000"
    "&real_estate_type=2"
)

# URL finale avec tous les filtres
LEBONCOIN_SEARCH_URL = (
    "https://www.leboncoin.fr/recherche"
    "?category=10"
    "&locations=Toulouse__43.599373754597394_1.435619856703149_9864_10000"
    "&price=450-max"
    "&real_estate_type=2"
    "&sort=price&order=asc"
)

# Timeout Playwright (ms)
PAGE_LOAD_TIMEOUT = 90_000  # Augmenté à 90s

# Stratégies anti-détection supplémentaires
USE_STEALTH_MODE = True


# =========================
# 🧠 SCRAPING & ANTI-BLOCAGE
# =========================

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Mettre à False pour debug visuel
HEADLESS_BROWSER = False

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
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

DB_PATH = BASE_DIR / "data" / "annonces.sqlite"


# =========================
# 🧾 LOGS
# =========================

LOG_DIR = BASE_DIR / "logs"
LOG_LEVEL = "INFO"


# =========================
# 🔁 DÉDUPLICATION
# =========================

# Champs utilisés pour identifier une annonce unique
DEDUP_KEYS = [
    "price",
    "surface",
    "district"
]


# =========================
# 🕒 PLANIFICATION
# =========================

SCRAPE_FREQUENCY_HOURS = 8


# =========================
# 🔧 DIVERS
# =========================

DEBUG = False
SAVE_RAW_HTML = False
