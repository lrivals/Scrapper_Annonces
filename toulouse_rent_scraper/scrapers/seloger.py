# scrapers/seloger.py
# =========================
# Scraper SeLoger avec Playwright
# =========================

import json
import re
from typing import List, Dict, Optional

from scrapers.base import BaseScraper
from config import SELOGER_BASE_URL


class SeLogerScraper(BaseScraper):
    """Scraper pour SeLoger.com."""

    def site_name(self) -> str:
        return "SeLoger"

    def base_url(self) -> str:
        return SELOGER_BASE_URL

    def search_url(self) -> Optional[str]:
        urls = self.search_urls()
        return urls[0] if urls else None

    def search_urls(self) -> list:
        return self.profile.seloger_search_urls()

    def card_selector(self) -> str:
        return 'div[data-testid^="classified-card-mfe-"]'

    def fallback_card_selectors(self) -> List[str]:
        return ["article", "[data-listing-id]"]

    def next_page_selector(self) -> str:
        return 'a[rel="next"]'

    def extract_annonce(self, card) -> Optional[Dict]:
        """Extrait les données d'une carte SeLoger via data-testid."""
        # Lien — le covering link contient href + title complet
        link_el = card.query_selector('a[data-testid="card-mfe-covering-link-testid"]')
        if not link_el:
            link_el = card.query_selector("a[href]")
        if not link_el:
            return None

        href = link_el.get_attribute("href")
        if not href:
            return None
        full_link = self.build_full_url(href)

        # Titre — depuis le title du covering link (ex: "Studio à louer - Toulouse - 350 € - 6 pièces")
        # ou depuis le div de description à l'intérieur de la carte
        title = ""
        link_title = link_el.get_attribute("title") or ""
        if link_title:
            # Nettoyer le &nbsp; et prendre la partie avant le prix
            title = link_title.replace('\xa0', ' ').split(' - ')[0].strip()

        if not title:
            title_el = card.query_selector('div.css-1n0wsen')
            if title_el:
                title = title_el.inner_text().strip()

        # Prix — depuis le data-testid dédié (aria-label = "300 €")
        price = None
        price_el = card.query_selector('[data-testid="cardmfe-price-testid"]')
        if price_el:
            price_label = price_el.get_attribute("aria-label") or ""
            price_match = re.search(r'([\d\s\xa0\u202f.]+)\s*€', price_label)
            if price_match:
                price = price_match.group(1).replace('\xa0', '').replace('\u202f', '').replace(' ', '').strip()

        # Fallback prix dans le texte du price_el
        if not price and price_el:
            price_text = price_el.inner_text()
            price_match = re.search(r'([\d\s\xa0\u202f.]+)\s*€', price_text)
            if price_match:
                price = price_match.group(1).replace('\xa0', '').replace('\u202f', '').replace(' ', '').strip()

        # Localisation — depuis le data-testid dédié
        location_raw = ""
        loc_el = card.query_selector('[data-testid="cardmfe-description-box-address"]')
        if loc_el:
            location_raw = loc_el.inner_text().strip()

        if not title and not price:
            return None

        # Thumbnail — première image de la carte
        thumbnail = None
        try:
            img_el = card.query_selector(
                'img[data-testid*="photo"], img[data-testid*="image"], img[src]'
            )
            if img_el:
                src = img_el.get_attribute("src") or img_el.get_attribute("data-src") or ""
                if src and src.startswith("http"):
                    thumbnail = src
        except Exception:
            pass

        return {
            "site": "SeLoger",
            "title": title,
            "price": price,
            "location_raw": location_raw,
            "url": full_link,
            "photos": json.dumps([thumbnail]) if thumbnail else None,
        }


def scrape_seloger() -> List[Dict]:
    """Fonction wrapper pour compatibilité avec le code existant."""
    scraper = SeLogerScraper()
    return scraper.scrape()


# Test manuel
if __name__ == "__main__":
    annonces = scrape_seloger()
    print(f"{len(annonces)} annonces recuperees")
    for a in annonces[:5]:
        print(a)
