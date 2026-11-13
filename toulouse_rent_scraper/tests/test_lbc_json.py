# tests/test_lbc_json.py
# =========================
# Sprint 15.1 — extraction LeBonCoin depuis __NEXT_DATA__, coordonnées exactes,
# santé de l'extraction (taux de remplissage)
# =========================

import json
import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from scrapers.detail_extractors.lbc_json import (
    extract_from_html, extract_next_data, find_ad, parse_ad,
)

# Annonce au format attendu de props.pageProps.ad (forme simplifiée d'une vraie page)
AD = {
    "list_id": 2875512345,
    "subject": "Appartement 2 pièces 38 m²",
    "body": "T2 lumineux proche métro Saint-Agne. Loyer 640 € dont 40 € de charges. "
            "Dépôt de garantie : 600 €. Libre au 1er décembre.",
    "price": [640],
    "first_publication_date": "2026-11-10 08:12:44",
    "images": {
        "urls": ["https://img.leboncoin.fr/a.jpg?rule=ad-image"],
        "urls_large": [
            "https://img.leboncoin.fr/a.jpg?rule=ad-large",
            "https://img.leboncoin.fr/b.jpg?rule=ad-large",
            "https://img.leboncoin.fr/a.jpg?rule=ad-large",
        ],
    },
    "attributes": [
        {"key": "real_estate_type", "value": "2", "value_label": "Appartement"},
        {"key": "square", "value": "38", "value_label": "38 m²"},
        {"key": "rooms", "value": "2", "value_label": "2"},
        {"key": "bedrooms", "value": "1", "value_label": "1"},
        {"key": "furnished", "value": "2", "value_label": "Non meublé"},
        {"key": "energy_rate", "value": "d", "value_label": "D"},
        {"key": "ges", "value": "b", "value_label": "B"},
        {"key": "floor_number", "value": "3", "value_label": "3"},
        {"key": "elevator", "value": "1", "value_label": "Oui"},
        {"key": "charges_included", "value": "1", "value_label": "Oui"},
    ],
    "location": {
        "city": "Toulouse", "zipcode": "31400", "lat": 43.5822, "lng": 1.4573,
        "source": "address", "is_shape": False,
    },
    "owner": {"type": "private", "name": "Marie"},
}


def _html(ad=AD, path=("props", "pageProps", "ad")):
    data = ad
    for key in reversed(path):
        data = {key: data}
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(data) + "</script></head><body>…</body></html>"
    )


class TestLocateAd:

    def test_next_data_parsed(self):
        assert extract_next_data(_html())["props"]["pageProps"]["ad"]["list_id"] == AD["list_id"]

    @pytest.mark.parametrize("html", [None, "", "<html>pas de json</html>",
                                      '<script id="__NEXT_DATA__">{tronqué</script>'])
    def test_absent_or_invalid(self, html):
        assert extract_next_data(html) is None
        assert extract_from_html(html) is None

    def test_ad_found_elsewhere_in_tree(self):
        html = _html(path=("props", "pageProps", "initialState", "adview", "ad"))
        assert find_ad(extract_next_data(html))["list_id"] == AD["list_id"]

    def test_non_ad_page(self):
        assert find_ad({"props": {"pageProps": {"searchData": {"total": 0}}}}) is None


class TestParseAd:

    def test_all_fields(self):
        r = parse_ad(AD)
        assert r["surface_m2"] == 38.0
        assert (r["nb_rooms"], r["nb_bedrooms"], r["floor"]) == (2, 1, 3)
        assert r["furnished"] is False            # « Non meublé » : plus de faux positif
        assert (r["dpe_rating"], r["ges_rating"]) == ("D", "B")
        assert r["elevator"] is True
        assert r["charges_included"] is True
        assert r["publisher_type"] == "individual"
        assert r["published_at"] == "2026-11-10"
        assert r["price"] == 640
        assert r["photos"] == [
            "https://img.leboncoin.fr/a.jpg?rule=ad-large",
            "https://img.leboncoin.fr/b.jpg?rule=ad-large",
        ]
        assert (r["lat"], r["lon"], r["geo_precision"]) == (43.5822, 1.4573, "exact")
        assert r["description"].startswith("T2 lumineux")
        assert r["extra_attributes"]["real_estate_type"] == "Appartement"

    def test_approximate_location(self):
        ad = {**AD, "location": {"lat": 43.6, "lng": 1.44, "source": "city", "is_shape": True}}
        assert parse_ad(ad)["geo_precision"] == "approx"

    def test_missing_and_odd_values(self):
        ad = {
            "list_id": 1, "subject": "x", "price": [],
            "attributes": [
                {"key": "energy_rate", "value": "v", "value_label": "Vierge"},
                {"key": "furnished", "value": "1", "value_label": "Meublé"},
                {"key": "floor_number", "value": "0", "value_label": "Rez-de-chaussée"},
                {"key": "square", "value": "27,5"},
            ],
            "location": {"lat": "pas un nombre"},
            "owner": {"type": "pro"},
        }
        r = parse_ad(ad)
        assert r["dpe_rating"] is None
        assert r["furnished"] is True
        assert r["floor"] == 0
        assert r["surface_m2"] == 27.5
        assert r["publisher_type"] == "agency"
        assert r["price"] is None and r["photos"] is None
        assert "lat" not in r


