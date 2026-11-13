# tests/test_seloger_json.py
# =========================
# Sprint 15.3 — SeLoger : extraction depuis l'état JSON embarqué (`window["__UFRN_…__"]`)
# Les fixtures reprennent, abrégée, la structure de vraies pages capturées le 2026-11-13.
# =========================

import copy
import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from scrapers.detail_extractors.seloger_json import (
    DETAIL_STATE, SEARCH_STATE, canonical_url, classified_id_from_url, extract_from_html,
    extract_state, find_search_classifieds, parse_detail, search_annonces_from_html,
)

URL = "https://www.seloger.com/annonce/location/occitanie/haute-garonne-31/toulouse-31000/26Z4HAEK5FKS"
CARD_URL = URL + "?serp_view=list&search=distributionTypes%3DRent%26page%3D3#ln=classified_search_results"

DESCRIPTION = (
    "Disponible immédiatement.\r\nAppartement T3 BBC de 63,13 m² + balcon, 2ème étage avec "
    "ascenseur, résidence sécurisée proche des transports."
)

DETAIL = {
    "brand": "seloger",
    "id": "26Z4HAEK5FKS",
    "metadata": {"legacyId": "285908273", "creationDate": "2026-11-13T06:56:00Z"},
    "domains": {"medias": {"images": [
        {"id": "a", "url": "https://mms.seloger.com/a.jpg"},
        {"id": "b", "url": "https://mms.seloger.com/b.jpg"},
        {"id": "logo", "url": "https://mms.seloger.com/logo.jpg"},
    ]}},
    "sections": {
        "location": {
            "address": {"country": "FRA", "city": "Toulouse", "zipCode": "31200", "district": "Lalande"},
            "isAddressPublished": True,
            "geometry": {"type": "Point", "coordinates": [1.426902861916414, 43.64877622105263]},
        },
        "description": {"description": DESCRIPTION, "headline": "Appartement récent"},
        "hardFacts": {
            "title": "Appartement à louer",
            "facts": [
                {"type": "numberOfRooms", "value": "3 pièces", "splitValue": "3"},
                {"type": "numberOfBedrooms", "value": "2 chambres", "splitValue": "2"},
                {"type": "livingSpace", "value": "63,13 m²", "splitValue": "63,13"},
                {"type": "numberOfFloors", "value": "2ème Étage", "splitValue": "2ème"},
            ],
            "price": {"value": "755 €", "ariaLabel": "755 €", "chargesLabel": "cc"},
        },
        "energy": {
            "features": [{"type": "energySource", "label": "Sources d'énergie", "value": "Gaz"}],
            "certificates": [{"scales": [
                {"efficiencyClass": {"index": 0, "rating": "A"},
                 "name": "Diagnostic de performance énergétique (DPE)", "type": "FR_ENERGY_BEFORE_2021"},
                {"efficiencyClass": {"index": 1, "rating": "B"},
                 "name": "Indice d'émission de gaz à effet de serre (GES)", "type": "FR_GHG_BEFORE_2021"},
            ]}],
        },
        "price": {
            "base": {
                "details": [{"label": {"main": "Coûts supplémentaires"},
                             "value": {"main": {"value": "71 €/mois", "ariaLabel": "71 €"}}}],
                "main": {"label": {"main": "Loyer charges comprises"},
                         "value": {"main": {"value": "755 €/mois", "ariaLabel": "755 €"}}},
            },
            "additional": [{"label": "Dépôt de garantie", "text": "684.0"}],
            "components": [
                {"type": "PRIMARY", "units": [{"details": [{"label": "dont", "prices": [
                    {"label": {"main": "Charges forfaitaires"},
                     "value": {"main": {"value": "71 €/mois", "ariaLabel": "71 €"}}}]}]}]},
                {"type": "SECONDARY", "units": [{"main": {"price": {
                    "label": {"main": "Honoraires TTC à la charge du locataire"},
                    "value": {"main": {"value": "656,64 €", "ariaLabel": "656.64 €"}}}}}]},
            ],
        },
        "features": {
            "preview": [
                {"icon": "availability", "value": "Disponible à partir du 17/11/2026"},
                {"icon": "elevator", "value": "Ascenseur"},
                {"icon": "furnished", "value": "Non meublé"},
            ],
            "details": {"categories": [
                {"title": "Extérieur", "elements": [{"icon": "balcony", "value": "Balcon"}]},
            ]},
        },
        "gallery": {"images": [
            {"url": "https://mms.seloger.com/a.jpg", "classification": {"name": "LIVING_ROOM"}},
            {"url": "https://mms.seloger.com/logo.jpg", "classification": {"name": "LOGO"}},
            {"url": "https://mms.seloger.com/b.jpg", "classification": {"name": "BEDROOM"}},
        ]},
    },
    "contactSections": {"contactCard": {"title": "CALOT ET ASSOCIES", "isPrivateOwner": False}},
    "legacyTracking": {"products": [{"client_type": "pro", "energy_letter": "A", "price": 755,
                                     "space": 63.13, "nb_rooms": 3, "nb_bedrooms": 2}]},
    "rawData": {"distributionType": "RENT", "propertyType": "APARTMENT"},
}


