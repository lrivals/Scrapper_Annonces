# tests/test_ui.py
# =========================
# Tests de l'interface Flask (masquage, filtres)
# =========================

import sqlite3

import pytest

from storage.sqlite import init_db, insert_annonce, upsert_annonce_profile


class CsrfClient:
    """Client de test qui ajoute le jeton CSRF de la session à chaque POST."""

    def __init__(self, client):
        self._client = client
        client.get("/")  # crée la session et le jeton
        with client.session_transaction() as sess:
            self.token = sess["csrf_token"]

    def get(self, *args, **kwargs):
        return self._client.get(*args, **kwargs)

    def post(self, url, data=None, **kwargs):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token)
        return self._client.post(url, data=data, **kwargs)


@pytest.fixture
def raw_client(temp_db):
    init_db()
    from ui import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def client(raw_client):
    return CsrfClient(raw_client)


def _add(url, price=420, site="SeLoger", location="Rangueil", profile="enac", distance=1.0):
    insert_annonce({
        "site": site, "title": f"Studio {price}", "price": price,
        "location_raw": location, "distance_enac_km": 1.0, "url": url,
    })
    upsert_annonce_profile(url, profile, distance)


def _status(db, url):
    with sqlite3.connect(db) as con:
        return con.execute("SELECT status FROM annonces WHERE url = ?", (url,)).fetchone()[0]


