# scrapers/api_base.py
# =========================
# Sources « API JSON » (Sprint 15.7) : pas de navigateur, pas d'anti-bot à contourner.
#
# Deux familles de sources :
#   - navigateur + anti-bot (BaseScraper : SeLoger, LeBonCoin) ;
#   - API JSON (ApiScraper : Bien'ici, puis PAP…) : requêtes HTTP simples, rythme poli,
#     annonces complètes produites sous forme de `Listing`.
# Même interface pour le pipeline : ApiScraper(profile, unattended).search_url() / .scrape().
# =========================

import random
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from config import DEFAULT_PROFILE, SEARCH_PROFILES, SearchProfile
from utils.logger import setup_logger

# Navigateur courant : certaines API refusent les clients sans User-Agent de navigateur
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


class ApiBlocked(Exception):
    """Le site refuse les requêtes (403 / 429) : on s'arrête et on le mémorise (anti-ban)."""


class ApiScraper(ABC):
    """Base des sources interrogées via une API JSON."""

    # Pas de longue pause anti-bot avant cette recherche (pipeline.run_scraping)
    requires_cooldown = False

    def __init__(self, profile: Optional[SearchProfile] = None, unattended: bool = False):
        self.profile = profile or SEARCH_PROFILES[DEFAULT_PROFILE]
        self.unattended = unattended
        self.logger = setup_logger(self.site_name().lower().replace("'", ""))
        self.results: List[Dict] = []
        self._session: Optional[requests.Session] = None
        self._requests = 0

    # --- À définir par chaque source ---

    @abstractmethod
    def site_name(self) -> str:
        """Nom du site tel que stocké en base (colonne `site`)."""

    @abstractmethod
    def search_url(self) -> Optional[str]:
        """Point d'entrée de la recherche du profil ; None si le profil n'est pas configuré."""

    @abstractmethod
    def fetch_annonces(self) -> None:
        """
        Interroge l'API et ajoute les annonces brutes du pipeline à `self.results`
        au fil des pages : une erreur en page 3 garde les pages 1 et 2.
        """

    # --- HTTP ---

    def headers(self) -> Dict[str, str]:
        return {"User-Agent": USER_AGENT, "Accept": "application/json"}

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(self.headers())
        return self._session

    def polite_delay(self, low: float, high: float):
        """Pause entre deux requêtes (sauf avant la première)."""
        if self._requests:
            time.sleep(random.uniform(low, high))

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30) -> Any:
        """GET → JSON. ApiBlocked sur 403/429 ; autres erreurs HTTP/réseau : exception requests."""
        self._requests += 1
        resp = self.session.get(url, params=params, timeout=timeout)
        if resp.status_code in (403, 429):
            raise ApiBlocked(f"HTTP {resp.status_code}")
        resp.raise_for_status()
        return resp.json()

    # --- Point d'entrée commun ---

    def scrape(self) -> List[Dict]:
        self.results = []
        if not self.search_url():
            self.logger.warning(
                f"Profil '{self.profile.key}' non configuré pour {self.site_name()}, site ignoré"
            )
            return self.results
        self.logger.info(f"Demarrage {self.site_name()} (API) — profil {self.profile.label}")
        try:
            self.fetch_annonces()
        except ApiBlocked as e:
            from scrapers.antibot import record_block
            self.logger.error(f"{self.site_name()} refuse les requêtes ({e}) : arrêt, site mis en pause")
            record_block(self.site_name())
        except (requests.RequestException, ValueError) as e:
            self.logger.error(f"Erreur API {self.site_name()} : {e}")
        except Exception as e:
            self.logger.error(f"Erreur inattendue {self.site_name()} : {e}", exc_info=True)
        finally:
            if self._session is not None:
                self._session.close()
                self._session = None
        self.logger.info(f"{self.site_name()} : {len(self.results)} annonces")
        return self.results