def _state_html(name, state):
    """Comme sur le site : la chaîne passée à JSON.parse est elle-même un littéral JSON."""
    literal = json.dumps(json.dumps(state, ensure_ascii=False), ensure_ascii=False)
    return (f'<html><head><script id="{name}">window["{name}"]=JSON.parse({literal});</script>'
            '<script>var other = 1;</script></head><body>…</body></html>')


def _detail_html(classified=None):
    return _state_html(DETAIL_STATE, {"app_cldp": {"data": {"classified": classified or DETAIL, "error": None}}})


def _search_item(cid, price=750, **overrides):
    item = {
        "id": cid,
        "status": "Published",
        "metadata": {"creationDate": "2026-10-29T18:18:00Z"},
        "location": {"address": {"city": "Toulouse", "zipCode": "31200", "district": "Bonnefoy"}},
        "hardFacts": {
            "title": "Appartement à louer",
            "facts": [
                {"type": "numberOfRooms", "value": "2 pièces", "splitValue": "2"},
                {"type": "numberOfBedrooms", "value": "1 chambre", "splitValue": "1"},
                {"type": "livingSpace", "value": "43 m²", "splitValue": "43"},
            ],
            "price": {"value": f"{price} €", "chargesLabel": "cc"},
        },
        "gallery": {"images": [{"url": f"https://cdn/{cid}.jpg", "classification": {"name": "LIVING_ROOM"}}]},
        "provider": {"isPrivateOwner": False, "publisherType": "AGENCY"},
        "mainDescription": {"description": "Beau T2 lumineux proche métro, cuisine équipée, balcon..."},
        "type": "PROFESSIONAL",
        "url": f"https://www.seloger.com/annonce/location/occitanie/haute-garonne-31/toulouse-31000/{cid}",
        "rawData": {"price": price, "surface": {"main": 43}, "nbroom": 2, "propertySubType": "APARTMENT"},
    }
    item.update(overrides)
    return item


def _search_html(items, order=None, extra=None):
    serp = {
        "classifieds": order if order is not None else [i["id"] for i in items],
        "classifiedsData": {i["id"]: i for i in items},
        "suggestedClassifieds": [],
        **(extra or {}),
    }
    return _state_html(SEARCH_STATE, {"data": {"mfe_seom_resolver_serp_sl": {}, "classified-serp-data": serp}})


# ---------------------------------------------------------------------------
# Lecture de l'état
# ---------------------------------------------------------------------------

class TestState:

    def test_double_decoding(self):
        state = {"a": 'guillemets " et </ et \\ et é'}
        assert extract_state(_state_html("__X__", state), "__X__") == state

    def test_object_literal(self):
        html = '<script>window["__X__"]={"a": 1};</script>'
        assert extract_state(html, "__X__") == {"a": 1}

    @pytest.mark.parametrize("html", [
        None, "", "<html>rien</html>",
        '<script>window["__X__"]=JSON.parse("{\\"a\\": tronqu</script>',
        '<script>window["__X__"]=JSON.parse("[1, 2]")</script>',
    ])
    def test_absent_or_invalid(self, html):
        assert extract_state(html, "__X__") is None


# ---------------------------------------------------------------------------
# Page de détail
# ---------------------------------------------------------------------------

