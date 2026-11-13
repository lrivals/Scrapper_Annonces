# tests/test_cleaner.py
# =========================
# Tests unitaires pour le cleaner d'annonces expirées
# =========================

import sqlite3
from unittest.mock import patch

import pytest
import requests

from storage.cleaner import check_expired_annonces, _check_url_alive


class TestCheckUrlAlive:
    @patch("storage.cleaner.requests.head")
    def test_url_alive_returns_true(self, mock_head):
        mock_head.return_value.status_code = 200
        assert _check_url_alive("https://example.com") is True

    @patch("storage.cleaner.requests.head")
    def test_url_404_returns_false(self, mock_head):
        mock_head.return_value.status_code = 404
        assert _check_url_alive("https://example.com") is False

    @patch("storage.cleaner.requests.get")
    @patch("storage.cleaner.requests.head")
    def test_url_405_falls_back_to_get(self, mock_head, mock_get):
        mock_head.return_value.status_code = 405
        mock_get.return_value.status_code = 200
        assert _check_url_alive("https://example.com") is True
        mock_get.assert_called_once()

    @patch("storage.cleaner.requests.head", side_effect=requests.ConnectionError("timeout"))
    def test_url_exception_returns_false(self, mock_head):
        assert _check_url_alive("https://example.com") is False


class TestCheckExpiredAnnonces:
    @pytest.fixture
    def test_db(self, tmp_path):
        db_path = tmp_path / "test.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE annonces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site TEXT, title TEXT, price INTEGER,
                location_raw TEXT, distance_enac_km REAL,
                url TEXT UNIQUE, scraped_at TIMESTAMP,
                created_at TIMESTAMP, status TEXT DEFAULT 'active'
            )
        """)
        conn.execute(
            "INSERT INTO annonces (site, title, price, url, status) VALUES (?, ?, ?, ?, ?)",
            ("SeLoger", "Studio OK", 430, "https://example.com/active", "active"),
        )
        conn.execute(
            "INSERT INTO annonces (site, title, price, url, status) VALUES (?, ?, ?, ?, ?)",
            ("SeLoger", "Studio Gone", 350, "https://example.com/gone", "active"),
        )
        conn.execute(
            "INSERT INTO annonces (site, title, price, url, status) VALUES (?, ?, ?, ?, ?)",
            ("SeLoger", "Already expired", 300, "https://example.com/old", "expired"),
        )
        conn.commit()
        conn.close()
        return db_path

    @patch("storage.cleaner.RATE_LIMIT_DELAY", 0)
    @patch("storage.cleaner.time.sleep")
    @patch("storage.cleaner._check_url_alive")
    @patch("storage.cleaner.get_connection")
    def test_marks_dead_urls_as_expired(self, mock_conn, mock_alive, mock_sleep, test_db):
        mock_conn.return_value = sqlite3.connect(test_db)
        # Premier URL active, deuxième morte
        mock_alive.side_effect = [True, False]

        summary = check_expired_annonces()

        assert summary["checked"] == 2  # only active ones
        assert summary["expired"] == 1
        assert summary["still_active"] == 1

        # Vérifier en DB
        conn = sqlite3.connect(test_db)
        statuses = conn.execute(
            "SELECT url, status FROM annonces ORDER BY id"
        ).fetchall()
        conn.close()

        assert statuses[0] == ("https://example.com/active", "active")
        assert statuses[1] == ("https://example.com/gone", "expired")
        assert statuses[2] == ("https://example.com/old", "expired")  # inchangé

    @patch("storage.cleaner.RATE_LIMIT_DELAY", 0)
    @patch("storage.cleaner.time.sleep")
    @patch("storage.cleaner._check_url_alive", return_value=True)
    @patch("storage.cleaner.get_connection")
    def test_all_active(self, mock_conn, mock_alive, mock_sleep, test_db):
        mock_conn.return_value = sqlite3.connect(test_db)

        summary = check_expired_annonces()

        assert summary["expired"] == 0
        assert summary["still_active"] == 2


def test_page_shows_expired_uses_visible_text_and_embedded_ad():
    """Régression 2026-11-13 : motifs d'erreur présents dans les scripts d'une page LBC en ligne."""
    import json
    from unittest.mock import MagicMock
    from storage.cleaner import page_shows_expired

    def page(html, text):
        p = MagicMock()
        p.content.return_value = html
        p.inner_text.return_value = text
        return p

    scripts = '<script>{"t":"Annonce introuvable — Page introuvable"}</script>'
    assert not page_shows_expired(page(scripts, "T3 duplex 68 m²"))
    assert page_shows_expired(page(scripts, "Cette annonce n'est plus en ligne"))

    next_data = {"props": {"pageProps": {"ad": {
        "list_id": 3279424665, "subject": "T3", "body": "x" * 40, "price": [900], "attributes": [],
    }}}}
    live = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
    assert not page_shows_expired(page(live, "Page introuvable"))   # l'annonce est dans le JSON
