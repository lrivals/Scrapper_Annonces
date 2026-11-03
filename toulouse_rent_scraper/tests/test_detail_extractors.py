# tests/test_detail_extractors.py
# =========================
# Tests unitaires pour les extracteurs de détails (mock Playwright)
# =========================

from unittest.mock import MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Helpers pour créer un mock de page Playwright
# ---------------------------------------------------------------------------

def _make_mock_page(
    title: str = "Annonce immobilière",
    body_text: str = "",
    selectors: dict = None,
):
    """
    Crée un mock de page Playwright.
    `selectors` est un dict {css_selector: inner_text}.
    """
    selectors = selectors or {}
    page = MagicMock()
    page.url = "https://example.com/annonce/123"
    page.title.return_value = title

    def _query_selector(sel):
        for pattern, text in selectors.items():
            if pattern in sel or sel in pattern:
                el = MagicMock()
                el.inner_text.return_value = text
                el.get_attribute.return_value = None
                return el
        return None

    page.query_selector.side_effect = _query_selector
    page.query_selector_all.return_value = []
    page.inner_text.return_value = body_text
    page.wait_for_selector.return_value = None
    page.evaluate.return_value = None
    return page


# ---------------------------------------------------------------------------
# Tests SeLoger
# ---------------------------------------------------------------------------

class TestSeLogerDetail:

    def test_extract_surface(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(
            body_text="Appartement de 35 m² au 2ème étage",
            selectors={'[data-testid*="surface"]': "35 m²"},
        )
        result = extract_detail(page, "https://seloger.com/annonce/1")
        assert result["surface_m2"] == 35.0

    def test_extract_surface_from_body_text(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(body_text="Bel appartement 42m² bien orienté")
        result = extract_detail(page, "https://seloger.com/annonce/2")
        assert result["surface_m2"] == 42.0

    def test_extract_dpe(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(
            body_text="DPE : B - très économique",
            selectors={'[data-testid*="dpe"]': "B"},
        )
        result = extract_detail(page, "https://seloger.com/annonce/3")
        assert result["dpe_rating"] == "B"

    def test_extract_dpe_from_body_text(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(body_text="Consommation énergétique DPE C, bien isolé.")
        result = extract_detail(page, "https://seloger.com/annonce/4")
        assert result["dpe_rating"] == "C"

    def test_extract_nb_rooms(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(
            body_text="Appartement 2 pièces lumineux",
            selectors={'[data-testid*="rooms"]': "2 pièces"},
        )
        result = extract_detail(page, "https://seloger.com/annonce/5")
        assert result["nb_rooms"] == 2

    def test_extract_furnished(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(body_text="Studio meublé avec cuisine équipée.")
        result = extract_detail(page, "https://seloger.com/annonce/6")
        assert result["furnished"] is True

    def test_extract_not_furnished(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(body_text="Appartement vide, libre de suite.")
        result = extract_detail(page, "https://seloger.com/annonce/7")
        assert result["furnished"] is False

    def test_missing_fields_return_none(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(body_text="Bel appartement.")
        result = extract_detail(page, "https://seloger.com/annonce/8")
        assert result["surface_m2"] is None
        assert result["nb_rooms"] is None
        assert result["dpe_rating"] is None
        assert result["charges"] is None
        assert result["deposit"] is None

    def test_404_returns_error(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(title="404 - Page introuvable", body_text="")
        result = extract_detail(page, "https://seloger.com/annonce/999")
        assert result["enrichment_status"] == "error"
        assert result["error_detail"] == "404"

    def test_successful_extraction_marks_done(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(body_text="Studio 28 m², 1 pièce.")
        result = extract_detail(page, "https://seloger.com/annonce/10")
        assert result["enrichment_status"] == "done"

    def test_extract_charges(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(body_text="Loyer 450 € + 50 € de charges mensuelles.")
        result = extract_detail(page, "https://seloger.com/annonce/11")
        assert result["charges"] == 50

    def test_extract_deposit(self):
        from scrapers.detail_extractors.seloger_detail import extract_detail

        page = _make_mock_page(body_text="Dépôt de garantie : 900 €")
        result = extract_detail(page, "https://seloger.com/annonce/12")
        assert result["deposit"] == 900


# ---------------------------------------------------------------------------
# Tests LeBonCoin
# ---------------------------------------------------------------------------

class TestLeBonCoinDetail:

    def test_extract_surface(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = _make_mock_page(
            body_text="Surface : 30 m²",
            selectors={'[data-test-id="criteria_item_square"]': "30 m²"},
        )
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/123")
        assert result["surface_m2"] == 30.0

    def test_extract_surface_from_body_text(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = _make_mock_page(body_text="Appartement 25m² idéalement situé")
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/124")
        assert result["surface_m2"] == 25.0

    def test_extract_description(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        long_desc = "Bel appartement lumineux en plein cœur de Toulouse, idéal pour étudiant."
        page = _make_mock_page(
            body_text=long_desc,
            selectors={'[data-test-id="description"]': long_desc},
        )
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/125")
        assert result["description"] == long_desc

    def test_extract_furnished(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = _make_mock_page(body_text="Chambre meublée disponible immédiatement.")
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/126")
        assert result["furnished"] is True

    def test_extract_nb_rooms(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = _make_mock_page(
            body_text="Appartement 3 pièces",
            selectors={'[data-test-id="criteria_item_rooms_count"]': "3 pièces"},
        )
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/127")
        assert result["nb_rooms"] == 3

    def test_missing_fields_return_none(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = _make_mock_page(body_text="Annonce immobilière.")
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/128")
        assert result["surface_m2"] is None
        assert result["nb_rooms"] is None
        assert result["dpe_rating"] is None

    def test_404_returns_error(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = _make_mock_page(title="Page not found - 404", body_text="")
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/999")
        assert result["enrichment_status"] == "error"
        assert result["error_detail"] == "404"

    def test_successful_extraction_marks_done(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = _make_mock_page(body_text="Studio 22 m² meublé.")
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/130")
        assert result["enrichment_status"] == "done"

    def test_extract_publisher_pro(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = _make_mock_page(body_text="Mis en ligne par un pro, agence immobilière.")
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/131")
        assert result["publisher_type"] == "agency"

    def test_extract_publisher_individual(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = _make_mock_page(body_text="Annonce par un particulier, sans commission.")
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/132")
        assert result["publisher_type"] == "individual"