class TestDetail:

    def test_full_listing(self):
        d = extract_from_html(_detail_html())
        assert (d["surface_m2"], d["nb_rooms"], d["nb_bedrooms"], d["floor"]) == (63.13, 3, 2, 2)
        assert (d["dpe_rating"], d["ges_rating"]) == ("A", "B")
        assert (d["charges_included"], d["charges"], d["deposit"]) == (True, 71, 684)
        assert (d["furnished"], d["elevator"]) == (False, True)       # « Non meublé »
        assert d["description"].startswith("Disponible immédiatement.\nAppartement T3")
        assert "\r" not in d["description"]
        assert d["photos"] == ["https://mms.seloger.com/a.jpg", "https://mms.seloger.com/b.jpg"]  # sans logo
        assert (d["publisher_type"], d["published_at"], d["price"]) == ("agency", "2026-11-13", 755)
        assert (d["lat"], d["lon"], d["geo_precision"]) == (43.648776, 1.426903, "exact")
        extra = d["extra_attributes"]
        assert extra["honoraires"] == 657
        assert extra["availability"] == "Disponible à partir du 17/11/2026"
        assert extra["balcony"] == "Balcon" and extra["Sources d'énergie"] == "Gaz"
        assert extra["district"] == "Lalande"

    def test_hors_charges_and_unpublished_address(self):
        c = copy.deepcopy(DETAIL)
        c["sections"]["hardFacts"]["price"]["chargesLabel"] = "hc"
        c["sections"]["price"] = {"base": {"main": {"label": {"main": "Loyer de base (plus charges)"},
                                                    "value": {"main": {"ariaLabel": "270 €"}}}},
                                  "additional": [{"label": "Dépôt de garantie", "text": "270"}]}
        c["sections"]["location"] = {
            "address": {"city": "Toulouse", "zipCode": "99000", "district": "Saint-Étienne"},
            "isAddressPublished": False,
            "geometry": {"type": "MultiPolygon", "coordinates": [[[[1.0, 43.0], [2.0, 43.0], [2.0, 44.0], [1.0, 44.0]]]]},
        }
        d = parse_detail(c)
        assert (d["charges_included"], d["charges"], d["deposit"]) == (False, None, 270)
        assert (d["lat"], d["lon"], d["geo_precision"]) == (43.5, 1.5, "approx")

    def test_point_without_published_address_is_approx(self):
        c = copy.deepcopy(DETAIL)
        c["sections"]["location"]["isAddressPublished"] = False
        assert parse_detail(c)["geo_precision"] == "approx"

    @pytest.mark.parametrize("text,expected", [
        ("Rez-de-chaussée", 0), ("RDC", 0), ("1er Étage", 1), ("5ème Étage", 5),
    ])
    def test_floor(self, text, expected):
        c = copy.deepcopy(DETAIL)
        c["sections"]["hardFacts"]["facts"][3]["value"] = text
        assert parse_detail(c)["floor"] == expected

    def test_dpe_from_legacy_when_no_scale(self):
        c = copy.deepcopy(DETAIL)
        c["sections"]["energy"] = {"certificates": [{"scales": [
            {"name": "Diagnostic de Performance Énergétique (DPE)",
             "alternateText": "Un certificat énergétique n'est pas nécessaire pour ce bien."}]}]}
        d = parse_detail(c)
        assert (d["dpe_rating"], d["ges_rating"]) == ("A", None)

    def test_private_owner(self):
        c = copy.deepcopy(DETAIL)
        c["contactSections"]["contactCard"]["isPrivateOwner"] = True
        assert parse_detail(c)["publisher_type"] == "individual"

    def test_minimal_classified_never_raises(self):
        d = parse_detail({"sections": {"hardFacts": {}}})
        assert d["surface_m2"] is None and d["photos"] is None and "lat" not in d

    def test_classified_found_elsewhere(self):
        html = _state_html(DETAIL_STATE, {"other_app": {"payload": {"listing": DETAIL}}})
        assert extract_from_html(html)["surface_m2"] == 63.13

    def test_no_state(self):
        assert extract_from_html("<html><body>Annonce</body></html>") is None


# ---------------------------------------------------------------------------
# Page de recherche
# ---------------------------------------------------------------------------

