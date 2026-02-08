# tests/test_leboncoin.py
# =========================
# Tests unitaires pour le scraper Le Bon Coin
# =========================

import pytest
from unittest.mock import MagicMock

from scrapers.leboncoin import LeBonCoinScraper


@pytest.fixture
def scraper():
    return LeBonCoinScraper()


class TestLeBonCoinConfig:
    """Tests pour la configuration du scraper LeBonCoin."""

    def test_site_name(self, scraper):
        assert scraper.site_name() == "LeBonCoin"

    def test_base_url(self, scraper):
        assert scraper.base_url() == "https://www.leboncoin.fr"

    def test_search_url(self, scraper):
        url = scraper.search_url()
        assert "leboncoin.fr" in url
        assert "category=10" in url

    def test_card_selector(self, scraper):
        assert "aditem_container" in scraper.card_selector()

    def test_blocked_domains(self, scraper):
        domains = scraper.blocked_domains()
        assert "captcha-delivery.com" in domains
        assert "datadome.co" in domains


class TestLeBonCoinExtract:
    """Tests pour l'extraction de données des cartes LeBonCoin."""

    def _make_card(self, href=None, title=None, price=None, location=None):
        """Crée un mock de carte LeBonCoin."""
        card = MagicMock()
        card.get_attribute.return_value = href

        def query_selector(selector):
            el = MagicMock()
            if "title" in selector and title:
                el.inner_text.return_value = title
                return el
            elif "price" in selector and price:
                el.inner_text.return_value = price
                return el
            elif "location" in selector and location:
                el.inner_text.return_value = location
                return el
            return None

        card.query_selector.side_effect = query_selector
        card.inner_text.return_value = f"{title}\n{price}\n{location}"
        return card

    def test_extract_complete_annonce(self, scraper):
        card = self._make_card(
            href="/ad/locations/12345",
            title="Studio meublé Toulouse",
            price="420 €",
            location="Toulouse 31000",
        )
        result = scraper.extract_annonce(card)
        assert result is not None
        assert result["site"] == "LeBonCoin"
        assert result["title"] == "Studio meublé Toulouse"
        assert result["price"] == "420"
        assert result["location_raw"] == "Toulouse 31000"
        assert "leboncoin.fr" in result["url"]

    def test_extract_no_href(self, scraper):
        card = self._make_card(href=None, title="Test", price="300 €")
        result = scraper.extract_annonce(card)
        assert result is None

    def test_extract_no_title_no_price(self, scraper):
        card = self._make_card(href="/ad/locations/12345")
        card.inner_text.return_value = ""
        result = scraper.extract_annonce(card)
        assert result is None

    def test_extract_price_with_spaces(self, scraper):
        card = self._make_card(
            href="/ad/locations/99999",
            title="Appart T2",
            price="1 200 €",
            location="Ramonville",
        )
        result = scraper.extract_annonce(card)
        assert result is not None
        assert result["price"] == "1200"

    def test_extract_absolute_url(self, scraper):
        card = self._make_card(
            href="https://www.leboncoin.fr/ad/locations/12345",
            title="Studio",
            price="350 €",
            location="Toulouse",
        )
        result = scraper.extract_annonce(card)
        assert result["url"] == "https://www.leboncoin.fr/ad/locations/12345"

    def test_build_full_url_relative(self, scraper):
        assert scraper.build_full_url("/ad/123") == "https://www.leboncoin.fr/ad/123"

    def test_build_full_url_absolute(self, scraper):
        url = "https://www.leboncoin.fr/ad/123"
        assert scraper.build_full_url(url) == url
