# tests/test_bienici.py
# =========================
# Sprint 15.7 — source Bien'ici (API JSON) et modèle commun Listing
# =========================

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from config import SEARCH_PROFILES
from scrapers.bienici import (
    BienIciScraper, ad_url, build_filters, parse_ad, pick_zone_ids,
)

ENAC = SEARCH_PROFILES["enac"]
BLAGNAC = SEARCH_PROFILES["blagnac"]

# Annonce au format attendu de realEstateAds[] (forme simplifiée)
AD = {
    "id": "ag311234-418273645",
    "title": "Appartement 2 pièces 38 m²",
    "description": "T2 lumineux&nbsp;proche métro Saint-Agne.<br>Cuisine équipée, cave.<br/>Libre au 1er décembre.",
    "price": 450,
    "charges": 40,
    "safetyDeposit": 410,
    "agencyRentalFee": 380,
    "surfaceArea": 38,
    "roomsQuantity": 2,
    "bedroomsQuantity": 1,
    "floor": 3,
    "hasElevator": True,
    "isFurnished": False,
    "energyClassification": "D",
    "greenhouseGazClassification": "B",
    "propertyType": "flat",
    "adType": "rent",
    "city": "Toulouse",
    "postalCode": "31400",
    "district": {"name": "Saint-Agne"},
    "photos": [{"url": "https://file.bienici.com/photo/a.jpg"},
               {"url_photo": "https://file.bienici.com/photo/b.jpg"},
               {"url": "https://file.bienici.com/photo/a.jpg"}],
    "blurInfo": {"type": "exact", "position": {"lat": 43.5822, "lon": 1.4573}},
    "publicationDate": "2026-11-10T08:12:44.000Z",
    "adCreatedByPro": True,
    "availableDate": "2026-12-01T00:00:00.000Z",
    "hasBalcony": True,
}


def _ad(ad_id, **overrides):
    return {**AD, "id": ad_id, **overrides}


class TestParseAd:

    def test_all_fields(self):
        l = parse_ad(AD)
        assert l.site == "Bien'ici"
        assert l.url == "https://www.bienici.com/annonce/location/toulouse/appartement/2pieces/ag311234-418273645"
        assert (l.title, l.price, l.location_raw) == (AD["title"], 450, "Toulouse 31400 (Saint-Agne)")
        assert (l.surface_m2, l.nb_rooms, l.nb_bedrooms, l.floor) == (38.0, 2, 1, 3)
        assert (l.elevator, l.furnished, l.dpe_rating, l.ges_rating) == (True, False, "D", "B")
        assert (l.charges, l.charges_included, l.deposit) == (40, True, 410)
        assert l.description == "T2 lumineux\xa0proche métro Saint-Agne.\nCuisine équipée, cave.\nLibre au 1er décembre."
        assert l.photos == ["https://file.bienici.com/photo/a.jpg", "https://file.bienici.com/photo/b.jpg"]
        assert (l.lat, l.lon, l.geo_precision) == (43.5822, 1.4573, "exact")
        assert (l.publisher_type, l.published_at) == ("agency", "2026-11-10")
        assert l.extra_attributes["agencyRentalFee"] == 380 and l.extra_attributes["hasBalcony"] is True

    def test_blurred_position_is_approx(self):
        l = parse_ad(_ad("x1", blurInfo={"type": "disk", "radius": 300,
                                         "centroid": {"lat": 43.6, "lon": 1.44}}))
        assert (l.lat, l.geo_precision) == (43.6, "approx")

    def test_odd_values(self):
        l = parse_ad(_ad("x2", price=[620, 710], energyClassification="NS",
                         greenhouseGazClassification="", isFurnished=None, description="court",
                         blurInfo=None, adCreatedByPro=None, accountType="particulier",
                         isPriceIncludingCharges=False))
        assert l.price == 620
        assert (l.dpe_rating, l.ges_rating, l.furnished, l.description) == (None, None, None, None)
        assert l.lat is None and l.publisher_type == "individual"
        assert l.charges_included is False

    def test_unusable(self):
        assert parse_ad(_ad(None)) is None
        assert parse_ad(_ad("x3", price=None)) is None

    def test_url_fallback(self):
        assert ad_url({"id": "abc", "city": "Toulouse"}) == "https://www.bienici.com/annonce/abc"


