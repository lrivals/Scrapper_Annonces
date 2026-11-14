# tests/test_api.py
# =========================
# Sprint 2-bis — API JSON /api/v1 (lecture seule), accès local / jeton, page Tendances
# =========================

import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import config
from storage.sqlite import init_db, insert_annonce, upsert_annonce_profile

REMOTE = {"REMOTE_ADDR": "192.168.1.20"}


@pytest.fixture
def client(temp_db):
    init_db()
    from ui import app
    app.config["TESTING"] = True
    return app.test_client()


def _add(db, n, price=650, profile="blagnac", score=60.0, site="SeLoger", matched_at=None, **cols):
    url = f"https://example.fr/annonce/{n}"
    insert_annonce({"site": site, "title": f"T2 n°{n}", "price": price,
                    "location_raw": "Pinot, Blagnac (31700)", "url": url})
    upsert_annonce_profile(url, profile, 1.5)
    with sqlite3.connect(db) as con:
        aid = con.execute("SELECT id FROM annonces WHERE url = ?", (url,)).fetchone()[0]
        con.execute("UPDATE annonce_profiles SET score = ? WHERE annonce_id = ?", (score, aid))
        if matched_at:
            con.execute("UPDATE annonce_profiles SET matched_at = ? WHERE annonce_id = ?", (matched_at, aid))
        if cols:
            sets = ", ".join(f"{k} = ?" for k in cols)
            con.execute(f"UPDATE annonces SET {sets} WHERE id = ?", (*cols.values(), aid))
    return aid


# ---- Accès ----

def test_local_access_without_token(client):
    assert client.get("/api/v1/profiles").status_code == 200


