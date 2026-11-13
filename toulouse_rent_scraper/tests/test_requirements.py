# tests/test_requirements.py
# =========================
# Sprint 15.5 — critères éliminatoires par profil
# =========================

import dataclasses
import json
import sqlite3

import pytest

import config
from config import Requirements
from filters.requirements import describe_requirements, exclusion_reasons
from scoring import rescore
from storage.migrations import SCHEMA_VERSION
from storage.sqlite import (
    annonces_for_notification, init_db, insert_annonce, save_llm_analysis,
    update_annonce_enrichment, upsert_annonce_profile,
)


# ---------------------------------------------------------------------------
# Règles
# ---------------------------------------------------------------------------

class TestExclusionReasons:
    def test_empty_requirements_never_exclude(self):
        assert exclusion_reasons({"floor": 0, "apl_ok": False, "surface_m2": 5}, Requirements()) == []

    @pytest.mark.parametrize("annonce, req, expected", [
        ({"available_from": "2027-02-01"}, Requirements(available_before="2027-01-01"),
         ["disponible le 01/02/2027 (après le 01/01/2027)"]),
        ({"available_from": "2026-12-15"}, Requirements(available_before="2027-01-01"), []),
        ({"available_from": "immediate"}, Requirements(available_before="2027-01-01"), []),
        ({"apl_ok": False}, Requirements(apl_required=True), ["APL refusées"]),
        ({"apl_ok": True}, Requirements(apl_required=True), []),
        ({"floor": 0}, Requirements(no_ground_floor=True), ["rez-de-chaussée"]),
        ({"floor": 2}, Requirements(no_ground_floor=True), []),
        ({"surface_m2": 14.5}, Requirements(min_surface_m2=18), ["14.5 m² (minimum 18 m²)"]),
        ({"surface_m2": 18}, Requirements(min_surface_m2=18), []),
        ({"furnished": False, "enrichment_status": "done"}, Requirements(furnished=True), ["non meublé"]),
        ({"furnished": True, "enrichment_status": "done"}, Requirements(furnished=False), ["meublé"]),
        ({"colocation": True}, Requirements(no_colocation=True), ["colocation"]),
        ({"lease_type": "colocation"}, Requirements(no_colocation=True), ["colocation"]),
        ({"lease_type": "saisonnier"}, Requirements(excluded_lease_types=("saisonnier",)),
         ["location saisonnière"]),
        ({"lease_type": "classique"}, Requirements(excluded_lease_types=("saisonnier",)), []),
        ({"dpe_rating": "F"}, Requirements(max_dpe="E"), ["DPE F (maximum E)"]),
        ({"dpe_rating": "e"}, Requirements(max_dpe="E"), []),
    ])
    def test_rules(self, annonce, req, expected):
        assert exclusion_reasons(annonce, req) == expected

    def test_unknown_values_keep_the_annonce(self):
        req = Requirements(
            available_before="2027-01-01", apl_required=True, no_ground_floor=True,
            min_surface_m2=20, furnished=True, no_colocation=True,
            excluded_lease_types=("saisonnier",), max_dpe="D",
        )
        unknown = {"available_from": None, "apl_ok": None, "floor": None, "surface_m2": None,
                   "furnished": None, "colocation": None, "lease_type": None, "dpe_rating": None}
        assert exclusion_reasons(unknown, req) == []
        assert exclusion_reasons({}, req) == []
        assert exclusion_reasons({"available_from": "pas une date", "dpe_rating": "NS"}, req) == []

    def test_furnished_ignored_until_enriched(self):
        """Avant enrichissement, `furnished` peut être une valeur par défaut des cartes."""
        req = Requirements(furnished=True)
        assert exclusion_reasons({"furnished": False, "enrichment_status": "pending"}, req) == []

    def test_several_reasons(self):
        req = Requirements(apl_required=True, no_ground_floor=True)
        assert exclusion_reasons({"apl_ok": 0, "floor": 0}, req) == ["APL refusées", "rez-de-chaussée"]

    def test_colocation_not_reported_twice(self):
        req = Requirements(no_colocation=True, excluded_lease_types=("colocation",))
        assert exclusion_reasons({"lease_type": "colocation"}, req) == ["colocation"]

    def test_describe(self):
        req = Requirements(available_before="2027-01-01", apl_required=True, max_dpe="e",
                           excluded_lease_types=("mobilite",))
        assert describe_requirements(req) == [
            "libre avant le 01/01/2027", "APL acceptées", "pas de bail mobilité", "DPE E ou mieux",
        ]
        assert describe_requirements(Requirements()) == []

    def test_profiles_have_requirements(self):
        for profile in config.SEARCH_PROFILES.values():
            assert isinstance(profile.requirements, Requirements)


# ---------------------------------------------------------------------------
# Stockage, rescore, notifications
# ---------------------------------------------------------------------------

@pytest.fixture
def strict_enac(monkeypatch):
    """Profil ENAC avec des critères ; les autres profils inchangés."""
    def apply(**kwargs):
        profile = dataclasses.replace(config.SEARCH_PROFILES["enac"], requirements=Requirements(**kwargs))
        monkeypatch.setitem(config.SEARCH_PROFILES, "enac", profile)
        return profile
    return apply