class TestListing:

    def test_api_listing_is_complete_even_without_description(self):
        annonce = parse_ad(_ad("x4", description=None)).to_annonce()
        from utils.validation import validate_annonce
        assert validate_annonce(annonce) is None
        d = annonce["details"]
        assert d["enrichment_status"] == "done"          # source « authoritative » : pas de visite
        assert d["extraction_source"] == "api"
        assert d["field_sources"]["surface_m2"] == "api"
        assert (annonce["lat"], annonce["geo_precision"], annonce["nb_rooms"]) == (43.5822, "exact", 2)
        assert json.loads(annonce["photos"]) == ["https://file.bienici.com/photo/a.jpg"]
        assert len(d["photos"]) == 2


class TestFilters:

    def test_enac(self):
        f = build_filters(ENAC, ["-35735"], page=2)
        assert (f["filterType"], f["propertyType"], f["zoneIdsByTypes"]) == ("rent", ["flat"], {"zoneIds": ["-35735"]})
        assert (f["minPrice"], f["maxPrice"]) == (ENAC.min_rent_eur, ENAC.max_rent_eur)
        assert (f["page"], f["from"]) == (2, f["size"])
        assert (f["sortBy"], f["sortOrder"]) == ("publicationDate", "desc")
        assert "minRooms" not in f

    def test_blagnac_without_budget(self):
        f = build_filters(BLAGNAC, ["1"], page=1)
        assert f["propertyType"] == ["flat", "house"]
        assert "maxPrice" not in f and "minPrice" not in f


class TestZones:

    SUGGEST = [
        {"name": "Toulouse (31)", "zoneIds": ["-111"], "type": "department"},
        {"name": "Toulouse", "zoneIds": ["-35735"], "type": "city"},
    ]

    def test_pick_exact_name(self):
        assert pick_zone_ids("Toulouse", self.SUGGEST) == ["-35735"]

    def test_pick_first_otherwise(self):
        assert pick_zone_ids("Saint-Agne", self.SUGGEST) == ["-111"]
        assert pick_zone_ids("X", []) == [] and pick_zone_ids("X", {"error": 1}) == []

    def test_resolution_cached(self, tmp_path):
        cache = tmp_path / "zones.json"
        scraper = BienIciScraper(ENAC)
        with patch.object(scraper, "get_json", return_value=self.SUGGEST) as get, \
             patch("scrapers.api_base.time.sleep"):
            ids = scraper.zone_ids(cache_file=cache)
        assert get.call_count == len(ENAC.bienici_places)
        assert ids  # dédoublonnés
        again = BienIciScraper(ENAC)
        with patch.object(again, "get_json") as get2:
            assert again.zone_ids(cache_file=cache) == ids
        get2.assert_not_called()

    def test_explicit_zone_ids(self):
        from dataclasses import replace
        scraper = BienIciScraper(replace(ENAC, bienici_zone_ids=("-1", "-2")))
        with patch.object(scraper, "get_json") as get:
            assert scraper.zone_ids() == ["-1", "-2"]
        get.assert_not_called()