class TestSearch:

    def test_order_and_ignored_extras(self):
        items = [_search_item("26AAAAAAAAA1"), _search_item("26BBBBBBBBB2")]
        html = _search_html(items, order=["26BBBBBBBBB2", "26AAAAAAAAA1"],
                            extra={"suggestedClassifieds": [_search_item("26CCCCCCCCC3")]})
        state = extract_state(html, SEARCH_STATE)
        assert [c["id"] for c in find_search_classifieds(state)] == ["26BBBBBBBBB2", "26AAAAAAAAA1"]

    def test_annonce_for_pipeline(self):
        from utils.validation import validate_annonce

        [a] = search_annonces_from_html(_search_html([_search_item("26H2IBYFV8DE", price=862)]))
        assert validate_annonce(a) is None
        assert (a["site"], a["title"], a["price"]) == ("SeLoger", "Appartement à louer", 862)
        assert a["url"].endswith("/26H2IBYFV8DE")
        assert a["location_raw"] == "Bonnefoy, Toulouse (31200)"      # même forme que les cartes
        assert a["nb_rooms"] == 2 and "lat" not in a                   # pas de GPS dans la recherche
        d = a["details"]
        assert (d["surface_m2"], d["nb_bedrooms"], d["charges_included"]) == (43.0, 1, True)
        assert d["publisher_type"] == "agency" and d["published_at"] == "2026-10-29"
        assert d["extraction_source"] == "search_json"

    def test_truncated_description_not_saved_and_detail_still_visited(self):
        [a] = search_annonces_from_html(_search_html([_search_item("26H2IBYFV8DE")]))
        assert a["details"]["description"] is None
        assert "enrichment_status" not in a["details"]                 # page de détail à visiter

    def test_fake_zipcode_dropped(self):
        item = _search_item("26K5F58IG3TY", location={"address": {
            "city": "Toulouse", "zipCode": "99000", "district": "Saint-Étienne"}})
        [a] = search_annonces_from_html(_search_html([item]))
        assert a["location_raw"] == "Saint-Étienne, Toulouse"

    def test_bad_item_skipped(self):
        items = [_search_item("26AAAAAAAAA1"), _search_item("26BBBBBBBBB2", rawData={}, hardFacts={})]
        assert len(search_annonces_from_html(_search_html(items))) == 1  # sans prix : ignorée

    def test_no_state(self):
        assert search_annonces_from_html("<html></html>") == []


@pytest.mark.parametrize("url,expected", [
    (CARD_URL, "26Z4HAEK5FKS"),
    (URL, "26Z4HAEK5FKS"),
    ("https://www.seloger.com/annonce/26XNKCIS6TK8?serp_view=list", "26XNKCIS6TK8"),
    ("https://www.seloger.com/266061609/detail.htm?serp_view=list&search=x", "266061609"),
    ("https://www.seloger.com/classified-search?distributionTypes=Rent", None),
    ("https://www.seloger.com/professionnels-immobilier/agence", None),
    (None, None),
])
def test_classified_id_from_url(url, expected):
    assert classified_id_from_url(url) == expected


def test_canonical_url():
    assert canonical_url(CARD_URL) == URL
    assert canonical_url(URL + "#photos") == URL
    assert canonical_url(None) is None


# ---------------------------------------------------------------------------
# Scraper, enrichissement, annonces retirées
# ---------------------------------------------------------------------------

def _page(html):
    page = MagicMock()
    page.content.return_value = html
    return page


class TestScraper:

    @pytest.fixture
    def scraper(self):
        from config import SEARCH_PROFILES
        from scrapers.seloger import SeLogerScraper
        return SeLogerScraper(profile=SEARCH_PROFILES["blagnac"])

    def test_card_urls_are_canonical(self, scraper):
        rel = CARD_URL.replace("https://www.seloger.com", "")
        assert scraper.build_full_url(rel) == URL
        assert scraper.build_full_url(CARD_URL) == URL

    def test_json_and_card_share_key(self, scraper):
        [a] = scraper.page_json_annonces(_page(_search_html([_search_item("26Z4HAEK5FKS")])))
        card = MagicMock()
        link = MagicMock()
        link.get_attribute.return_value = CARD_URL
        card.query_selector.return_value = link
        assert scraper.annonce_key(a["url"]) == scraper.annonce_key(scraper.card_url(card)) == "26Z4HAEK5FKS"


