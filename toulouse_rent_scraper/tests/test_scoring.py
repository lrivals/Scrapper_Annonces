# tests/test_scoring.py
# =========================
# Score d'intérêt (Sprint 13.3)
# =========================

import json
import sqlite3

import pytest

from config import SEARCH_PROFILES
from scoring import (
    NEUTRAL, compute_score, describe, distance_score, dpe_score, furnished_score,
    median_price_per_m2, price_per_m2_score, rent_score, rescore,
)
from storage.sqlite import init_db, insert_annonce, upsert_annonce_profile, update_annonce_enrichment

ENAC = SEARCH_PROFILES["enac"]        # cible 350 €, max 500 €, 10 km
BLAGNAC = SEARCH_PROFILES["blagnac"]  # cible 600 €, pas de plafond (note nulle à 900 €), 8 km


class TestCriteria:
    @pytest.mark.parametrize("price,charges,expected", [
        (300, None, 1.0),     # sous la cible
        (350, None, 1.0),     # à la cible
        (425, None, 0.5),     # à mi-chemin
        (500, None, 0.0),     # au budget max
        (450, 60, 0.0),       # charges comprises : 510 > max
        (400, 25, 0.5),       # 425 CC
        (None, None, NEUTRAL),
    ])
    def test_rent_enac(self, price, charges, expected):
        assert rent_score(price, charges, ENAC) == pytest.approx(expected)

    def test_rent_without_max_budget(self):
        assert rent_score(600, None, BLAGNAC) == pytest.approx(1.0)
        assert rent_score(750, None, BLAGNAC) == pytest.approx(0.5)
        assert rent_score(900, None, BLAGNAC) == pytest.approx(0.0)

    @pytest.mark.parametrize("dist,expected", [(0, 1.0), (5, 0.5), (10, 0.0), (12, 0.0), (None, NEUTRAL)])
    def test_distance(self, dist, expected):
        assert distance_score(dist, ENAC) == pytest.approx(expected)

    @pytest.mark.parametrize("ppm2,median,expected", [
        (10, 20, 1.0), (20, 20, 0.5), (30, 20, 0.0), (None, 20, NEUTRAL), (20, None, NEUTRAL),
    ])
    def test_price_per_m2(self, ppm2, median, expected):
        assert price_per_m2_score(ppm2, median) == pytest.approx(expected)

    def test_furnished(self):
        assert (furnished_score(True), furnished_score(False), furnished_score(None)) == (1.0, 0.0, NEUTRAL)

    @pytest.mark.parametrize("rating,expected", [
        ("A", 1.0), ("c", 1.0), ("D", 0.6), ("E", 0.3), ("G", 0.0), (None, NEUTRAL), ("?", NEUTRAL),
    ])
    def test_dpe(self, rating, expected):
        assert dpe_score(rating) == expected

    def test_median(self):
        rows = [{"price": 400, "surface_m2": 20}, {"price": 600, "surface_m2": 20}, {"price": 500, "surface_m2": None}]
        assert median_price_per_m2(rows) == 25


class TestComputeScore:
    def test_ideal_annonce_scores_100(self):
        annonce = {"price": 350, "charges": 0, "surface_m2": 30, "furnished": True, "dpe_rating": "B"}
        score, detail = compute_score(annonce, 0, ENAC, median_ppm2=30)
        assert score == 100
        assert set(detail) == {"loyer", "distance", "prix_m2", "meuble", "dpe"}

    def test_unknown_criteria_are_neutral(self):
        score, _ = compute_score({"price": 425}, 5, ENAC)
        assert score == 50

    def test_good_deal_beats_bad_deal(self):
        good = {"price": 380, "surface_m2": 25, "furnished": True, "dpe_rating": "C"}
        bad = {"price": 495, "surface_m2": 12, "furnished": False, "dpe_rating": "G"}
        assert compute_score(good, 2, ENAC, 20)[0] > 80 > 20 > compute_score(bad, 9, ENAC, 20)[0]

    def test_describe(self):
        text = describe(json.dumps({"loyer": 0.8, "distance": 0.55}))
        assert text == "Loyer CC 8/10 · Distance 6/10"
        assert describe(None) == "" and describe("{oops") == ""


class TestRescore:
    def _add(self, url, price, distance, **details):
        insert_annonce({"site": "LeBonCoin", "title": "T", "price": price,
                        "location_raw": "Rangueil", "url": url})
        upsert_annonce_profile(url, "enac", distance)
        if details:
            update_annonce_enrichment(url, details)

    def test_scores_saved_per_profile(self, temp_db):
        init_db()
        self._add("https://a/1", 360, 1.0, surface_m2=25, furnished=True, dpe_rating="B")
        self._add("https://a/2", 490, 9.0, surface_m2=15, furnished=False, dpe_rating="F")
        assert rescore(["enac"]) == 2
        with sqlite3.connect(temp_db) as con:
            rows = dict(con.execute(
                "SELECT a.url, ap.score FROM annonce_profiles ap JOIN annonces a ON a.id = ap.annonce_id"
            ).fetchall())
            detail = json.loads(con.execute("SELECT score_detail FROM annonce_profiles LIMIT 1").fetchone()[0])
        assert rows["https://a/1"] > 80 > rows["https://a/2"]
        assert "loyer" in detail

    def test_enrichment_changes_score(self, temp_db):
        init_db()
        self._add("https://a/1", 400, 3.0)
        read = lambda: sqlite3.connect(temp_db).execute("SELECT score FROM annonce_profiles").fetchone()[0]  # noqa: E731
        rescore(["enac"])
        before = read()  # meublé et DPE inconnus : neutres
        update_annonce_enrichment("https://a/1", {"dpe_rating": "G", "furnished": False})
        rescore(["enac"])
        assert read() == pytest.approx(before - 10)  # 2 critères de poids 10 passent de 0.5 à 0
