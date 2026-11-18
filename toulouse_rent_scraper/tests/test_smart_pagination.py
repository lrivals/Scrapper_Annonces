# tests/test_smart_pagination.py
# =========================
# Pagination intelligente : arrêt dès que les pages ne contiennent plus que des annonces
# publiées avant le dernier passage de la recherche
# =========================

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import config
from config import SEARCH_PROFILES
from scrapers.smart_pagination import PaginationPlan, annonce_date

NOW = datetime(2026, 11, 18, 13, 5)


def _state(entries):
    config.SEARCH_STATE_FILE.write_text(json.dumps(entries), encoding="utf-8")


def _recent_state(key="Fake|blagnac", last=NOW - timedelta(hours=5), full=NOW - timedelta(days=2)):
    _state({key: {"last_scan_at": last.isoformat(), "last_full_scan_at": full.isoformat()}})


def _ad(day, url=None):
    return {"url": url or f"https://x.test/{day}", "details": {"published_at": day}}


class TestPlan:

    def test_first_pass_is_full(self):
        plan = PaginationPlan("Fake", "blagnac", now=NOW)
        assert plan.full_scan and plan.cutoff is None
        assert plan.stale_reason([_ad("2020-01-01")], 3) is None

    def test_cutoff_from_last_scan_with_margin(self):
        _recent_state()
        plan = PaginationPlan("Fake", "blagnac", now=NOW)
        assert not plan.full_scan
        assert plan.cutoff.isoformat() == "2026-11-17"     # dernier passage le 18, marge 1 jour

    def test_page_older_than_cutoff_is_stale(self):
        _recent_state()
        plan = PaginationPlan("Fake", "blagnac", now=NOW)
        assert plan.stale_reason([_ad("2026-11-16"), _ad("2026-10-01")], 2)
        # Une seule annonce récente suffit à lire la page suivante
        assert plan.stale_reason([_ad("2026-11-16"), _ad("2026-11-17")], 2) is None

    def test_lbc_listed_at_wins_over_first_publication(self):
        ad = {"url": "u", "listed_at": "2026-11-18", "details": {"published_at": "2026-09-01"}}
        assert annonce_date(ad).isoformat() == "2026-11-18"
        _recent_state()
        assert PaginationPlan("Fake", "blagnac", now=NOW).stale_reason([ad], 2) is None

    def test_undated_page_uses_known_urls(self):
        _recent_state()
        plan = PaginationPlan("Fake", "blagnac", now=NOW)
        ads = [{"url": "a"}, {"url": "b"}, _ad("2026-01-01")]
        assert plan.stale_reason(ads, 2, known=lambda url: True)
        assert plan.stale_reason(ads, 2, known=lambda url: url != "b") is None

    def test_full_scan_again_after_a_week(self):
        _recent_state(full=NOW - timedelta(days=8))
        plan = PaginationPlan("Fake", "blagnac", now=NOW)
        assert plan.full_scan and "7 jours" in plan.reason

    def test_forced_or_disabled(self, monkeypatch):
        _recent_state()
        assert PaginationPlan("Fake", "blagnac", now=NOW, force_full=True).full_scan
        monkeypatch.setattr(config, "SMART_PAGINATION", False)
        assert PaginationPlan("Fake", "blagnac", now=NOW).full_scan

    def test_record_only_complete_scans(self):
        plan = PaginationPlan("Fake", "blagnac", now=NOW)
        assert not plan.record("error")
        assert not config.SEARCH_STATE_FILE.exists()
        assert plan.record("stale")
        entry = json.loads(config.SEARCH_STATE_FILE.read_text())["Fake|blagnac"]
        assert entry == {"last_scan_at": NOW.isoformat(timespec="seconds")}   # pas un parcours complet
        assert plan.record("end")
        entry = json.loads(config.SEARCH_STATE_FILE.read_text())["Fake|blagnac"]
        assert entry["last_full_scan_at"] == entry["last_scan_at"]


# ---- Intégration BaseScraper (pagination par URLs) ----

from tests.test_base_scraper import FakeScraper, _make_page, _session  # noqa: E402