class TestEnrichment:

    def test_json_first(self):
        from scrapers.detail_extractors import seloger_detail

        with patch.object(seloger_detail, "_extract_from_dom") as dom:
            d = seloger_detail.extract_detail(_page(_detail_html()), URL)
        dom.assert_not_called()
        assert d["enrichment_status"] == "done" and d["extraction_source"] == "json"
        assert "price" not in d and d["detail_price"] == 755      # sert à corriger un prix mal lu
        assert "detail_price" not in d["field_sources"]
        assert d["field_sources"]["dpe_rating"] == "json"
        assert "extra_attributes" not in d["field_sources"]

    def test_dom_fallback_completed_by_partial_json(self):
        from scrapers.detail_extractors import seloger_detail

        partial = {"sections": {"hardFacts": {}, "location": DETAIL["sections"]["location"]},
                   "legacyTracking": {"products": [{"energy_letter": "C"}]}}
        dom_result = {"surface_m2": 40.0, "nb_rooms": 2, "description": "x" * 50, "dpe_rating": None,
                      "enrichment_status": "done"}
        with patch.object(seloger_detail, "_extract_from_dom", return_value=dom_result):
            d = seloger_detail.extract_detail(_page(_detail_html(partial)), URL)
        assert d["extraction_source"] == "json+dom"
        assert d["dpe_rating"] == "C" and d["field_sources"]["dpe_rating"] == "json"
        assert d["field_sources"]["surface_m2"] == "dom"
        assert d["geo_precision"] == "exact"

    def test_dom_only(self):
        from scrapers.detail_extractors import seloger_detail

        with patch.object(seloger_detail, "_extract_from_dom",
                          return_value={"surface_m2": 40.0, "enrichment_status": "done"}):
            d = seloger_detail.extract_detail(_page("<html></html>"), URL)
        assert d["extraction_source"] == "dom"

    def test_online_listing_not_expired(self):
        from storage.cleaner import page_shows_expired

        page = _page(_detail_html())
        page.inner_text.return_value = "Cette annonce n'est plus disponible"   # texte trompeur
        assert page_shows_expired(page) is False


# ---------------------------------------------------------------------------
# Migration 10 : URLs SeLoger sans paramètres
# ---------------------------------------------------------------------------

def test_migration_canonical_urls_merges_same_listing(temp_db):
    from storage.sqlite import init_db

    init_db()
    con = sqlite3.connect(temp_db)
    other = "https://www.leboncoin.fr/ad/locations/123?x=1"
    rows = [
        (1, "SeLoger", URL + "?search=page%3D1#ln=a", 700),
        (2, "SeLoger", URL + "?search=page%3D3#ln=b", 690),     # même annonce vue page 3
        (3, "SeLoger", "https://www.seloger.com/266061609/detail.htm?serp_view=list", 500),
        (4, "LeBonCoin", other, 600),                          # autre site : intouché
        (5, "LeBonCoin", "https://www.leboncoin.fr/ad/locations/999", 650),
    ]
    con.executemany("INSERT INTO annonces (id, site, title, url, price, status) VALUES (?, ?, 't', ?, ?, 'active')", rows)
    con.execute("UPDATE annonces SET duplicate_of = 2 WHERE id = 5")
    con.execute("INSERT INTO price_history (annonce_id, price, seen_at) VALUES (2, 690, '2026-11-10')")
    con.execute("INSERT INTO annonce_profiles (annonce_id, profile, distance_km) VALUES (1, 'enac', 3.0)")
    con.execute("INSERT INTO annonce_profiles (annonce_id, profile, distance_km) VALUES (2, 'enac', 3.0)")
    con.execute("INSERT INTO annonce_profiles (annonce_id, profile, distance_km) VALUES (2, 'blagnac', 5.0)")
    con.execute("INSERT INTO annonce_feedback (annonce_id, profile, feedback) VALUES (2, 'blagnac', 'favorite')")
    con.execute("PRAGMA user_version = 9")
    con.commit()
    con.close()

    init_db()

    con = sqlite3.connect(temp_db)
    urls = dict(con.execute("SELECT id, url FROM annonces").fetchall())
    assert urls == {1: URL, 3: "https://www.seloger.com/266061609/detail.htm", 4: other,
                    5: "https://www.leboncoin.fr/ad/locations/999"}
    assert con.execute("SELECT annonce_id FROM price_history").fetchall() == [(1,)]
    assert sorted(con.execute("SELECT annonce_id, profile FROM annonce_profiles").fetchall()) == [
        (1, "blagnac"), (1, "enac")]
    assert con.execute("SELECT annonce_id, feedback FROM annonce_feedback").fetchall() == [(1, "favorite")]
    assert con.execute("SELECT duplicate_of FROM annonces WHERE id = 5").fetchone() == (1,)
    con.close()