class TestLeBonCoinExtractDetail:

    def _page(self, html):
        page = MagicMock()
        page.title.return_value = "Annonce"
        page.content.return_value = html
        page.inner_text.return_value = ""
        page.query_selector.return_value = None
        page.query_selector_all.return_value = []
        return page

    def test_json_path_skips_dom(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = self._page(_html())
        result = extract_detail(page, "https://www.leboncoin.fr/ad/locations/1")
        assert result["enrichment_status"] == "done"
        assert result["extraction_source"] == "json"
        assert result["surface_m2"] == 38.0
        assert "price" not in result
        page.inner_text.assert_not_called()   # pas de regex sur la page entière

    def test_charges_and_deposit_from_description(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        attrs = [a for a in AD["attributes"] if a["key"] != "charges_included"]
        result = extract_detail(self._page(_html({**AD, "attributes": attrs})), "u")
        assert (result["charges"], result["deposit"]) == (40, 600)
        assert result["field_sources"]["charges"] == "description"
        assert result["field_sources"]["surface_m2"] == "json"

    def test_charges_not_added_when_included(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        result = extract_detail(self._page(_html()), "u")
        assert result["charges"] is None and result["charges_included"] is True

    def test_dom_fallback_without_json(self):
        from scrapers.detail_extractors.leboncoin_detail import extract_detail

        page = self._page("<html>rien</html>")
        page.inner_text.return_value = "Appartement non meublé de 31 m², 2 pièces"
        with patch("scrapers.detail_extractors.leboncoin_detail.time.sleep"):
            result = extract_detail(page, "u")
        assert result["extraction_source"] == "dom"
        assert result["surface_m2"] == 31.0
        assert result["furnished"] is False
        assert result["field_sources"]["surface_m2"] == "dom"


# ---------------------------------------------------------------------------
# Stockage : coordonnées exactes vs géocodage
# ---------------------------------------------------------------------------

URL = "https://www.leboncoin.fr/ad/locations/1"


def _row(db, url=URL):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM annonces WHERE url = ?", (url,)).fetchone())
    conn.close()
    return row


@pytest.fixture
def db(temp_db):
    from storage.sqlite import init_db, insert_annonce, upsert_annonce_profile
    init_db()
    insert_annonce({"site": "LeBonCoin", "title": "T2", "price": 640, "location_raw": "Toulouse 31400",
                    "distance_enac_km": 3.0, "url": URL, "lat": 43.6, "lon": 1.44})
    upsert_annonce_profile(URL, "enac", 3.0)
    return temp_db


class TestCoordinates:

    def test_geocoded_insert_is_approx(self, db):
        assert _row(db)["geo_precision"] == "approx"

    def test_exact_point_replaces_geocoding(self, db):
        from storage.sqlite import update_annonce_enrichment
        update_annonce_enrichment(URL, {"lat": 43.5822, "lon": 1.4573, "geo_precision": "exact",
                                        "field_sources": {"lat": "json"}, "extra_attributes": {"a": 1}})
        row = _row(db)
        assert (row["lat"], row["lon"], row["geo_precision"]) == (43.5822, 1.4573, "exact")
        assert json.loads(row["field_sources"]) == {"lat": "json"}

    def test_approx_point_does_not_replace_existing(self, db):
        from storage.sqlite import update_annonce_enrichment
        update_annonce_enrichment(URL, {"lat": 1.0, "lon": 1.0, "geo_precision": "approx"})
        assert (_row(db)["lat"], _row(db)["geo_precision"]) == (43.6, "approx")

    def test_rescrape_keeps_exact_point(self, db):
        """Un point exact connu remplace le géocodage lors des scrapings suivants."""
        from storage.sqlite import get_coordinates, update_annonce_enrichment
        update_annonce_enrichment(URL, {"lat": 43.5822, "lon": 1.4573, "geo_precision": "exact"})
        from pipeline import process_annonces
        raw = [{"site": "LeBonCoin", "title": "T2", "price": "640 €",
                "location_raw": "Toulouse 31400", "url": URL}]
        with patch("filters.price_and_distance.geocode_address") as geocode:
            process_annonces(raw, "LeBonCoin")
        geocode.assert_not_called()
        coords = get_coordinates(URL)
        assert (coords["lat"], coords["geo_precision"]) == (43.5822, "exact")

    def test_enrichment_refreshes_distances(self, db):
        page = MagicMock()
        page.content.return_value = _html()

        @contextmanager
        def session(*a, **k):
            yield MagicMock(), page

        with patch("scrapers.enricher.chrome_session", session), \
             patch("scrapers.enricher.is_page_blocked", return_value=False), \
             patch("scrapers.enricher.time.sleep"):
            from scrapers.enricher import enrich_annonces
            result = enrich_annonces(limit=5)

        assert (result["enriched"], result["relocated"]) == (1, 1)
        row = _row(db)
        assert (row["extraction_source"], row["ges_rating"], row["elevator"]) == ("json", "B", 1)
        conn = sqlite3.connect(db)
        dist = conn.execute("SELECT distance_km FROM annonce_profiles WHERE profile = 'enac'").fetchone()[0]
        conn.close()
        assert dist != 3.0 and dist < 3.0   # 43.5822,1.4573 est à ~2,5 km de l'ENAC


# ---------------------------------------------------------------------------
# Score : prix charges comprises
# ---------------------------------------------------------------------------

def test_rent_cc_does_not_double_count_included_charges():
    from scoring import rent_cc
    assert rent_cc(640, 40, charges_included=True) == 640
    assert rent_cc(600, 40, charges_included=False) == 640
    assert rent_cc(600, None) == 600


# ---------------------------------------------------------------------------
# Santé de l'extraction
# ---------------------------------------------------------------------------

class TestQuality:

    def _rows(self, n, **fields):
        base = {"site": "LeBonCoin", "surface_m2": 30, "nb_rooms": 1, "description": "x" * 30,
                "photos": '["https://a"]', "extraction_source": "json"}
        return [{**base, **fields} for _ in range(n)]

    def test_healthy(self):
        from storage.quality import check_fill_rates
        assert check_fill_rates({"LeBonCoin": self._rows(6)}) == []

    def test_broken_selectors_alert(self):
        from storage.quality import check_fill_rates
        alerts = check_fill_rates({"LeBonCoin": self._rows(6, surface_m2=None, photos="[]")})
        assert len(alerts) == 1 and "surface 0%" in alerts[0] and "photos 0%" in alerts[0]

    def test_json_disappeared_alert(self):
        from storage.quality import check_fill_rates
        alerts = check_fill_rates({"LeBonCoin": self._rows(6, extraction_source="dom")})
        assert any("JSON" in a for a in alerts)

    def test_too_few_samples_no_verdict(self):
        from storage.quality import check_fill_rates
        assert check_fill_rates({"LeBonCoin": self._rows(2, surface_m2=None)}) == []

    def test_enrichment_notifies_on_degradation(self):
        from scrapers.enricher import report_extraction_health
        with patch("notify.send") as send:
            alerts = report_extraction_health({"LeBonCoin": self._rows(6, nb_rooms=None)})
        assert alerts and send.call_args.kwargs["priority"] == "high"

    def test_cli_report(self, db, capsys):
        from main import main
        from storage.sqlite import update_annonce_enrichment
        update_annonce_enrichment(URL, {"enrichment_status": "done", "surface_m2": 38,
                                        "extraction_source": "json"})
        main(["quality"])
        out = capsys.readouterr().out
        assert "LeBonCoin" in out and "100%" in out


def test_ui_shows_feature_badges(db):
    from storage.sqlite import update_annonce_enrichment
    from ui import app
    update_annonce_enrichment(URL, {"enrichment_status": "done", "dpe_rating": "D", "ges_rating": "B",
                                    "furnished": False, "charges_included": True, "nb_rooms": 2,
                                    "lat": 43.58, "lon": 1.45, "geo_precision": "exact"})
    app.config["TESTING"] = True
    html = app.test_client().get("/?profile=enac").get_data(as_text=True)
    for label in ("DPE D", "GES B", "Vide", "CC", "T2", "📍 GPS"):
        assert label in html
