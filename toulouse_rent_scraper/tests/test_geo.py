# tests/test_geo.py
# =========================
# Tests du géocodage (Nominatim mocké)
# =========================

import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import geo.distance as geo
from geo.distance import build_queries, geocode_address


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("geo.distance.time.sleep"):
        yield


def _loc(lat=43.55, lon=1.47):
    return SimpleNamespace(latitude=lat, longitude=lon)


class TestBuildQueries:
    def test_district_gets_toulouse_suffix(self):
        assert build_queries("Rangueil") == ["Rangueil, Toulouse, France"]

    def test_commune_does_not_get_toulouse_suffix(self):
        assert build_queries("Ramonville-Saint-Agne")[0] == "Ramonville-Saint-Agne, France"
        assert build_queries("Blagnac")[0] == "Blagnac, France"

    def test_postcode_does_not_get_toulouse_suffix_and_is_last_resort(self):
        queries = build_queries("Muret 31600 Centre-ville")
        assert queries[0] == "Muret 31600 Centre-ville, France"
        assert "Muret 31600, France" in queries
        assert queries[-1] == "31600, France"

    def test_noise_removed(self):
        assert "Blagnac, France" in build_queries("Blagnac proche aéroport")


class TestGeocodeCache:
    def test_success_is_cached(self, temp_db):
        with patch.object(geo.geolocator, "geocode", return_value=_loc()) as m:
            assert geocode_address("Rangueil") == (43.55, 1.47)
            assert geocode_address("Rangueil") == (43.55, 1.47)
        assert m.call_count == 1

    def test_fallback_query_used(self, temp_db):
        with patch.object(geo.geolocator, "geocode", side_effect=[None, _loc(43.46, 1.33)]) as m:
            assert geocode_address("Muret 31600 Centre-ville") == (43.46, 1.33)
        assert m.call_count == 2

    def test_failure_is_negatively_cached(self, temp_db):
        with patch.object(geo.geolocator, "geocode", return_value=None) as m:
            assert geocode_address("Lieu introuvable") is None
            calls = m.call_count
            assert geocode_address("Lieu introuvable") is None
        assert m.call_count == calls  # aucun nouvel appel réseau

    def test_negative_cache_expires(self, temp_db):
        with patch.object(geo.geolocator, "geocode", return_value=None):
            geocode_address("Lieu introuvable")
        old = (datetime.now() - timedelta(days=geo.GEOCODE_NEGATIVE_TTL_DAYS + 1)).isoformat(sep=" ")
        with sqlite3.connect(temp_db) as con:
            con.execute("UPDATE geocoding_cache SET cached_at = ?", (old,))
        with patch.object(geo.geolocator, "geocode", return_value=_loc()) as m:
            assert geocode_address("Lieu introuvable") == (43.55, 1.47)
        assert m.call_count == 1

    def test_network_error_not_cached(self, temp_db):
        with patch.object(geo.geolocator, "geocode", side_effect=RuntimeError("boom")):
            assert geocode_address("Saouzelong") is None
        with patch.object(geo.geolocator, "geocode", return_value=_loc()) as m:
            assert geocode_address("Saouzelong") == (43.55, 1.47)
        assert m.call_count == 1

    def test_empty_address(self, temp_db):
        assert geocode_address("") is None
        assert geocode_address("   ") is None
