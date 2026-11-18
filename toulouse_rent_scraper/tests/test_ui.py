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
    assert "Aussi sur LeBonCoin" in page          # menu ⋯ de la carte

    page = client.get("/?dups=hide").get_data(as_text=True)
    assert "Aussi sur LeBonCoin" not in page


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
    assert 'class="tb-item btn-restore"' in page      # menu ⋯ de la carte
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
    assert 'class="score-badge score-high"' in page
    assert "Loyer CC" in page  # détail au survol


def test_map_data_includes_score(client):
    from scoring import rescore
    _add("https://ex.com/1")
    rescore(["enac"])
    assert client.get("/api/map-data").get_json()["listings"][0]["score"] is not None


def test_map_and_list_share_detail_panel(client):
    """Étape 4 : un seul panneau de détail pour la liste et la carte (la pile de résumés disparaît)."""
    _add("https://ex.com/1")
    page = client.get("/").get_data(as_text=True)
    assert 'id="map"' in page and 'id="detail-panel"' in page and 'id="detail-body"' in page
    assert "map-stack" not in page
    assert '<article class="card" data-id="1"' in page
    assert 'class="select-box" data-id="1"' in page      # case de sélection, synchronisée avec la pile


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
    # Carte : prix, €/m², ligne clé (logement · distance · annonceur)
    assert "T2 · 42 m² · 2ᵉ ét." in html and "14 €/m²" in html and "Particulier" in html
    assert "energy-B" not in html and "Fiche pas encore lue" not in html
    # Panneau de détail : énergie, annonceur, fiche pas encore lue
    full = client.get("/annonce/1/details?profile=blagnac").get_data(as_text=True)
    assert "energy-B" in full and "Particulier" in full and "T2 · 42 m² · 2ᵉ ét." in full
    pending = client.get("/annonce/2/details?profile=blagnac").get_data(as_text=True)
    assert "Fiche pas encore lue" in pending        # la 2ᵉ annonce n'a pas été ouverte
    listing = next(l for l in client.get("/api/map-data?profile=blagnac").get_json()["listings"]
                   if l["url"] == "https://ex.com/full")
    assert listing["key_facts"] == ["T2", "42 m²", "2ᵉ ét."]
    assert listing["price_note"] == "CC" and listing["energy"] == [["DPE", "B"]]


def test_card_details_panel(client, temp_db):
    from storage.sqlite import update_annonce_enrichment
    _add("https://ex.com/d", price=600, profile="blagnac")
    update_annonce_enrichment("https://ex.com/d", {
        "enrichment_status": "done", "description": "Lumineux, proche du tram T1",
        "photos": '["https://img.ex/1.jpg", "https://img.ex/2.jpg"]',
    })
    page = client.get("/?profile=blagnac").get_data(as_text=True)
    assert 'data-open-detail' in page and 'id="detail-panel"' in page
    assert "btn-details" not in page and "card-details" not in page

    html = client.get("/annonce/1/details?profile=blagnac").get_data(as_text=True)
    assert "Lumineux, proche du tram T1" in html and "https://img.ex/2.jpg" in html
    assert "Voir l’annonce sur SeLoger" in html
    assert client.get("/annonce/1/details?profile=enac").status_code == 404     # autre profil
    assert client.get("/annonce/999/details?profile=blagnac").status_code == 404


# ---- Barre du haut (refonte UI, étape 1) ----

@pytest.mark.parametrize("url", ["/", "/tendances?profile=blagnac", "/settings/weights",
                                 "/settings/requirements?profile=blagnac", "/settings/llm"])
def test_topbar_on_every_page(client, url):
    page = client.get(url).get_data(as_text=True)
    assert 'class="topbar"' in page and "/static/topbar.js" in page
    assert 'popovertarget="menu-settings"' in page and 'popovertarget="scrape-panel"' in page
    assert 'id="theme-toggle"' in page
    assert f'<meta name="csrf-token" content="{client.token}">' in page


