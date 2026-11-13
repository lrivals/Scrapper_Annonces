# tests/test_pipeline.py
# =========================
# Pipeline de scraping avec scrapers et géocodage simulés
# =========================

from unittest.mock import MagicMock, patch

import pytest

from config import SEARCH_PROFILES
from pipeline import RunStats, process_annonces, run_scraping
from storage.sqlite import init_db

ENAC = SEARCH_PROFILES["enac"]
BLAGNAC = SEARCH_PROFILES["blagnac"]


def _raw(n, price=450, title="Studio", site="LeBonCoin"):
    return {"site": site, "title": f"{title} {n}", "price": f"{price} €",
            "location_raw": "Rangueil", "url": f"https://lbc.fr/{site}/{n}"}


KNOWN_COORDS_SEEN = []


def _matches(annonce, profiles=None, known_coords=None):
    """match_profiles simulé : ENAC si prix ≤ 500, sinon Blagnac."""
    KNOWN_COORDS_SEEN.append(known_coords)
    price = int(annonce["price"].split()[0])
    lat, lon = known_coords or (43.56, 1.46)
    enriched = {**annonce, "price": price, "lat": lat, "lon": lon, "distance_enac_km": 1.0}
    if price > 750:
        return None, []
    return enriched, [(ENAC if price <= 500 else BLAGNAC, 1.5)]


@pytest.fixture
def db(temp_db):
    init_db()
    with patch("filters.price_and_distance.match_profiles", side_effect=_matches):
        yield temp_db


def test_process_counts_new_then_unchanged(db):
    raw = [_raw(1), _raw(2, price=700), _raw(3, price=900)]
    stats = process_annonces(raw, "LeBonCoin")
    assert (stats.raw, stats.kept, stats.rejected, stats.inserted) == (3, 2, 1, 2)
    assert stats.new_by_profile == {"enac": 1, "blagnac": 1}

    again = process_annonces(raw, "LeBonCoin")
    assert (again.inserted, again.unchanged) == (0, 2)
    assert not again.new_by_profile


def test_process_rejects_invalid(db):
    stats = process_annonces([{"site": "LeBonCoin", "title": "", "price": "400 €",
                               "location_raw": "x", "url": "https://lbc.fr/x"}], "LeBonCoin")
    assert stats.validation_errors == 1 and stats.rejected == 1


def test_runstats_addition():
    total = RunStats(raw=1, inserted=1)
    total.new_by_profile["enac"] = 1
    other = RunStats(raw=2, duplicates=1)
    other.new_by_profile["enac"] = 2
    total += other
    assert (total.raw, total.inserted, total.duplicates) == (3, 1, 1)
    assert total.new_by_profile["enac"] == 3


def _fake_scraper_class(results_by_profile):
    class Fake:
        def __init__(self, profile, unattended=False):
            self.profile = profile

        def site_name(self):
            return "LeBonCoin"

        def search_url(self):
            return None if self.profile.key == "unconfigured" else "https://lbc.fr/search"

        def scrape(self):
            return results_by_profile.get(self.profile.key, [])
    return Fake


def test_run_scraping_loops_profiles_and_pauses_between_searches(db):
    Fake = _fake_scraper_class({"enac": [_raw(1)], "blagnac": [_raw(2, price=700)]})
    sleep = MagicMock()
    with patch("scrapers.get_scraper_class", return_value=Fake), \
         patch("reporting.generator.generate_summary_reports") as reports:
        total = run_scraping([ENAC, BLAGNAC], ["leboncoin"], sleep=sleep, enrich=False)
    assert total.inserted == 2
    assert total.new_by_profile == {"enac": 1, "blagnac": 1}
    assert sleep.call_count == 1          # une pause entre les deux recherches
    reports.assert_called_once()


def test_run_scraping_skips_unconfigured_site_without_pause(db):
    Fake = _fake_scraper_class({"enac": [_raw(1)]})
    unconfigured = MagicMock(key="unconfigured", label="X")
    sleep = MagicMock()
    with patch("scrapers.get_scraper_class", return_value=Fake), \
         patch("reporting.generator.generate_summary_reports"):
        total = run_scraping([unconfigured, ENAC], ["leboncoin"], sleep=sleep, enrich=False)
    assert total.inserted == 1
    sleep.assert_not_called()


def test_events_new_and_price_drop(db, monkeypatch):
    import pipeline
    monkeypatch.setattr(pipeline, "NOTIFY_PRICE_DROP_EUR", 20)
    first = process_annonces([_raw(1, price=480), _raw(2, price=450)], "LeBonCoin")
    assert [e["kind"] for e in first.events] == ["new", "new"]

    again = process_annonces([_raw(1, price=455), _raw(2, price=440)], "LeBonCoin")
    assert again.events == [{"kind": "price_drop", "profile": "enac",
                             "url": "https://lbc.fr/LeBonCoin/1", "old_price": 480}]