def _add(url, profiles=("enac",), **details):
    insert_annonce({"site": "LeBonCoin", "title": "Studio", "price": 400,
                    "location_raw": "Rangueil", "url": url})
    for p in profiles:
        upsert_annonce_profile(url, p, 2.0)
    if details:
        update_annonce_enrichment(url, details)


def _excluded(db):
    with sqlite3.connect(db) as con:
        rows = con.execute(
            "SELECT a.url, ap.profile, ap.excluded_reasons FROM annonce_profiles ap "
            "JOIN annonces a ON a.id = ap.annonce_id"
        ).fetchall()
    return {(url, p): (json.loads(r) if r else None) for url, p, r in rows}


def test_migration_adds_column(temp_db):
    init_db()
    with sqlite3.connect(temp_db) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(annonce_profiles)")}
        assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "excluded_reasons" in cols


def test_rescore_marks_exclusions_per_profile(temp_db, strict_enac):
    init_db()
    strict_enac(no_ground_floor=True)
    _add("https://a/rdc", profiles=("enac", "blagnac"), floor=0)
    _add("https://a/etage", floor=3)
    _add("https://a/inconnu")
    rescore()
    state = _excluded(temp_db)
    assert state[("https://a/rdc", "enac")] == ["rez-de-chaussée"]
    assert state[("https://a/rdc", "blagnac")] is None     # critère propre au profil ENAC
    assert state[("https://a/etage", "enac")] is None
    assert state[("https://a/inconnu", "enac")] is None


def test_exclusion_is_reversible(temp_db, strict_enac):
    init_db()
    strict_enac(min_surface_m2=20)
    _add("https://a/1", surface_m2=15)
    rescore()
    assert _excluded(temp_db)[("https://a/1", "enac")] == ["15 m² (minimum 20 m²)"]
    strict_enac(min_surface_m2=12)   # critère assoupli
    rescore()
    assert _excluded(temp_db)[("https://a/1", "enac")] is None


def test_llm_fields_feed_requirements(temp_db, strict_enac):
    init_db()
    strict_enac(apl_required=True, available_before="2027-01-01")
    _add("https://a/1")
    with sqlite3.connect(temp_db) as con:
        annonce_id = con.execute("SELECT id FROM annonces").fetchone()[0]
    save_llm_analysis(annonce_id, {"llm_status": "done", "apl_ok": False, "available_from": "2027-03-01"})
    rescore()
    assert _excluded(temp_db)[("https://a/1", "enac")] == [
        "disponible le 01/03/2027 (après le 01/01/2027)", "APL refusées",
    ]


def test_excluded_annonces_are_not_notified(temp_db, strict_enac):
    init_db()
    strict_enac(no_ground_floor=True)
    _add("https://a/rdc", floor=0)
    _add("https://a/ok", floor=2)
    rescore()
    infos = annonces_for_notification("enac", ["https://a/rdc", "https://a/ok"])
    assert set(infos) == {"https://a/ok"}


def test_build_messages_skips_excluded(temp_db, strict_enac, monkeypatch):
    from notify.messages import build_messages
    monkeypatch.setattr(config, "NOTIFY_MIN_SCORE", 0)
    init_db()
    strict_enac(no_ground_floor=True)
    _add("https://a/rdc", floor=0)
    rescore()
    assert build_messages([{"kind": "new", "profile": "enac", "url": "https://a/rdc"}]) == []


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

@pytest.fixture
def ui_client(temp_db):
    init_db()
    from ui import app
    app.config["TESTING"] = True
    return app.test_client()


def test_ui_hides_excluded_by_default(ui_client, strict_enac):
    strict_enac(no_ground_floor=True, apl_required=True)
    _add("https://a/rdc", floor=0)
    _add("https://a/ok", floor=2)
    rescore()

    html = ui_client.get("/?profile=enac").get_data(as_text=True)
    assert "https://a/ok" in html and "https://a/rdc" not in html
    assert "Critères ENAC : APL acceptées · pas de rez-de-chaussée" in html
    assert "1 annonce exclue" in html
    assert "excl=only" in html

    html = ui_client.get("/?profile=enac&excl=only").get_data(as_text=True)
    assert "https://a/rdc" in html and "https://a/ok" not in html
    assert "⛔ rez-de-chaussée" in html

    html = ui_client.get("/?profile=enac&excl=show").get_data(as_text=True)
    assert "https://a/rdc" in html and "https://a/ok" in html


def test_ui_without_requirements_shows_no_filter(ui_client, strict_enac):
    strict_enac()
    _add("https://a/1", floor=0)
    rescore()
    html = ui_client.get("/?profile=enac").get_data(as_text=True)
    assert "https://a/1" in html
    assert 'name="excl"' not in html and "requirements-bar" not in html


def test_map_data_hides_excluded(ui_client, strict_enac):
    strict_enac(no_ground_floor=True)
    _add("https://a/rdc", floor=0)
    _add("https://a/ok", floor=2)
    rescore()
    urls = {l["url"] for l in ui_client.get("/api/map-data?profile=enac").get_json()["listings"]}
    assert urls == {"https://a/ok"}
    urls = {l["url"] for l in ui_client.get("/api/map-data?profile=enac&excl=show").get_json()["listings"]}
    assert urls == {"https://a/ok", "https://a/rdc"}
