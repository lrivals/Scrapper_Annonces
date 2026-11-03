# tests/test_enricher.py
# =========================
# Tests pour le pipeline d'enrichissement
# =========================

from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import pytest


def _fake_session(page):
    """Remplace chrome_session : aucun Chrome lancé, yield (browser, page)."""
    @contextmanager
    def session(*args, **kwargs):
        yield MagicMock(), page
    return session


class TestEnrichAnnonces:
    """Tests pour enrich_annonces() avec DB et Playwright mockés."""

    def test_enrich_empty_db(self, temp_db):
        """Aucune annonce en attente → retourne 0 enrichies."""
        from storage.sqlite import init_db
        init_db()

        with patch("scrapers.enricher.get_pending_annonces", return_value=[]):
            from scrapers.enricher import enrich_annonces
            result = enrich_annonces(limit=10)

        assert result["total"] == 0
        assert result["enriched"] == 0
        assert result["errors"] == 0

    def test_enrich_marks_done(self, temp_db):
        """Une annonce SeLoger → extracteur appelé → enrichment_status='done' en DB."""
        from storage.sqlite import init_db, insert_annonce, get_pending_annonces
        init_db()
        insert_annonce({
            "site": "SeLoger",
            "title": "Studio test",
            "price": 400,
            "location_raw": "Rangueil",
            "distance_enac_km": 1.0,
            "url": "https://seloger.com/test/enricher/1",
        })

        fake_detail = {
            "surface_m2": 28.0,
            "nb_rooms": 1,
            "dpe_rating": "C",
            "enrichment_status": "done",
        }

        mock_page = MagicMock()
        mock_page.url = "https://seloger.com/test/enricher/1"
        mock_page.goto.return_value = None

        with patch("scrapers.enricher.chrome_session", _fake_session(mock_page)), \
             patch("scrapers.enricher.is_page_blocked", return_value=False), \
             patch("scrapers.detail_extractors.seloger_detail.extract_detail", return_value=fake_detail):
            from scrapers.enricher import enrich_annonces
            result = enrich_annonces(limit=10)

        assert result["enriched"] == 1
        assert result["errors"] == 0

        # Vérifier en DB
        import sqlite3
        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT enrichment_status, surface_m2, dpe_rating FROM annonces WHERE url = ?",
            ("https://seloger.com/test/enricher/1",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "done"
        assert row[1] == 28.0
        assert row[2] == "C"

    def test_enrich_marks_error_on_exception(self, temp_db):
        """Extracteur qui lève une exception → enrichment_status='error' en DB."""
        from storage.sqlite import init_db, insert_annonce
        init_db()
        insert_annonce({
            "site": "LeBonCoin",
            "title": "Chambre test",
            "price": 350,
            "location_raw": "Ramonville",
            "distance_enac_km": 3.0,
            "url": "https://www.leboncoin.fr/ad/locations/enricher/1",
        })

        mock_page = MagicMock()
        mock_page.url = "https://www.leboncoin.fr/ad/locations/enricher/1"
        mock_page.goto.return_value = None

        with patch("scrapers.enricher.chrome_session", _fake_session(mock_page)), \
             patch("scrapers.enricher.is_page_blocked", return_value=False), \
             patch(
                 "scrapers.detail_extractors.leboncoin_detail.extract_detail",
                 side_effect=RuntimeError("Sélecteur introuvable"),
             ):
            from scrapers.enricher import enrich_annonces
            result = enrich_annonces(limit=10)

        assert result["errors"] == 1
        assert result["enriched"] == 0

    def test_site_filter_seloger(self, temp_db):
        """site_filter='SeLoger' ne récupère que les annonces SeLoger."""
        from storage.sqlite import init_db, insert_annonce
        init_db()
        insert_annonce({
            "site": "SeLoger",
            "title": "Studio SeLoger",
            "price": 400,
            "location_raw": "Rangueil",
            "distance_enac_km": 1.0,
            "url": "https://seloger.com/filter/test/1",
        })
        insert_annonce({
            "site": "LeBonCoin",
            "title": "Studio LBC",
            "price": 380,
            "location_raw": "Rangueil",
            "distance_enac_km": 1.5,
            "url": "https://www.leboncoin.fr/filter/test/1",
        })

        captured = {}

        def fake_get_pending(site_filter=None, limit=50):
            captured["site_filter"] = site_filter
            return []

        with patch("scrapers.enricher.get_pending_annonces", side_effect=fake_get_pending):
            from scrapers.enricher import enrich_annonces
            enrich_annonces(site_filter="SeLoger", limit=10)

        assert captured.get("site_filter") == "SeLoger"
