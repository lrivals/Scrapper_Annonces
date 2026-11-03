# tests/test_profiles.py
# =========================
# Tests des profils de recherche (Sprint 14)
# =========================

import sqlite3
from unittest.mock import patch

import pytest

from config import SEARCH_PROFILES, LEBONCOIN_SEARCH_URL, SELOGER_SEARCH_URLS
from filters.price_and_distance import guess_rooms, match_profiles
from storage.sqlite import init_db, insert_annonce, upsert_annonce_profile

ENAC = SEARCH_PROFILES["enac"]
BLAGNAC = SEARCH_PROFILES["blagnac"]

# Coordonnées approximatives
RANGUEIL = (43.5615, 1.4630)          # ~1.4 km de l'ENAC
BLAGNAC_CENTRE = (43.6360, 1.3900)    # ~1.8 km de la Pl. Marcel Dassault
PURPAN = (43.6070, 1.4000)
SAINT_CYPRIEN = (43.5980, 1.4320)


def _annonce(price, title="Appartement", location="Quelque part"):
    return {
        "site": "LeBonCoin", "title": title, "price": f"{price} €",
        "location_raw": location, "url": f"https://lbc.fr/{price}-{title}",
    }


def _match(annonce, coords):
    with patch("filters.price_and_distance.geocode_address", return_value=coords) as geo:
        enriched, matches = match_profiles(annonce, [ENAC, BLAGNAC])
    return enriched, [p.key for p, _ in matches], geo


class TestConfig:
    def test_enac_profile_reproduces_legacy_urls(self):
        assert ENAC.leboncoin_search_url() == LEBONCOIN_SEARCH_URL
        assert ENAC.seloger_search_urls() == SELOGER_SEARCH_URLS

    def test_blagnac_leboncoin_url(self):
        url = BLAGNAC.leboncoin_search_url()
        assert "locations=Blagnac_31700__43.6417_1.3693" in url
        assert "price=550-750" in url
        assert "rooms=1-3" in url

    def test_blagnac_seloger_not_configured_yet(self):
        assert BLAGNAC.seloger_search_urls() == []

    def test_scrapers_follow_profile(self):
        pytest.importorskip("playwright")
        from scrapers.leboncoin import LeBonCoinScraper
        from scrapers.seloger import SeLogerScraper
        assert LeBonCoinScraper(BLAGNAC).search_url() == BLAGNAC.leboncoin_search_url()
        assert SeLogerScraper(BLAGNAC).search_url() is None
        assert LeBonCoinScraper().profile.key == "enac"


class TestGuessRooms:
    @pytest.mark.parametrize("title,expected", [
        ("Studio meublé", 1),
        ("Appartement T2 Blagnac", 2),
        ("Appartement 3 pièces 62 m²", 3),
        ("F1 bis", 1),
        ("Location appartement", None),
    ])
    def test_from_title(self, title, expected):
        assert guess_rooms({"title": title}) == expected

    def test_enriched_value_wins(self):
        assert guess_rooms({"title": "Studio", "nb_rooms": 2}) == 2


class TestMatchProfiles:
    def test_cheap_studio_near_enac_matches_enac_only(self):
        enriched, keys, _ = _match(_annonce(480, "Studio"), RANGUEIL)
        assert keys == ["enac"]
        assert enriched["price"] == 480
        assert (enriched["lat"], enriched["lon"]) == RANGUEIL
        assert enriched["distance_enac_km"] < 2

    def test_t2_700_in_blagnac_matches_blagnac_only(self):
        _, keys, _ = _match(_annonce(700, "Appartement T2"), BLAGNAC_CENTRE)
        assert keys == ["blagnac"]

    def test_between_budgets_matches_nothing_without_geocoding(self):
        enriched, keys, geo = _match(_annonce(520, "T1"), PURPAN)
        assert enriched is None and keys == []
        geo.assert_not_called()  # aucun profil n'accepte 520 € : pas d'appel Nominatim

    def test_t1_600_saint_cyprien_matches_blagnac(self):
        _, keys, _ = _match(_annonce(600, "Appartement T1"), SAINT_CYPRIEN)
        assert keys == ["blagnac"]

    def test_too_many_rooms_rejected_by_blagnac(self):
        _, keys, geo = _match(_annonce(720, "Maison 5 pièces"), BLAGNAC_CENTRE)
        assert keys == []
        geo.assert_not_called()

    def test_outside_radius(self):
        _, keys, _ = _match(_annonce(700, "T2"), RANGUEIL)  # ~10 km de Blagnac
        assert keys == []

    def test_price_with_thousands_separator_rejected(self):
        _, keys, _ = _match(_annonce("1 200", "T3"), BLAGNAC_CENTRE)
        assert keys == []

    def test_geocoding_failure(self):
        enriched, keys, _ = _match(_annonce(700, "T2"), None)
        assert enriched is None and keys == []


