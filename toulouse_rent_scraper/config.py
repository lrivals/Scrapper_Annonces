# config.py
# =========================
# Configuration globale du projet
# =========================

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    min_rent_eur: Optional[int] = None          # None = pas de borne
    max_rent_eur: Optional[int] = None          # None = pas de plafond
    rooms: Optional[Tuple[int, int]] = None     # (min, max) pièces ; None = pas de contrainte
    target_rent_eur: Optional[int] = None       # loyer CC « idéal » : note loyer maximale en dessous
    lbc_location: Optional[str] = None          # paramètre `locations` LeBonCoin
    lbc_search_url: Optional[str] = None        # URL LBC brute (copiée du site), prioritaire sur lbc_location
    lbc_warmup_urls: Tuple[str, ...] = ()       # recherches visitées avant celle scannée (cooldown entre chaque)
    seloger_locations: Optional[str] = None     # paramètre `locations` SeLoger (base64, à capturer)
    seloger_search_url: Optional[str] = None    # URL SeLoger brute (copiée du site), prioritaire
    seloger_warmup_urls: Tuple[str, ...] = ()   # recherches visitées avant celle scannée
    seloger_sub_types: str = "Studio"
    enabled: bool = True

    @property
    def target(self) -> Tuple[float, float]:
        return (self.target_lat, self.target_lon)

    def leboncoin_search_url(self) -> Optional[str]:
        if self.lbc_search_url:
            return self.lbc_search_url
        if not self.lbc_location:
            return None
        return build_leboncoin_search_url(
            self.lbc_location, self.min_rent_eur, self.max_rent_eur, self.rooms
        )

    def leboncoin_search_urls(self) -> List[str]:
        """Page 1 puis &page=2… Les profils sans lbc_search_url gardent la pagination par bouton."""
        first = self.leboncoin_search_url()
        if not first:
            return []
        if not self.lbc_search_url:
            return [first]
        return [first] + [f"{first}&page={n}" for n in range(2, MAX_PAGES_PER_SITE + 1)]

    def seloger_search_urls(self):
        if self.seloger_search_url:
            first = self.seloger_search_url
            return [first] + [f"{first}&page={n}" for n in range(2, MAX_PAGES_PER_SITE + 1)]
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
        target_rent_eur=350,
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
        # Pas de fourchette de prix ni de nombre de pièces (2026-11-04) : seuls
        # le rayon et la recherche LBC filtrent. target_rent_eur sert au score.
        target_rent_eur=600,
        # URLs copiées depuis leboncoin.fr (2026-11-04) : Blagnac 5 km + Toulouse,
        # appartement/maison avec balcon/terrasse/jardin. Pas de filtre prix côté LBC :
        # budget et distance ≤ 8 km sont filtrés en local.
        lbc_warmup_urls=(
            "https://www.leboncoin.fr/recherche?category=10"
            "&locations=Toulouse__43.599373754597394_1.435619856703149_9864__d31",
            "https://www.leboncoin.fr/recherche?category=10"
            "&locations=Blagnac_31700__43.63458_1.39684_5000,"
            "Toulouse__43.599373754597394_1.435619856703149_9864__d31",
        ),
        lbc_search_url=(
            "https://www.leboncoin.fr/recherche?category=10&text=location"
            "&locations=Blagnac_31700__43.63458_1.39684_5000%2C"
            "Toulouse__43.599373754597394_1.435619856703149_9864__d31"
            "&real_estate_type=2%2C1&outside_access=balcony%2Cterrace%2Cgarden"
        ),
        # SeLoger (2026-11-04) : accueil onglet Louer → Toulouse → recherche scannée
        # (appartement, balcon/terrasse, Toulouse + Blagnac, 1+ chambre, ≤ 3 pièces).
        seloger_warmup_urls=(
            "https://www.seloger.com/?tab=rent#?BD=Head_LO_Loc_2",
            "https://www.seloger.com/classified-search?distributionTypes=Rent"
            "&estateTypes=House,Apartment&initialQuery=Toulouse&locations=AD08FR12535"
            "&method=smart_suggestion&m=homepage_new_search_classified_search_result",
        ),
        seloger_search_url=(
            "https://www.seloger.com/classified-search?distributionTypes=Rent"
            "&estateTypes=Apartment&featuresIncluded=Balcony_Terrace"
            "&initialQuery=Toulouse%20Blagnac&locations=AD08FR12535,AD08FR12051"
            "&method=form&numberOfBedroomsMin=1&numberOfRoomsMax=3&projectTypes=Stock"
            "&order=DateDesc"
        ),
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

