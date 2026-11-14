# scrapers/pap.py
# =========================
# PAP.fr (Sprint 4) — annonces de particuliers, sans frais d'agence.
#
# Cloudflare refuse les requêtes sans navigateur (403 « Just a moment… ») : vrai Chrome
# au profil persistant, comme SeLoger et LeBonCoin.
#
# Pas de pages numérotées : la liste se charge au défilement (pages -2, -3… ajoutées à la
# même page). On défile comme un humain jusqu'à ce que la liste ne grandisse plus, puis on
# lit toutes les cartes d'un coup dans le HTML (scrapers/detail_extractors/pap_html.py).
# Au-delà des résultats de la zone, PAP propose des annonces « à proximité » sans carte :
# la liste cesse alors de grandir.
# =========================

import random
import time
from typing import Dict, List, Optional

from config import (
    MAX_PAGES_PER_SITE,
    PAP_BASE_URL,
    PAP_MAX_SCROLLS,
    PAP_SCROLL_MAX_DELAY,
    PAP_SCROLL_MIN_DELAY,
    PAP_STABLE_SCROLLS,
)
from scrapers import antibot
from scrapers.base import BaseScraper
from scrapers.detail_extractors import pap_html

# Vérification Cloudflare (s'ajoute aux marqueurs DataDome communs)
CLOUDFLARE_MARKERS = ["vérifiez que vous êtes humain", "verify you are human", "checking your browser"]


class PAPScraper(BaseScraper):
    """Scraper pour PAP.fr (particulier à particulier)."""

    def site_name(self) -> str:
        return pap_html.SITE_NAME

    def base_url(self) -> str:
        return PAP_BASE_URL

    def search_url(self) -> Optional[str]:
        return self.profile.pap_search_url

    def warmup_urls(self) -> List[str]:
        return list(self.profile.pap_warmup_urls)

    def card_selector(self) -> str:
        return "div.search-list-item-alt"

    def fallback_card_selectors(self) -> List[str]:
        return ["div[class*='search-list-item']"]

    def next_page_selector(self) -> str:
        return "a#pagination-next"

    def challenge_markers(self) -> List[str]:
        return antibot.CHALLENGE_MARKERS + CLOUDFLARE_MARKERS

    def annonce_key(self, url: Optional[str]) -> Optional[str]:
        return pap_html.annonce_id(url) or url

    def build_full_url(self, relative_url: str) -> str:
        return pap_html.canonical_url(super().build_full_url(relative_url))

    # --- Cartes ---

    def page_json_annonces(self, page) -> List[Dict]:
        """Cartes logement lues dans le HTML de la page (toutes celles chargées par le défilement)."""
        return [listing.to_annonce() for listing in pap_html.search_listings(page.content())]

    def _json_annonces_for_cards(self, page, cards) -> List[Dict]:
        # Lu dans la page elle-même : jamais périmé. Le contrôle de recouvrement de la base
        # le rejetterait à tort quand la recherche contient beaucoup de bureaux / garages.
        try:
            return self.page_json_annonces(page)
        except Exception as e:
            self.logger.warning(f"  Cartes PAP illisibles dans le HTML : {e}")
            return []

    def extract_annonce(self, card) -> Optional[Dict]:
        """Secours carte par carte (le HTML complet est normalement lu par page_json_annonces)."""
        try:
            fragment = card.evaluate("el => el.outerHTML")
        except Exception:
            return None
        listing = pap_html.parse_card(fragment)
        return listing.to_annonce() if listing else None

    # --- Défilement infini ---

    def _card_count(self, page) -> int:
        try:
            return page.evaluate(
                "() => new Set([...document.querySelectorAll('a.item-title')].map(a => a.href)).size"
            )
        except Exception:
            return -1

    def _scroll_until_complete(self, page):
        """Défile jusqu'à ce que la liste ne grandisse plus (≈ 10 cartes par palier)."""
        # Un palier ≈ une « page » du site : même plafond que les autres sources
        max_cards = MAX_PAGES_PER_SITE * 12
        previous, stable = -1, 0
        for step in range(PAP_MAX_SCROLLS):
            page.mouse.wheel(0, random.randint(700, 1100))
            time.sleep(random.uniform(PAP_SCROLL_MIN_DELAY, PAP_SCROLL_MAX_DELAY))
            if step % 5 == 4:
                self.human_mouse_move(page)
            count = self._card_count(page)
            if count == previous:
                stable += 1
                if stable >= PAP_STABLE_SCROLLS:
                    break
            else:
                stable, previous = 0, count
            if count >= max_cards:
                self.logger.info(f"  Plafond de {max_cards} cartes atteint")
                break
            if self.is_page_blocked(page) and not self.wait_for_challenge(page):
                break
        try:
            total = pap_html.search_total(page.content())
        except Exception:
            total = None
        self.logger.info(
            f"  Défilement terminé : {max(previous, 0)} carte(s) chargée(s)"
            + (f" sur {total} annoncée(s) par le site" if total is not None else "")
        )

    def _scrape_current_page(self, page, selector: str, page_num: int):
        self._scroll_until_complete(page)
        super()._scrape_current_page(page, selector, page_num)

    def _paginate(self, page, selector: str):
        """Tout est chargé par le défilement de la première page."""
        return