# ---------------------------------------------------------------------------
# Prix de la page d'annonce : correction des prix de cartes mal lus
# ---------------------------------------------------------------------------

class TestDetailPrice:

    def _setup(self, temp_db, price, profiles=("enac", "blagnac")):
        from storage.sqlite import get_annonces_by_ids, init_db, insert_annonce, upsert_annonce_profile

        init_db()
        insert_annonce({"site": "SeLoger", "title": "Appartement à louer", "price": price,
                        "location_raw": "Toulouse (31200)", "url": URL})
        for p in profiles:
            upsert_annonce_profile(URL, p, 3.0)
        return get_annonces_by_ids([1])[0]

    def test_wrong_price_corrected_and_out_of_budget_profile_left(self, temp_db):
        from scrapers.enricher import _apply_detail_price
        from storage.sqlite import get_price_history, linked_profiles

        annonce = self._setup(temp_db, 4)                 # « 1 004 € » lu 4 € (2026-11-04)
        assert _apply_detail_price(annonce, 1004) is True
        with sqlite3.connect(temp_db) as con:
            assert con.execute("SELECT price FROM annonces WHERE id = 1").fetchone() == (1004,)
        assert [h["price"] for h in get_price_history(1)] == [4, 1004]
        assert linked_profiles(1) == ["blagnac"]          # ENAC : budget ≤ 500 €

    def test_same_or_missing_price_changes_nothing(self, temp_db):
        from scrapers.enricher import _apply_detail_price
        from storage.sqlite import linked_profiles

        annonce = self._setup(temp_db, 450)
        assert _apply_detail_price(annonce, 450) is False
        assert _apply_detail_price(annonce, None) is False
        assert _apply_detail_price(annonce, 0) is False
        assert linked_profiles(1) == ["blagnac", "enac"]

    def test_enrich_ids_revisits_listing(self, temp_db):
        from scrapers import enricher

        self._setup(temp_db, 4)
        with sqlite3.connect(temp_db) as con:
            con.execute("UPDATE annonces SET enrichment_status = 'done'")   # déjà enrichie
        page = _page(_detail_html())
        page.inner_text.return_value = ""
        session = MagicMock()
        session.__enter__.return_value = (None, page)
        with patch.object(enricher, "chrome_session", return_value=session), \
             patch.object(enricher, "is_page_blocked", return_value=False), \
             patch.object(enricher.time, "sleep"):
            summary = enricher.enrich_annonces(ids=[1])
        assert (summary["enriched"], summary["repriced"]) == (1, 1)
        with sqlite3.connect(temp_db) as con:
            assert con.execute("SELECT price, dpe_rating FROM annonces WHERE id = 1").fetchone() == (755, "A")


def test_enrich_stops_when_browser_closed(temp_db):
    """Chrome fermé en cours de run : arrêt net, aucune annonce pénalisée (constat du 2026-11-13)."""
    from scrapers import enricher
    from storage.sqlite import init_db, insert_annonce

    init_db()
    for i in range(3):
        insert_annonce({"site": "SeLoger", "title": "A", "price": 700, "location_raw": "Toulouse",
                        "url": f"{URL}{i}"})
    page = MagicMock()
    page.goto.side_effect = Exception("Page.goto: Target page, context or browser has been closed")
    page.is_closed.return_value = True
    session = MagicMock()
    session.__enter__.return_value = (None, page)
    with patch.object(enricher, "chrome_session", return_value=session), patch.object(enricher.time, "sleep"):
        summary = enricher.enrich_annonces(ids=[1, 2, 3])
    assert summary["errors"] == 0 and page.goto.call_count == 1
    with sqlite3.connect(temp_db) as con:
        assert con.execute("SELECT DISTINCT enrichment_status, enrichment_attempts FROM annonces").fetchall() \
            == [("pending", 0)]