# Recherches avec warm-up (LBC, SeLoger) : cooldown entre étapes de warm-up et entre pages scannées
WARMUP_STEP_MIN_DELAY = 15.0
WARMUP_STEP_MAX_DELAY = 30.0
WARMUP_PAGE_MIN_DELAY = 10.0
WARMUP_PAGE_MAX_DELAY = 20.0

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

# Horaires : voir deploy/scraper.timer (systemd), pas de réglage ici.

# Verrou : un seul scraping / enrichissement à la fois (timer + bouton de l'UI)
SCRAPE_LOCK_FILE = DATA_DIR / ".scrape.lock"

# Challenge anti-bot : attente de résolution manuelle (secondes)
CHALLENGE_TIMEOUT_SECONDS = 180
UNATTENDED_CHALLENGE_TIMEOUT_SECONDS = 600   # mode planifié : le temps de voir la notification

# Après un blocage non résolu, un run planifié saute ce site pendant ce délai (anti-ban IP)
BLOCK_COOLDOWN_HOURS = 6
BLOCK_STATE_FILE = DATA_DIR / ".last_block.json"


# =========================
# 🔍 ENRICHISSEMENT
# =========================

ENRICHMENT_MIN_DELAY = 5.0
ENRICHMENT_MAX_DELAY = 10.0
ENRICHMENT_DEFAULT_LIMIT = 50
# Échec d'enrichissement : nouvel essai après ce délai, au plus N tentatives (puis « failed »)
ENRICHMENT_MAX_ATTEMPTS = 3
ENRICHMENT_RETRY_DELAY_HOURS = 24

# Santé de l'extraction (Sprint 15.1) : taux de remplissage minimal attendu par champ
# sur les annonces enrichies d'un run. En dessous → alerte « sélecteurs probablement cassés ».
QUALITY_MIN_SAMPLES = 5            # pas de verdict en dessous de N annonces enrichies par site
QUALITY_MIN_FILL_RATES = {
    "surface_m2": 0.6,
    "nb_rooms": 0.6,
    "description": 0.6,
    "photos": 0.6,
}
# Part minimale d'annonces LBC extraites depuis le JSON : en dessous, `__NEXT_DATA__`
# a probablement disparu ou changé de forme
QUALITY_MIN_JSON_RATE = {"LeBonCoin": 0.5}


# =========================
# ⭐ SCORE D'INTÉRÊT (Sprint 13)
# =========================

# Poids relatifs des critères (le score final est ramené sur 100)
SCORE_WEIGHTS = {
    "loyer": 35,       # loyer charges comprises vs budget du profil
    "distance": 30,    # distance à la cible du profil
    "prix_m2": 15,     # €/m² vs médiane des annonces du profil
    "meuble": 10,
    "dpe": 10,
}

# Valeur (0–1) de chaque étiquette DPE ; inconnu = 0.5 (neutre)
DPE_SCORES = {"A": 1.0, "B": 1.0, "C": 1.0, "D": 0.6, "E": 0.3, "F": 0.0, "G": 0.0}


# =========================
# 🔔 NOTIFICATIONS (Sprint 13)
# =========================

def _load_env_file(path: Path):
    """Charge un fichier .env (CLE=valeur) sans écraser l'environnement existant."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# Secrets dans toulouse_rent_scraper/.env (ignoré par git) — voir .env.example
_load_env_file(BASE_DIR / ".env")

NOTIFY_BACKEND = os.environ.get("NOTIFY_BACKEND") or None    # "ntfy" | "telegram" | None
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")                    # long et aléatoire : il fait office de secret
NTFY_TOKEN = os.environ.get("NTFY_TOKEN")                    # optionnel (serveur ntfy protégé)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

NOTIFY_MIN_SCORE = 55          # en dessous, pas d'alerte (l'annonce reste visible dans l'UI)
NOTIFY_PRICE_DROP_EUR = 20     # alerte si le loyer baisse d'au moins ce montant
NOTIFY_GROUP_THRESHOLD = 3     # au-delà, un seul message récapitulatif par profil
NOTIFY_GROUP_MAX_ITEMS = 8     # nombre d'annonces listées dans un récapitulatif