class TestStorage:
    def _insert(self, url, **extra):
        insert_annonce({"site": "LeBonCoin", "title": "T2", "price": 700,
                        "location_raw": "Blagnac", "url": url, **extra})

    def test_upsert_is_new_once_per_profile(self, temp_db):
        init_db()
        self._insert("https://lbc.fr/1")
        assert upsert_annonce_profile("https://lbc.fr/1", "blagnac", 2.0) is True
        assert upsert_annonce_profile("https://lbc.fr/1", "blagnac", 2.5) is False
        assert upsert_annonce_profile("https://lbc.fr/1", "enac", 9.0) is True
        with sqlite3.connect(temp_db) as con:
            rows = con.execute(
                "SELECT profile, distance_km FROM annonce_profiles ORDER BY profile"
            ).fetchall()
        assert rows == [("blagnac", 2.5), ("enac", 9.0)]

    def test_upsert_unknown_url(self, temp_db):
        init_db()
        assert upsert_annonce_profile("https://nope", "enac", 1.0) is False

    def test_coordinates_stored(self, temp_db):
        init_db()
        self._insert("https://lbc.fr/1", lat=43.63, lon=1.38)
        with sqlite3.connect(temp_db) as con:
            assert con.execute("SELECT lat, lon FROM annonces").fetchone() == (43.63, 1.38)

    def test_legacy_annonces_migrated_to_enac(self, temp_db):
        init_db()
        self._insert("https://old/1", distance_enac_km=3.3)
        with sqlite3.connect(temp_db) as con:
            con.execute("DELETE FROM annonce_profiles")  # base d'avant le Sprint 14
            con.execute(
                "INSERT INTO geocoding_cache (address, latitude, longitude) VALUES ('Blagnac', 43.6, 1.39)"
            )
        init_db()
        init_db()  # idempotent
        with sqlite3.connect(temp_db) as con:
            assert con.execute(
                "SELECT profile, distance_km FROM annonce_profiles"
            ).fetchall() == [("enac", 3.3)]
            assert con.execute("SELECT lat, lon FROM annonces").fetchone() == (43.6, 1.39)


class TestExport:
    def test_one_row_per_profile(self, temp_db, monkeypatch):
        import reporting.exporter as exporter
        monkeypatch.setattr(exporter, "DB_PATH", temp_db)
        init_db()
        insert_annonce({"site": "LeBonCoin", "title": "T1", "price": 500,
                        "location_raw": "Purpan", "url": "https://lbc.fr/1"})
        upsert_annonce_profile("https://lbc.fr/1", "enac", 8.0)
        upsert_annonce_profile("https://lbc.fr/1", "blagnac", 4.0)
        rows = exporter._fetch_all_annonces()
        assert [(r["profile"], r["distance_km"]) for r in rows] == [("blagnac", 4.0), ("enac", 8.0)]


class TestCli:
    def test_selected_profiles(self):
        import main
        assert [p.key for p in main.selected_profiles(None)] == ["enac", "blagnac"]
        assert [p.key for p in main.selected_profiles(["blagnac", "blagnac"])] == ["blagnac"]
