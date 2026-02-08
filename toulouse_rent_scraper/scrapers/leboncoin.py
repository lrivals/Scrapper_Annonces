# scrapers/leboncoin.py
# =========================
# Scraper Le Bon Coin avec Playwright
# =========================

import re
from typing import List, Dict, Optional

from scrapers.base import BaseScraper
from config import (
    LEBONCOIN_SEARCH_URL,
    LEBONCOIN_BASE_URL,
    LEBONCOIN_STEP_IMMOBILIER,
    LEBONCOIN_STEP_LOCATION,
    LEBONCOIN_STEP_TOULOUSE,
)


class LeBonCoinScraper(BaseScraper):
    """Scraper pour leboncoin.fr."""

    def site_name(self) -> str:
        return "LeBonCoin"

    def base_url(self) -> str:
        return LEBONCOIN_BASE_URL

    def search_url(self) -> str:
        return LEBONCOIN_SEARCH_URL

    def navigation_steps(self) -> List[Dict]:
        """Navigation progressive : accueil puis recherche directe."""
        return [
            {"url": LEBONCOIN_BASE_URL, "label": "page d'accueil LeBonCoin"},
            {"url": LEBONCOIN_SEARCH_URL, "label": "recherche avec filtres"},
        ]

    def card_selector(self) -> str:
        return 'article[data-qa-id="aditem_container"]'

    def fallback_card_selectors(self) -> List[str]:
        return [
            'article[data-test-id="ad"]',
            'article:has(a[href*="/ad/"])',
        ]

    def next_page_selector(self) -> str:
        return 'a[title="Page suivante"], button[title="Page suivante"]'

    def blocked_domains(self) -> List[str]:
        domains = super().blocked_domains()
        return domains + ["leboncoin.fr/blocked"]

    def challenge_markers(self) -> List[str]:
        markers = super().challenge_markers()
        return markers + [
            "veuillez patienter",
            "vérification en cours",
        ]

    def extract_annonce(self, card) -> Optional[Dict]:
        """Extrait les données d'une carte Le Bon Coin."""
        # Récupérer le lien
        href = card.get_attribute("href")
        if not href:
            link_el = card.query_selector('a[href*="/ad/"]')
            if not link_el:
                return None
            href = link_el.get_attribute("href")
            if not href:
                return None

        full_link = self.build_full_url(href)

        # Titre — aria-label de l'article (ex: "Appartement, 2 pièces, 36 mètres carrés.")
        title = ""
        aria_label = card.get_attribute("aria-label")
        if aria_label:
            title = aria_label.strip().rstrip(".")

        if not title:
            h3 = card.query_selector("h3")
            if h3:
                title = h3.inner_text().strip().rstrip(".")

        # Prix — data-test-id="price" (nouveau sélecteur LBC)
        price = None
        price_el = card.query_selector('[data-test-id="price"]')
        if price_el:
            price_text = price_el.inner_text()
            price_match = re.search(r'([\d\s\xa0\u202f.]+)\s*€', price_text)
            if price_match:
                price = price_match.group(1).replace('\xa0', '').replace('\u202f', '').replace(' ', '').strip()

        # Fallback prix via regex sur tout le texte
        if not price:
            card_text = card.inner_text()
            price_match = re.search(r'([\d\s\xa0\u202f.]+)\s*€', card_text)
            if price_match:
                price = price_match.group(1).replace('\xa0', '').replace('\u202f', '').replace(' ', '').strip()

        # Localisation — chercher "Située à ..." dans les <p class="sr-only">
        location_raw = ""
        sr_elements = card.query_selector_all('p.sr-only')
        for sr in sr_elements:
            text = sr.inner_text().strip()
            if text.startswith("Située à "):
                location_raw = text.replace("Située à ", "").rstrip(".")
                break

        # Fallback localisation via le texte visible (aria-hidden paragraph)
        if not location_raw:
            card_text = card.inner_text()
            lines = [l.strip() for l in card_text.split("\n") if l.strip()]
            for line in lines:
                if line.startswith("Situ"):
                    continue
                if re.search(r'\b(31\d{3}|[Tt]oulouse|[Rr]amonville|[Bb]alma|[Cc]astanet|[Mm]uret)', line):
                    location_raw = line
                    break

        if not title and not price:
            return None

        return {
            "site": "LeBonCoin",
            "title": title,
            "price": price,
            "location_raw": location_raw,
            "url": full_link,
        }


def scrape_leboncoin() -> List[Dict]:
    """Fonction wrapper pour usage direct."""
    scraper = LeBonCoinScraper()
    return scraper.scrape()


# Test manuel
if __name__ == "__main__":
    annonces = scrape_leboncoin()
    print(f"{len(annonces)} annonces recuperees")
    for a in annonces[:5]:
        print(a)
