# tests/test_ui.py
# =========================
# Tests de l'interface Flask (masquage, filtres)
# =========================

import sqlite3

import pytest

from storage.sqlite import init_db, insert_annonce, upsert_annonce_profile


@pytest.fixture
def client(temp_db, monkeypatch):
    import ui
    monkeypatch.setattr(ui, "DB_PATH", temp_db)
    init_db()
    ui.app.config["TESTING"] = True
    return ui.app.test_client()


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
    assert "3.2 km" in page


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