def test_run_scraping_rescores_and_notifies(db):
    Fake = _fake_scraper_class({"enac": [_raw(1)]})
    with patch("scrapers.get_scraper_class", return_value=Fake), \
         patch("reporting.generator.generate_summary_reports"), \
         patch("notify.notify_events", return_value=1) as notify_events:
        run_scraping([ENAC], ["leboncoin"], sleep=MagicMock(), enrich=False)
    events = notify_events.call_args.args[0]
    assert events == [{"kind": "new", "profile": "enac", "url": "https://lbc.fr/LeBonCoin/1"}]
    import sqlite3
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT score FROM annonce_profiles").fetchone()[0] is not None


# ---- Sprint 16 — ouverture des fiches dans le pipeline ----

def _fake_open(calls, details=None):
    """open_annonces simulé : enregistre l'appel et écrit `details` dans chaque fiche."""
    from scrapers.enricher import EnrichStats
    from storage.sqlite import update_annonce_enrichment

    def fake(annonces, unattended=False, budget=None, blocked_since=None, label=""):
        calls.append(("open", [a["url"] for a in annonces]))
        for a in annonces:
            update_annonce_enrichment(a["url"], {"enrichment_status": "done", **(details or {})})
        return EnrichStats(total=len(annonces), opened=len(annonces), enriched=len(annonces))
    return fake


def _run(calls, details=None, **kwargs):
    from notify.messages import build_messages
    Fake = _fake_scraper_class({"enac": [_raw(1)]})
    sent = []

    def notify_events(events):
        calls.append(("notify", None))
        sent.extend(build_messages(events))
        return len(sent)

    with patch("scrapers.get_scraper_class", return_value=Fake), \
         patch("reporting.generator.generate_summary_reports"), \
         patch("scrapers.enricher.open_annonces", side_effect=_fake_open(calls, details)), \
         patch("scoring.rescore", side_effect=lambda *a: calls.append(("rescore", None))), \
         patch("notify.notify_events", side_effect=notify_events):
        total = run_scraping([ENAC], ["leboncoin"], sleep=MagicMock(), **kwargs)
    return total, sent


def test_run_opens_details_before_rescore_and_notify(db):
    calls = []
    total, _ = _run(calls)
    assert [c[0] for c in calls] == ["rescore", "open", "rescore", "notify"]
    assert calls[1][1] == ["https://lbc.fr/LeBonCoin/1"]
    assert (total.opened, total.enriched) == (1, 1)
    assert total.retained_urls == ["https://lbc.fr/LeBonCoin/1"]


def test_no_enrich_opens_nothing(db):
    calls = []
    total, _ = _run(calls, enrich=False)
    assert [c[0] for c in calls] == ["rescore", "notify"]
    assert total.opened == 0


def test_exclusion_revealed_by_detail_page_is_not_notified(db, monkeypatch):
    import config
    from config import Requirements
    from filters.requirements import save_requirements
    monkeypatch.setattr(config, "NOTIFY_MIN_SCORE", 0)
    save_requirements("enac", Requirements(max_dpe="E"))

    calls = []
    # vrai rescore (critères), open_annonces simulé qui révèle un DPE G
    from scoring import rescore as real_rescore

    def rescore(*a):
        calls.append(("rescore", None))
        return real_rescore(*a)

    from notify.messages import build_messages
    Fake = _fake_scraper_class({"enac": [_raw(1)]})
    sent = []
    with patch("scrapers.get_scraper_class", return_value=Fake), \
         patch("reporting.generator.generate_summary_reports"), \
         patch("scrapers.enricher.open_annonces", side_effect=_fake_open(calls, {"dpe_rating": "G"})), \
         patch("scoring.rescore", side_effect=rescore), \
         patch("notify.notify_events", side_effect=lambda ev: sent.extend(build_messages(ev)) or 0):
        total = run_scraping([ENAC], ["leboncoin"], sleep=MagicMock())
    assert total.events and total.opened == 1
    assert sent == []

    # Contre-épreuve : même annonce avec un DPE C → notifiée, fiche complète dans le message
    calls.clear()
    sent.clear()
    import sqlite3
    with sqlite3.connect(db) as con:
        con.execute("DELETE FROM annonce_profiles")
        con.execute("DELETE FROM annonces")
    with patch("scrapers.get_scraper_class", return_value=Fake), \
         patch("reporting.generator.generate_summary_reports"), \
         patch("scrapers.enricher.open_annonces",
               side_effect=_fake_open(calls, {"dpe_rating": "C", "surface_m2": 38, "nb_rooms": 2, "charges": 40})), \
         patch("scoring.rescore", side_effect=rescore), \
         patch("notify.notify_events", side_effect=lambda ev: sent.extend(build_messages(ev)) or 0):
        run_scraping([ENAC], ["leboncoin"], sleep=MagicMock())
    assert len(sent) == 1
    assert "T2 · 38 m² · 450 € (+40 € ch.) · DPE C" in sent[0]["body"]


def test_browser_failure_during_opening_still_notifies(db):
    calls = []
    Fake = _fake_scraper_class({"enac": [_raw(1)]})
    with patch("scrapers.get_scraper_class", return_value=Fake), \
         patch("reporting.generator.generate_summary_reports"), \
         patch("scrapers.enricher.open_annonces", side_effect=RuntimeError("Chrome absent")), \
         patch("notify.notify_events", return_value=0) as notify_events:
        total = run_scraping([ENAC], ["leboncoin"], sleep=MagicMock())
    notify_events.assert_called_once()
    assert total.opened == 0