def test_remote_refused_when_no_token_configured(client, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", None)
    resp = client.get("/api/v1/profiles", environ_base=REMOTE)
    assert resp.status_code == 403 and "API_TOKEN" in resp.get_json()["error"]


@pytest.mark.parametrize("headers,status", [
    ({}, 401),
    ({"Authorization": "Bearer mauvais"}, 401),
    ({"Authorization": "Bearer s3cret-jeton"}, 200),
    ({"X-API-Token": "s3cret-jeton"}, 200),
])
def test_remote_with_token(client, monkeypatch, headers, status):
    monkeypatch.setattr(config, "API_TOKEN", "s3cret-jeton")
    assert client.get("/api/v1/profiles", headers=headers, environ_base=REMOTE).status_code == status


def test_wrong_token_refused_even_locally(client, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "s3cret-jeton")
    assert client.get("/api/v1/profiles", headers={"Authorization": "Bearer faux"}).status_code == 401


def test_read_only(client):
    assert client.post("/api/v1/annonces").status_code in (403, 405)    # CSRF ou méthode refusée
    assert client.delete("/api/v1/annonces/1").status_code in (403, 405)


# ---- Ressources ----

def test_profiles(client):
    data = client.get("/api/v1/profiles").get_json()
    keys = [p["key"] for p in data["items"]]
    assert "blagnac" in keys and data["default"] in keys
    blagnac = next(p for p in data["items"] if p["key"] == "blagnac")
    assert {"lat", "lon", "address"} <= blagnac["target"].keys()


def test_annonces_filters_sort_and_pagination(client, temp_db):
    _add(temp_db, 1, price=600, score=50)
    _add(temp_db, 2, price=700, score=80, furnished=1, photos='["https://p/1.jpg"]', site="PAP")
    _add(temp_db, 3, price=800, score=70)
    _add(temp_db, 4, price=500, profile="enac")

    data = client.get("/api/v1/annonces?profile=blagnac").get_json()
    assert data["total"] == 3 and [a["score"] for a in data["items"]] == [80, 70, 50]
    first = data["items"][0]
    assert first["furnished"] is True and "description" not in first
    assert "photo_hash" not in first and "llm_input_hash" not in first      # champs internes privés

    cheap = client.get("/api/v1/annonces?profile=blagnac&prix_max=650").get_json()
    assert [a["price"] for a in cheap["items"]] == [600]
    by_price = client.get("/api/v1/annonces?profile=blagnac&sort=price&order=asc").get_json()
    assert [a["price"] for a in by_price["items"]] == [600, 700, 800]
    pap = client.get("/api/v1/annonces?profile=blagnac&site=PAP").get_json()
    assert [a["site"] for a in pap["items"]] == ["PAP"]
    page = client.get("/api/v1/annonces?profile=blagnac&limit=1&offset=1").get_json()
    assert page["total"] == 3 and len(page["items"]) == 1 and page["items"][0]["score"] == 70


def test_annonces_bad_parameters(client):
    assert client.get("/api/v1/annonces?profile=inconnu").status_code == 404
    assert client.get("/api/v1/annonces?sort=title").status_code == 400
    assert client.get("/api/v1/annonces?order=up").status_code == 400
    assert client.get("/api/v1/annonces?limit=abc").status_code == 200           # défaut


def test_excluded_hidden_by_default(client, temp_db):
    aid = _add(temp_db, 1)
    with sqlite3.connect(temp_db) as con:
        con.execute("UPDATE annonce_profiles SET excluded_reasons = '[\"DPE G\"]' WHERE annonce_id = ?", (aid,))
    assert client.get("/api/v1/annonces?profile=blagnac").get_json()["total"] == 0
    shown = client.get("/api/v1/annonces?profile=blagnac&excl=show").get_json()["items"][0]
    assert shown["excluded_reasons"] == ["DPE G"]                                # JSON décodé


def test_annonce_detail_with_price_history(client, temp_db):
    aid = _add(temp_db, 1, price=700, description="Beau T2", photos='["https://p/1.jpg", "https://p/2.jpg"]')
    insert_annonce({"site": "SeLoger", "title": "T2 n°1", "price": 650, "location_raw": "Blagnac",
                    "url": "https://example.fr/annonce/1"})
    item = client.get(f"/api/v1/annonces/{aid}?profile=blagnac").get_json()["item"]
    assert item["description"] == "Beau T2" and item["photos"] == ["https://p/1.jpg", "https://p/2.jpg"]
    assert [p["price"] for p in item["price_history"]] == [700, 650]
    assert client.get(f"/api/v1/annonces/{aid}?profile=enac").status_code == 404
    assert client.get("/api/v1/annonces/99999?profile=blagnac").status_code == 404


def test_runs_stats_and_history(client, temp_db):
    from storage.run_stats import record_run

    _add(temp_db, 1, price=600, surface_m2=40)
    _add(temp_db, 2, price=800, site="PAP", matched_at=(datetime.now() - timedelta(days=3)).isoformat())
    total = SimpleNamespace(new_by_profile={"blagnac": 2}, updated=0, reactivated=0, duplicates=0, opened=0)
    record_run(datetime.now() - timedelta(hours=1), ["blagnac"], ["SeLoger", "PAP"], total)

    runs = client.get("/api/v1/runs?profile=blagnac").get_json()["items"]
    assert len(runs) == 1 and runs[0]["new_count"] == 2 and runs[0]["active_count"] == 2

    stats = client.get("/api/v1/stats?profile=blagnac").get_json()
    assert stats["active_count"] == 2 and stats["by_site"] == {"PAP": 1, "SeLoger": 1}
    assert stats["new_24h"] == 1 and stats["new_7d"] == 2 and stats["median_rent_cc"] == 700
    assert stats["last_run"]["sites"] == "SeLoger,PAP"

    hist = client.get("/api/v1/stats/history?profile=blagnac&days=7").get_json()
    daily = hist["daily"]
    assert len(daily["days"]) == 7 and daily["days"][-1] == datetime.now().date().isoformat()
    assert daily["new_by_site"]["SeLoger"][-1] == 1 and daily["new_by_site"]["PAP"][-4] == 1
    assert daily["median_rent_cc"][-1] == 600
    assert daily["median_rent_cc_7d"][-1] == 700                                 # 600 et 800 sur 7 jours
    assert len(hist["runs"]) == 1
    assert client.get("/api/v1/stats/history?days=99999").get_json()["days"] == 730


# ---- Page Tendances ----

def test_tendances_page(client, temp_db):
    _add(temp_db, 1, price=600)
    resp = client.get("/tendances?profile=blagnac&days=30")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "chart.umd.min.js" in html and "4.4.1" in html                     # version épinglée
    assert "const DAILY = {" in html and "Annonces visibles" in html
    assert "encore vide" in html                                              # aucun run journalisé
    assert 'href="/tendances?profile=blagnac' in client.get("/?profile=blagnac").get_data(as_text=True)