def test_delete_hides_instead_of_deleting(client, temp_db):
    _add("https://ex.com/1")
    resp = client.post("/delete", data={"id": "1"}, headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.get_json()["ok"] is True
    assert _status(temp_db, "https://ex.com/1") == "hidden"


def test_hidden_excluded_by_default_and_restorable(client, temp_db):
    _add("https://ex.com/1", price=410)
    _add("https://ex.com/2", price=430)
    client.post("/delete", data={"id": "1"})

    page = client.get("/").get_data(as_text=True)
    assert "Studio 430" in page and "Studio 410" not in page

    page = client.get("/?status=hidden").get_data(as_text=True)
    assert "Studio 410" in page and "Studio 430" not in page

    client.post("/restore", data={"id": "1"})
    assert _status(temp_db, "https://ex.com/1") == "active"


def test_invalid_price_filter_is_ignored(client):
    _add("https://ex.com/1")
    resp = client.get("/?prix_min=abc&prix_max=")
    assert resp.status_code == 200
    assert "Studio 420" in resp.get_data(as_text=True)


def test_duplicates_badge_and_filter(client, temp_db):
    _add("https://lbc.fr/1", site="LeBonCoin")
    _add("https://seloger.com/2", site="SeLoger")
    with sqlite3.connect(temp_db) as con:
        con.execute("UPDATE annonces SET duplicate_of = 1 WHERE id = 2")

    page = client.get("/").get_data(as_text=True)
    assert "aussi sur LeBonCoin" in page

    page = client.get("/?dups=hide").get_data(as_text=True)
    assert "aussi sur LeBonCoin" not in page


def test_map_data_excludes_hidden(client):
    _add("https://ex.com/1")
    _add("https://ex.com/2", price=430)
    client.post("/delete", data={"id": "1"})
    listings = client.get("/api/map-data").get_json()["listings"]
    assert [l["id"] for l in listings] == [2]


def test_profile_tabs_split_listings(client):
    _add("https://ex.com/enac", price=450)
    _add("https://ex.com/blagnac", price=700, profile="blagnac", distance=3.2)

    page = client.get("/").get_data(as_text=True)
    assert "Studio 450" in page and "Studio 700" not in page

    page = client.get("/?profile=blagnac").get_data(as_text=True)
    assert "Studio 700" in page and "Studio 450" not in page
    assert "≈ 3,2 km" in page


def test_unknown_profile_falls_back_to_default(client):
    _add("https://ex.com/enac", price=450)
    assert "Studio 450" in client.get("/?profile=inconnu").get_data(as_text=True)


def test_sort_by_profile_distance(client):
    _add("https://ex.com/far", price=600, profile="blagnac", distance=7.5)
    _add("https://ex.com/near", price=700, profile="blagnac", distance=1.2)
    page = client.get("/?profile=blagnac&sort=distance&order=asc").get_data(as_text=True)
    assert page.index("Studio 700") < page.index("Studio 600")


def test_map_data_targets_profile(client):
    _add("https://ex.com/blagnac", price=700, profile="blagnac", distance=3.2)
    data = client.get("/api/map-data?profile=blagnac").get_json()
    assert data["target"]["key"] == "blagnac"
    assert data["target"]["radius_km"] == 8
    assert [l["distance_km"] for l in data["listings"]] == [3.2]


def test_export_document_uses_profile(client):
    _add("https://ex.com/blagnac", price=700, profile="blagnac", distance=3.2)
    resp = client.post("/export-document", data={"ids": "[1]", "profile": "blagnac"})
    text = resp.get_data(as_text=True)
    assert "Blagnac" in text.splitlines()[0]
    assert "3.2 km" in text
    assert "candidatures_blagnac_" in resp.headers["Content-Disposition"]


# ---- Sécurité (Sprint 12.6) ----

def test_post_without_csrf_token_is_rejected(raw_client, temp_db):
    _add("https://ex.com/1")
    assert raw_client.post("/clear-db", data={"confirm": "VIDER"}).status_code == 403
    assert raw_client.post("/delete", data={"id": "1"}).status_code == 403
    assert raw_client.post("/start-scraping").status_code == 403
    assert _status(temp_db, "https://ex.com/1") == "active"


def test_csrf_token_accepted_in_header(client):
    _add("https://ex.com/1")
    resp = client._client.post(
        "/delete", data={"id": "1"},
        headers={"X-CSRF-Token": client.token, "X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.get_json()["ok"] is True


def test_wrong_csrf_token_rejected(client):
    resp = client._client.post("/delete", data={"id": "1", "csrf_token": "faux"})
    assert resp.status_code == 403


def test_clear_db_requires_confirmation(client, temp_db):
    _add("https://ex.com/1")
    client.post("/clear-db", data={"back": "/"})
    with sqlite3.connect(temp_db) as con:
        assert con.execute("SELECT COUNT(*) FROM annonces").fetchone()[0] == 1
    client.post("/clear-db", data={"back": "/", "confirm": "VIDER"})
    with sqlite3.connect(temp_db) as con:
        assert con.execute("SELECT COUNT(*) FROM annonces").fetchone()[0] == 0


@pytest.mark.parametrize("back,expected_prefix", [
    ("https://evil.com/phish", "/?"),
    ("//evil.com/x", "/?"),
    ("javascript:alert(1)", "/?"),
    ("/?profile=blagnac&sort=price", "/?profile=blagnac&sort=price&flash="),
    ("http://localhost/?profile=enac", "/?profile=enac&flash="),
])
def test_back_redirect_stays_local(client, back, expected_prefix):
    _add("https://ex.com/1")
    resp = client.post("/delete", data={"id": "1", "back": back})
    location = resp.headers["Location"]
    assert location.startswith(expected_prefix), location
    assert "evil.com" not in location


def test_page_exposes_csrf_meta_and_static_assets(client):
    page = client.get("/").get_data(as_text=True)
    assert f'<meta name="csrf-token" content="{client.token}">' in page
    assert "/static/app.js" in page and "/static/app.css" in page
    assert client.get("/static/app.js").status_code == 200


# ---- Historique de prix (Sprint 12.4) ----

def test_price_drop_shown(client):
    _add("https://ex.com/1", price=480)
    insert_annonce({"site": "SeLoger", "title": "Studio 480", "price": 450,
                    "location_raw": "Rangueil", "url": "https://ex.com/1"})
    page = client.get("/").get_data(as_text=True)
    assert "↓ 30 €" in page
    assert "Prix initial 480 €" in page


def test_restore_button_visible_outside_document_mode(client):
    """Régression : le bouton Restaurer utilisait .btn-add-doc (masqué hors mode document)."""
    _add("https://ex.com/1")
    client.post("/delete", data={"id": "1"})
    page = client.get("/?status=hidden").get_data(as_text=True)
    assert 'class="btn-restore"' in page
    css = client.get("/static/app.css").get_data(as_text=True)
    restore_rule = css[css.index(".btn-restore {"):].split("}")[0]
    assert "display: none" not in restore_rule


# ---- Score (Sprint 13.3) ----

def test_default_sort_is_score_desc(client):
    from scoring import rescore
    _add("https://ex.com/far", price=490, distance=9.0)
    _add("https://ex.com/near", price=360, distance=0.5)
    rescore(["enac"])
    page = client.get("/").get_data(as_text=True)
    assert page.index("Studio 360") < page.index("Studio 490")
    assert 'class="score-pill score-high"' in page
    assert "Loyer CC" in page  # détail au survol


def test_map_data_includes_score(client):
    from scoring import rescore
    _add("https://ex.com/1")
    rescore(["enac"])
    assert client.get("/api/map-data").get_json()["listings"][0]["score"] is not None


def test_map_view_has_summary_stack(client):
    """Sprint 16 : pile de résumés à côté de la carte, cartes de la liste repérables par id."""
    _add("https://ex.com/1")
    page = client.get("/").get_data(as_text=True)
    assert 'id="map-stack"' in page and 'id="map-stack-list"' in page
    assert '<article class="card" data-id="1"' in page
    assert 'class="btn-add-doc" id="doc-btn-1" data-id="1"' in page


def test_card_shows_full_detail(client, temp_db):
    from storage.sqlite import update_annonce_enrichment
    _add("https://ex.com/full", price=605, profile="blagnac")
    update_annonce_enrichment("https://ex.com/full", {
        "enrichment_status": "done", "surface_m2": 42, "nb_rooms": 2, "floor": 2,
        "charges_included": True, "dpe_rating": "B", "publisher_type": "individual",
        "lat": 43.6, "lon": 1.39, "geo_precision": "exact",
    })
    _add("https://ex.com/pending", price=610, profile="blagnac")
    html = client.get("/?profile=blagnac").get_data(as_text=True)
    assert "T2 · 42 m² · 2ᵉ ét." in html
    assert "energy-B" in html and "14 €/m²" in html
    assert "Particulier" in html
    assert "Fiche pas encore lue" in html          # la 2ᵉ annonce n'a pas été ouverte
    listing = next(l for l in client.get("/api/map-data?profile=blagnac").get_json()["listings"]
                   if l["url"] == "https://ex.com/full")
    assert listing["key_facts"] == ["T2", "42 m²", "2ᵉ ét."]
    assert listing["price_note"] == "CC" and listing["energy"] == [["DPE", "B"]]
