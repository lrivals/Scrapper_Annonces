# tests/test_pipeline.py
# =========================
# Pipeline de scraping avec scrapers et géocodage simulés
# =========================

from unittest.mock import MagicMock, patch

import pytest

from config import SEARCH_PROFILES
from pipeline import RunStats, process_annonces, run_scraping
from storage.sqlite import init_db

ENAC = SEARCH_PROFILES["enac"]
BLAGNAC = SEARCH_PROFILES["blagnac"]


def _raw(n, price=450, title="Studio", site="LeBonCoin"):
    return {"site": site, "title": f"{title} {n}", "price": f"{price} €",
            "location_raw": "Rangueil", "url": f"https://lbc.fr/{site}/{n}"}


def _matches(annonce, profiles=None):
    """match_profiles simulé : ENAC si prix ≤ 500, sinon Blagnac."""
    price = int(annonce["price"].split()[0])
    enriched = {**annonce, "price": price, "lat": 43.56, "lon": 1.46, "distance_enac_km": 1.0}
    if price > 750:
        return None, []
    return enriched, [(ENAC if price <= 500 else BLAGNAC, 1.5)]


@pytest.fixture
def db(temp_db):
    init_db()
    with patch("filters.price_and_distance.match_profiles", side_effect=_matches):
        yield temp_db


def test_process_counts_new_then_unchanged(db):
    raw = [_raw(1), _raw(2, price=700), _raw(3, price=900)]
    stats = process_annonces(raw, "LeBonCoin")
    assert (stats.raw, stats.kept, stats.rejected, stats.inserted) == (3, 2, 1, 2)
    assert stats.new_by_profile == {"enac": 1, "blagnac": 1}

    again = process_annonces(raw, "LeBonCoin")
    assert (again.inserted, again.unchanged) == (0, 2)
    assert not again.new_by_profile


def test_process_rejects_invalid(db):
    stats = process_annonces([{"site": "LeBonCoin", "title": "", "price": "400 €",
                               "location_raw": "x", "url": "https://lbc.fr/x"}], "LeBonCoin")
    assert stats.validation_errors == 1 and stats.rejected == 1


def test_runstats_addition():
    total = RunStats(raw=1, inserted=1)
    total.new_by_profile["enac"] = 1
    other = RunStats(raw=2, duplicates=1)
    other.new_by_profile["enac"] = 2
    total += other
    assert (total.raw, total.inserted, total.duplicates) == (3, 1, 1)
    assert total.new_by_profile["enac"] == 3


def _fake_scraper_class(results_by_profile):
    class Fake:
        def __init__(self, profile):
            self.profile = profile

        def site_name(self):
            return "LeBonCoin"

        def search_url(self):
            return None if self.profile.key == "unconfigured" else "https://lbc.fr/search"

        def scrape(self):
            return results_by_profile.get(self.profile.key, [])
    return Fake


def test_run_scraping_loops_profiles_and_pauses_between_searches(db):
    Fake = _fake_scraper_class({"enac": [_raw(1)], "blagnac": [_raw(2, price=700)]})
    sleep = MagicMock()
    with patch("scrapers.get_scraper_class", return_value=Fake), \
         patch("reporting.generator.generate_summary_reports") as reports:
        total = run_scraping([ENAC, BLAGNAC], ["leboncoin"], sleep=sleep)
    assert total.inserted == 2
    assert total.new_by_profile == {"enac": 1, "blagnac": 1}
    assert sleep.call_count == 1          # une pause entre les deux recherches
    reports.assert_called_once()


def test_run_scraping_skips_unconfigured_site_without_pause(db):
    Fake = _fake_scraper_class({"enac": [_raw(1)]})
    unconfigured = MagicMock(key="unconfigured", label="X")
    sleep = MagicMock()
    with patch("scrapers.get_scraper_class", return_value=Fake), \
         patch("reporting.generator.generate_summary_reports"):
        total = run_scraping([unconfigured, ENAC], ["leboncoin"], sleep=sleep)
    assert total.inserted == 1
    sleep.assert_not_called()