class TestScrape:

    def _scraper(self, pages, page_size=2):
        scraper = BienIciScraper(ENAC)
        responses = iter(pages)

        def get_json(url, params=None, timeout=30):
            scraper._requests += 1
            r = next(responses)
            if isinstance(r, Exception):
                raise r
            return r

        patches = [
            patch.object(scraper, "zone_ids", return_value=["-35735"]),
            patch.object(scraper, "get_json", side_effect=get_json),
            patch("scrapers.bienici.BIENICI_PAGE_SIZE", page_size),
            patch("scrapers.api_base.time.sleep"),
        ]
        return scraper, patches

    def _run(self, pages, **kw):
        scraper, patches = self._scraper(pages, **kw)
        for p in patches:
            p.start()
        try:
            return scraper.scrape()
        finally:
            for p in patches:
                p.stop()

    def test_pages_until_short_page(self):
        results = self._run([
            {"total": 3, "realEstateAds": [_ad("a"), _ad("b")]},
            {"total": 3, "realEstateAds": [_ad("c"), _ad("a")]},   # « a » déjà vu
        ])
        assert [r["url"].rsplit("/", 1)[1] for r in results] == ["a", "b", "c"]

    def test_blocked_keeps_previous_pages(self):
        from scrapers.api_base import ApiBlocked
        with patch("scrapers.antibot.record_block") as record:
            results = self._run([{"total": 9, "realEstateAds": [_ad("a"), _ad("b")]}, ApiBlocked("HTTP 403")])
        assert len(results) == 2
        record.assert_called_once_with("Bien'ici")

    def test_unexpected_format(self):
        assert self._run([{"error": "bad request"}]) == []

    def test_unconfigured_profile(self):
        from dataclasses import replace
        assert BienIciScraper(replace(ENAC, bienici_places=())).scrape() == []

    def test_http_403_raises_blocked(self):
        from scrapers.api_base import ApiBlocked
        scraper = BienIciScraper(ENAC)
        response = MagicMock(status_code=403)
        with patch("requests.Session.get", return_value=response), pytest.raises(ApiBlocked):
            scraper.get_json("https://www.bienici.com/realEstateAds.json")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@pytest.fixture
def db(temp_db):
    from storage.sqlite import init_db
    init_db()
    return temp_db


def _row(db, url):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM annonces WHERE url = ?", (url,)).fetchone())
    conn.close()
    return row


def test_pipeline_stores_complete_annonce(db):
    from pipeline import process_annonces
    from storage.sqlite import get_pending_annonces

    annonce = parse_ad(AD).to_annonce()
    with patch("filters.price_and_distance.geocode_address") as geocode:
        stats = process_annonces([annonce], "Bien'ici")
    geocode.assert_not_called()
    assert (stats.inserted, stats.prefilled, stats.new_by_profile["enac"]) == (1, 1, 1)
    row = _row(db, annonce["url"])
    assert (row["site"], row["enrichment_status"], row["extraction_source"]) == ("Bien'ici", "done", "api")
    assert (row["charges_included"], row["deposit"], row["geo_precision"]) == (1, 410, "exact")
    assert get_pending_annonces(limit=10) == []


def test_cross_site_duplicate_uses_surface_from_details(db):
    """Même T2 sur LBC (déjà en base) et Bien'ici : doublon, surface comparée via details."""
    from pipeline import process_annonces
    from tests.test_lbc_json import AD as LBC_AD
    from scrapers.detail_extractors.lbc_json import search_ad_to_annonce

    lbc = search_ad_to_annonce({**LBC_AD, "price": [450],
                                "location": {**LBC_AD["location"], "city_label": "Toulouse 31400"}})
    with patch("filters.price_and_distance.geocode_address"):
        process_annonces([lbc], "LeBonCoin")
        stats = process_annonces([parse_ad(AD).to_annonce()], "Bien'ici")
    assert stats.duplicates == 1

    other_surface = parse_ad(_ad("ag-other", surfaceArea=70)).to_annonce()
    with patch("filters.price_and_distance.geocode_address"):
        assert process_annonces([other_surface], "Bien'ici").duplicates == 0


def test_no_cooldown_before_api_source(db):
    from pipeline import run_scraping

    class Api:
        requires_cooldown = False

        def __init__(self, profile, unattended=False):
            self.profile = profile

        def site_name(self):
            return "Bien'ici"

        def search_url(self):
            return "https://api"

        def scrape(self):
            return []

    sleep = MagicMock()
    with patch("scrapers.get_scraper_class", return_value=Api), \
         patch("reporting.generator.generate_summary_reports"):
        run_scraping([ENAC, BLAGNAC], ["bienici"], sleep=sleep)
    sleep.assert_not_called()


def test_cli_accepts_bienici():
    from main import build_parser
    assert build_parser().parse_args(["scrape", "--site", "bienici"]).sites == ["bienici"]