def test_settings_menu_groups_secondary_actions(client):
    page = client.get("/?profile=blagnac").get_data(as_text=True)
    menu = page[page.index('id="menu-settings"'):]
    menu = menu[:menu.index("</div>")]
    for href in ("/settings/requirements?profile=blagnac", "/settings/weights", "/settings/llm"):
        assert f'href="{href}"' in menu
    assert 'action="/clear-db"' in menu and 'name="confirm"' in menu and "Vider la base" in menu
    assert f'value="{client.token}"' in menu
    assert "action-bar" not in page and "btn-clear-db" not in page


def test_profile_menu_marks_current_profile(client):
    from config import SEARCH_PROFILES
    page = client.get("/?profile=blagnac").get_data(as_text=True)
    menu = page[page.index('id="menu-profile"'):]
    menu = menu[:menu.index("</div>")]
    for key in SEARCH_PROFILES:
        assert f'href="/?profile={key}"' in menu
    assert menu.count('aria-current="true"') == 1
    current = menu[:menu.index('aria-current="true"')]
    assert current.rstrip().endswith('href="/?profile=blagnac"')
    # Tendances : le sélecteur garde la période choisie
    trends = client.get("/tendances?profile=blagnac&days=30").get_data(as_text=True)
    assert 'href="/tendances?days=30&amp;profile=enac"' in trends


def test_index_keeps_count_view_and_scrape_controls(client):
    page = client.get("/").get_data(as_text=True)
    for el_id in ("annonce-count", "view-toggle", "btn-scrape", "scrape-log"):
        assert f'id="{el_id}"' in page
    assert client.get("/static/topbar.js").status_code == 200


# ---- Barre d'outils, puces des filtres actifs, panneau des filtres (refonte UI, étape 2) ----

def _args(qs):
    from werkzeug.datastructures import MultiDict
    from urllib.parse import parse_qsl
    return MultiDict(parse_qsl(qs))


def test_chips_remove_only_their_own_param():
    from ui.filter_bar import filter_bar
    bar = filter_bar(_args("profile=blagnac&prix_max=800&site=LeBonCoin&sort=price&order=asc&view=map"
                           "&flash=ok&flash_msg=Hello"), "price", "asc")
    chips = {c.label: c.url for c in bar.chips}
    assert chips == {
        "Prix ≤ 800 €": "/?profile=blagnac&site=LeBonCoin&sort=price&order=asc&view=map",
        "LeBonCoin": "/?profile=blagnac&prix_max=800&sort=price&order=asc&view=map",
    }
    assert bar.count == 2
    # Tout effacer : garde profil, tri et vue ; jamais le message flash
    assert bar.clear_url == "/?profile=blagnac&sort=price&order=asc&view=map"


def test_chips_ignore_defaults_and_invalid_values():
    from ui.filter_bar import filter_bar
    bar = filter_bar(_args("profile=enac&site=&status=&prix_min=abc&dups=&excl=bogus&fb=favorite"), "score", "desc")
    assert bar.chips == []           # ⭐ Favoris est un filtre rapide, pas une puce
    assert [q.current for q in bar.quick] == [True, False]
    assert bar.quick[0].url == "/?profile=enac&prix_min=abc&excl=bogus"   # second clic : retire fb
    assert bar.quick[1].url.endswith("fb=contacted")


def test_chip_labels():
    from ui.filter_bar import filter_bar
    bar = filter_bar(_args("prix_min=400&status=hidden&dups=hide&fb=dislike&excl=only"), "score", "desc")
    assert [c.label for c in bar.chips] == ["Prix ≥ 400 €", "Masquées", "Sans doublons", "👎 Pas intéressé",
                                             "Exclues seulement"]


def test_sort_menu_marks_current_option():
    from ui.filter_bar import filter_bar
    bar = filter_bar(_args("profile=blagnac&sort=price&order=desc"), "price", "desc")
    assert bar.sort_label == "Prix ↓"
    current = [s for s in bar.sorts if s.current]
    assert len(current) == 1 and current[0].url == "/?profile=blagnac&sort=price&order=desc"
    assert filter_bar(_args(""), "distance_enac_km", "asc").sort_label == "Distance"
    assert filter_bar(_args(""), "score", "asc").sort_label == "Score ↑"   # hors menu