class DatedFakeScraper(FakeScraper):
    """Page 1 : annonce du jour ; pages suivantes : annonces anciennes."""

    def extract_annonce(self, card):
        day = "2026-11-18" if card.title == "Annonce 2" else "2026-10-01"
        return {"title": card.title, "url": card.url, "details": {"published_at": day}}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr("scrapers.base.time.sleep", lambda *_: None)
    monkeypatch.setattr("scrapers.base.LOG_DIR", MagicMock())


def test_scraper_stops_on_stale_page():
    _recent_state(last=datetime.now() - timedelta(hours=5), full=datetime.now() - timedelta(days=1))
    page = _make_page()
    urls = [f"https://fake.test/p{i}" for i in range(1, 6)]
    scraper = DatedFakeScraper(urls, SEARCH_PROFILES["blagnac"])
    with patch("scrapers.base.chrome_session", _session(page)):
        results = scraper.scrape()
    # accueil + p1 (récente) + p2 (ancienne → arrêt) ; p3…p5 jamais ouvertes
    assert page.goto_calls == 3 and len(results) == 2
    assert scraper.scan_status == "stale"
    entry = json.loads(config.SEARCH_STATE_FILE.read_text())["Fake|blagnac"]
    assert entry["last_scan_at"] > (datetime.now() - timedelta(minutes=1)).isoformat()


def test_scraper_full_scan_without_history():
    page = _make_page()
    urls = [f"https://fake.test/p{i}" for i in range(1, 4)]
    scraper = DatedFakeScraper(urls, SEARCH_PROFILES["blagnac"])
    with patch("scrapers.base.chrome_session", _session(page)):
        assert len(scraper.scrape()) == 3
    assert scraper.scan_status == "max"
    assert "last_full_scan_at" in json.loads(config.SEARCH_STATE_FILE.read_text())["Fake|blagnac"]


def test_blocked_scan_not_recorded(monkeypatch):
    from scrapers.base import BaseScraper
    monkeypatch.setattr("scrapers.antibot.time.sleep", lambda *_: None)
    page = _make_page(blocked_after_goto=1)
    scraper = DatedFakeScraper(["https://fake.test/p1"], SEARCH_PROFILES["blagnac"])
    with patch("scrapers.base.chrome_session", _session(page)), \
         patch.object(BaseScraper, "wait_for_challenge", return_value=False):
        scraper.scrape()
    assert not config.SEARCH_STATE_FILE.exists()


# ---- Bien'ici (API) ----

def test_bienici_stops_on_stale_page():
    from scrapers.bienici import BienIciScraper
    from tests.test_bienici import _ad as bienici_ad

    _recent_state(key="Bien'ici|enac", last=datetime.now() - timedelta(hours=5),
                  full=datetime.now() - timedelta(days=1))
    today = datetime.now().strftime("%Y-%m-%dT08:00:00.000Z")
    pages = iter([
        {"total": 99, "realEstateAds": [bienici_ad("a", publicationDate=today), bienici_ad("b")]},
        {"total": 99, "realEstateAds": [bienici_ad("c"), bienici_ad("d")]},      # 10/11 : déjà vues
        {"total": 99, "realEstateAds": [bienici_ad("e"), bienici_ad("f")]},
    ])
    scraper = BienIciScraper(SEARCH_PROFILES["enac"])

    def get_json(url, params=None, timeout=30):
        scraper._requests += 1
        return next(pages)

    with patch.object(scraper, "zone_ids", return_value=["-35735"]), \
         patch.object(scraper, "get_json", side_effect=get_json), \
         patch("scrapers.bienici.BIENICI_PAGE_SIZE", 2), \
         patch("scrapers.api_base.time.sleep"):
        results = scraper.scrape()
    assert [r["url"].rsplit("/", 1)[1] for r in results] == ["a", "b", "c", "d"]
    assert scraper.scan_status == "stale"


def test_lbc_search_annonce_carries_index_date():
    from scrapers.detail_extractors.lbc_json import search_ad_to_annonce
    ad = {
        "list_id": 123, "url": "https://www.leboncoin.fr/ad/locations/123", "subject": "T2",
        "price": [650], "first_publication_date": "2026-09-01 10:00:00",
        "index_date": "2026-11-18 07:30:00",
    }
    annonce = search_ad_to_annonce(ad)
    assert annonce["listed_at"] == "2026-11-18"
    assert annonce["details"]["published_at"] == "2026-09-01"
