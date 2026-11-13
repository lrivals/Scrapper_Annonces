# tests/test_lbc_search_json.py
# =========================
# Sprint 15.2 — annonces LeBonCoin complètes dès la page de recherche (__NEXT_DATA__)
# =========================

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from scrapers.detail_extractors.lbc_json import (
    extract_next_data, find_search_ads, list_id_from_url, search_ad_to_annonce, search_annonces_from_html,
)
from tests.test_lbc_json import AD


def _ad(list_id, **overrides):
    return {**AD, "list_id": list_id, "url": f"https://www.leboncoin.fr/ad/locations/{list_id}",
            **overrides}


def _search_html(ads, path=("props", "pageProps", "searchData", "ads")):
    data = ads
    for key in reversed(path):
        data = {key: data}
    return ('<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data) + "</script></html>")


class TestSearchJson:

    def test_ads_found_at_usual_place(self):
        html = _search_html([_ad(1111111), _ad(2222222)])
        ads = find_search_ads(extract_next_data(html))
        assert [a["list_id"] for a in ads] == [1111111, 2222222]

    def test_ads_found_elsewhere(self):
        html = _search_html([_ad(1111111), _ad(2222222), {"pub": True}],
                            path=("props", "pageProps", "initialState", "results", "list"))
        assert len(search_annonces_from_html(html)) == 2

    @pytest.mark.parametrize("url,expected", [
        ("https://www.leboncoin.fr/ad/locations/2875512345", "2875512345"),
        ("/ad/locations/2875512345", "2875512345"),
        ("https://www.leboncoin.fr/locations/2875512345.htm?ca=16", "2875512345"),
        ("https://www.leboncoin.fr/recherche?category=10", None),
        (None, None),
    ])
    def test_list_id_from_url(self, url, expected):
        assert list_id_from_url(url) == expected

    def test_annonce_for_pipeline(self):
        from utils.validation import validate_annonce

        a = search_ad_to_annonce(_ad(1111111, location={**AD["location"], "city_label": "Toulouse 31400"}))
        assert validate_annonce(a) is None
        assert (a["site"], a["title"], a["price"]) == ("LeBonCoin", AD["subject"], 640)
        assert a["location_raw"] == "Toulouse 31400"
        assert (a["lat"], a["lon"], a["geo_precision"]) == (43.5822, 1.4573, "exact")
        assert a["nb_rooms"] == 2
        assert json.loads(a["photos"]) == ["https://img.leboncoin.fr/a.jpg?rule=ad-large"]
        d = a["details"]
        assert (d["surface_m2"], d["dpe_rating"], d["enrichment_status"]) == (38.0, "D", "done")
        assert d["extraction_source"] == "search_json"
        assert "lat" not in d and "price" not in d

    def test_relative_url_and_missing_url(self):
        assert search_ad_to_annonce({**_ad(1), "url": "/ad/locations/1234567"})["url"] \
            == "https://www.leboncoin.fr/ad/locations/1234567"
        no_url = {k: v for k, v in _ad(7654321).items() if k != "url"}
        assert search_ad_to_annonce(no_url)["url"].endswith("/ad/locations/7654321")

    def test_incomplete_ad_stays_pending(self):
        a = search_ad_to_annonce(_ad(1111111, body=None))
        assert "enrichment_status" not in a["details"]
        assert a["details"]["surface_m2"] == 38.0

    def test_ad_without_price_skipped(self):
        assert search_annonces_from_html(_search_html([_ad(1111111, price=[]), _ad(2222222)])) \
            == [search_ad_to_annonce(_ad(2222222))]


# ---------------------------------------------------------------------------
# Scraper : JSON d'abord, cartes DOM pour le reste
# ---------------------------------------------------------------------------

def _card(list_id):
    card = MagicMock()
    card.get_attribute.side_effect = lambda name: f"/ad/locations/{list_id}" if name == "href" else None
    return card


@pytest.fixture
def scraper():
    from scrapers.leboncoin import LeBonCoinScraper
    s = LeBonCoinScraper()
    s.results = []
    with patch.object(s, "human_scroll"), patch("scrapers.base.time.sleep"):
        yield s


def _run(scraper, html, cards):
    page = MagicMock()
    page.content.return_value = html
    page.query_selector_all.return_value = cards
    with patch.object(scraper, "extract_annonce",
                      side_effect=lambda c: {"url": c.get_attribute("href"), "from": "dom"}) as extract:
        scraper._scrape_current_page(page, scraper.card_selector(), 1)
    return extract


def test_json_used_and_missing_cards_from_dom(scraper):
    html = _search_html([_ad(1111111), _ad(2222222)])
    extract = _run(scraper, html, [_card(1111111), _card(2222222), _card(3333333)])
    assert extract.call_count == 1                      # seule la carte absente du JSON
    assert [r.get("from", "json") for r in scraper.results] == ["json", "json", "dom"]


def test_stale_json_ignored(scraper):
    """Pagination côté client : le JSON décrit encore la page 1 → cartes DOM seulement."""
    html = _search_html([_ad(1111111), _ad(2222222)])
    extract = _run(scraper, html, [_card(4444444), _card(5555555), _card(1111111)])
    assert extract.call_count == 3
    assert all(r["from"] == "dom" for r in scraper.results)


def test_json_without_cards(scraper):
    _run(scraper, _search_html([_ad(1111111)]), [])
    assert len(scraper.results) == 1 and scraper.results[0]["details"]["surface_m2"] == 38.0


def test_no_json_falls_back_to_cards(scraper):
    extract = _run(scraper, "<html>pas de json</html>", [_card(1111111), _card(2222222)])
    assert extract.call_count == 2


def test_detail_visit_kept_when_disabled(scraper):
    with patch("scrapers.leboncoin.LBC_SEARCH_JSON_SKIPS_DETAIL", False):
        _run(scraper, _search_html([_ad(1111111)]), [_card(1111111)])
    assert "enrichment_status" not in scraper.results[0]["details"]


# ---------------------------------------------------------------------------
# Pipeline : stockage des détails, GPS exact, pas de visite de détail
# ---------------------------------------------------------------------------

def _row(db, url):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM annonces WHERE url = ?", (url,)).fetchone())
    conn.close()
    return row


@pytest.fixture
def db(temp_db):
    from storage.sqlite import init_db
    init_db()
    return temp_db


def test_pipeline_stores_details_without_geocoding(db):
    from pipeline import process_annonces
    from storage.sqlite import get_pending_annonces

    annonce = search_ad_to_annonce(_ad(1111111, price=[450]))
    with patch("filters.price_and_distance.geocode_address") as geocode:
        stats = process_annonces([annonce], "LeBonCoin")
    geocode.assert_not_called()
    assert (stats.inserted, stats.prefilled) == (1, 1)
    assert stats.new_by_profile["enac"] == 1

    row = _row(db, annonce["url"])
    assert (row["surface_m2"], row["ges_rating"], row["enrichment_status"]) == (38.0, "B", "done")
    assert (row["geo_precision"], row["lat"], row["extraction_source"]) == ("exact", 43.5822, "search_json")
    assert row["enriched_at"] is not None
    assert get_pending_annonces(limit=10) == []          # pas de visite de la page de détail

    conn = sqlite3.connect(db)
    dist = conn.execute("SELECT distance_km FROM annonce_profiles WHERE profile = 'enac'").fetchone()[0]
    conn.close()
    assert dist < 3.0


def test_incomplete_details_still_visited(db):
    from pipeline import process_annonces
    from storage.sqlite import get_pending_annonces

    annonce = search_ad_to_annonce(_ad(1111111, price=[450], body=None))
    with patch("filters.price_and_distance.geocode_address"):
        process_annonces([annonce], "LeBonCoin")
    row = _row(db, annonce["url"])
    assert (row["surface_m2"], row["enrichment_status"]) == (38.0, "pending")
    assert [a["url"] for a in get_pending_annonces(limit=10)] == [annonce["url"]]


def test_enriched_annonce_not_overwritten(db):
    from pipeline import process_annonces
    from storage.sqlite import update_annonce_enrichment

    first = search_ad_to_annonce(_ad(1111111, price=[450]))
    with patch("filters.price_and_distance.geocode_address"):
        process_annonces([first], "LeBonCoin")
    update_annonce_enrichment(first["url"], {"description": "Description complète de la page de détail."})

    again = search_ad_to_annonce(_ad(1111111, price=[450], body="Texte tronqué de la recherche…"))
    with patch("filters.price_and_distance.geocode_address"):
        stats = process_annonces([again], "LeBonCoin")
    assert stats.prefilled == 0
    assert _row(db, first["url"])["description"].startswith("Description complète")


def test_approx_json_position_used_when_geocoding_fails(db):
    from pipeline import process_annonces

    annonce = search_ad_to_annonce(_ad(1111111, price=[450], location={
        "city_label": "Ramonville 31520", "lat": 43.5455, "lng": 1.4745, "is_shape": True}))
    with patch("filters.price_and_distance.geocode_address", return_value=None):
        stats = process_annonces([annonce], "LeBonCoin")
    assert stats.kept == 1
    assert _row(db, annonce["url"])["geo_precision"] == "approx"


def test_search_json_counts_as_json_for_health():
    from storage.quality import json_rate
    assert json_rate([{"extraction_source": "search_json"}, {"extraction_source": "dom"}]) == 0.5


def test_notification_shows_specs():
    from notify.messages import _line
    line = _line({"title": "T2", "price": 450, "nb_rooms": 2, "surface_m2": 38.0,
                  "dpe_rating": "D", "distance_km": 2.4, "score": 71})
    assert "T2 38 m² DPE D" in line


def test_search_health_rows():
    from pipeline import search_health_rows
    from storage.quality import check_fill_rates

    good = [search_ad_to_annonce(_ad(1000000 + i)) for i in range(6)]
    assert check_fill_rates({"LeBonCoin": search_health_rows(good, "LeBonCoin")}) == []

    cards_only = [{"url": f"https://lbc/{i}", "photos": None} for i in range(6)]
    alerts = check_fill_rates({"LeBonCoin": search_health_rows(cards_only, "LeBonCoin")})
    assert any("JSON" in a for a in alerts)

    assert search_health_rows(cards_only, "SeLoger") == []   # site sans JSON de recherche : pas jugé