def test_index_toolbar_chips_and_filters_dialog(client):
    _add("https://ex.com/1", price=450)
    _add("https://ex.com/2", price=900, site="LeBonCoin")
    page = client.get("/?prix_max=800&sort=price&order=asc").get_data(as_text=True)
    assert "Studio 450" in page and "Studio 900" not in page
    assert 'class="chip"' in page and "Prix ≤ 800 €" in page
    assert 'href="/?sort=price&amp;order=asc"' in page                  # ✕ de la puce
    assert 'class="btn-tool-badge"' in page and "Trier :</span> Prix ↑" in page
    assert 'aria-pressed="false"' in page and "⭐ Favoris" in page
    # Panneau : formulaire GET existant, tri et vue conservés, bouton « Voir N annonces »
    dialog = page[page.index('<dialog id="filters-dialog"'):page.index("</dialog>")]
    assert 'method="get"' in dialog
    for name in ("prix_min", "prix_max", "site", "status", "fb", "dups"):
        assert f'name="{name}"' in dialog
    assert 'name="sort" value="price"' in dialog and 'name="order" value="asc"' in dialog
    assert "Voir 1 annonce<" in dialog
    assert "filter-bar" not in page and "order-btn" not in page


def test_index_without_filters_has_no_chips_row(client):
    _add("https://ex.com/1")
    page = client.get("/").get_data(as_text=True)
    assert 'class="chips-row"' not in page and 'class="btn-tool-badge"' not in page


# ---- Sélection par cases à cocher et barre d'export (refonte UI, étape 3) ----

def test_cards_have_selection_checkbox_and_export_bar(client):
    _add("https://ex.com/1", price=450)
    page = client.get("/").get_data(as_text=True)
    assert 'class="select-box" data-id="1"' in page
    assert "Sélectionner « Studio 450 » pour l’export" in page
    bar = page[page.index('id="selection-bar"'):]
    bar = bar[:bar.index("</form>")]
    assert "hidden" in bar.split(">")[0]                  # cachée tant que rien n'est coché
    assert "Exporter" in bar and "Tout décocher" in bar
    assert 'action="/export-document"' in bar and 'name="ids"' in bar and 'name="profile"' in bar
    # Ancien mode document retiré
    for gone in ("btn-doc-mode", "btn-add-doc", "Commencer document", "doc-bar"):
        assert gone not in page


# ---- Carte simplifiée et panneau de détail (refonte UI, étape 4) ----

def test_simplified_card_and_action_menu(client, temp_db):
    _add("https://ex.com/1", price=450)
    page = client.get("/").get_data(as_text=True)
    card = page[page.index('<article class="card" data-id="1"'):]
    card = card[:card.index("</article>")]
    assert 'class="btn-fb btn-fav' in card and 'data-value="favorite"' in card       # ⭐ direct
    menu = card[card.index('id="card-menu-1"'):]
    assert 'popover' in card and 'role="menu"' in menu
    for text in ('data-value="contacted"', 'data-value="dislike"', 'action="/delete"', "Masquer"):
        assert text in menu
    assert 'data-value="favorite"' not in menu
    # Étiquettes classiques retirées de la carte (passées dans le détail)
    for gone in ("card-meta", "card-feats", "status-pill", "energy"):
        assert gone not in card


def test_detail_fragment_has_header_and_feedback(client, temp_db):
    _add("https://ex.com/1", price=450, profile="blagnac")
    html = client.get("/annonce/1/details?profile=blagnac").get_data(as_text=True)
    assert 'class="detail-head" data-title="Studio 450"' in html
    assert "450 €" in html and "Voir l’annonce sur SeLoger" in html
    for value in ("favorite", "contacted", "dislike"):
        assert f'data-id="1" data-value="{value}"' in html
