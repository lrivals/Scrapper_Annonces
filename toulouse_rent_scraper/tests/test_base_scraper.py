# tests/test_base_scraper.py
# =========================
# Orchestration de BaseScraper.scrape() avec une page simulée (aucun Chrome)
# =========================

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from scrapers.base import BaseScraper
from scrapers.browser import BrowserError


class FakeScraper(BaseScraper):
    def __init__(self, urls, profile=None):
        self._urls = urls
        super().__init__(profile)

    def site_name(self):
        return "Fake"

    def base_url(self):
        return "https://fake.test"

    def search_url(self):
        return self._urls[0] if self._urls else None

    def search_urls(self):
        return self._urls

    def card_selector(self):
        return "article"

    def fallback_card_selectors(self):
        return []

    def next_page_selector(self):
        return "a.next"

    def extract_annonce(self, card):
        return {"title": card.title, "url": card.url}


def _make_page(blocked_after_goto=None):
    page = MagicMock()
    page.url = "https://fake.test/search"
    page.evaluate.return_value = 0          # scrollHeight
    page.inner_text.return_value = "ok"
    page.content.return_value = "<html>ok</html>"
    page.title.return_value = "Résultats"
    page.viewport_size = {"width": 1200, "height": 800}
    page.goto_calls = 0

    def goto(url, **kwargs):
        page.goto_calls += 1
        page.url = url
        if blocked_after_goto and page.goto_calls >= blocked_after_goto:
            page.url = "https://geo.captcha-delivery.com/challenge"

    page.goto.side_effect = goto

    def cards(selector):
        card = MagicMock()
        card.title, card.url = f"Annonce {page.goto_calls}", f"https://fake.test/{page.goto_calls}"
        return [card]

    page.query_selector_all.side_effect = cards
    page.query_selector.return_value = None   # pas de popup cookies / bouton suivant
    return page


def _session(page):
    @contextmanager
    def session(*args, **kwargs):
        yield MagicMock(), page
    return session


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr("scrapers.base.time.sleep", lambda *_: None)
    monkeypatch.setattr("scrapers.base.LOG_DIR", MagicMock())


def test_scrapes_first_page_and_direct_url_pages():
    page = _make_page()
    urls = ["https://fake.test/p1", "https://fake.test/p2", "https://fake.test/p3"]
    with patch("scrapers.base.chrome_session", _session(page)):
        results = FakeScraper(urls).scrape()
    # navigation : accueil + recherche, puis pages 2 et 3
    assert page.goto_calls == 4
    assert len(results) == 3


def test_pagination_capped_by_max_pages(monkeypatch):
    monkeypatch.setattr("scrapers.base.MAX_PAGES_PER_SITE", 2)
    page = _make_page()
    urls = [f"https://fake.test/p{i}" for i in range(1, 6)]
    with patch("scrapers.base.chrome_session", _session(page)):
        results = FakeScraper(urls).scrape()
    assert len(results) == 2


def test_stops_cleanly_when_blocked_without_resolution(monkeypatch):
    monkeypatch.setattr("scrapers.antibot.time.sleep", lambda *_: None)
    page = _make_page(blocked_after_goto=1)
    scraper = FakeScraper(["https://fake.test/p1"])
    with patch("scrapers.base.chrome_session", _session(page)), \
         patch.object(BaseScraper, "wait_for_challenge", return_value=False):
        assert scraper.scrape() == []


def test_no_search_url_skips_site():
    session = MagicMock()
    with patch("scrapers.base.chrome_session", session):
        assert FakeScraper([]).scrape() == []
    session.assert_not_called()


def test_browser_error_is_reported_not_raised():
    @contextmanager
    def broken(*args, **kwargs):
        raise BrowserError("Chrome introuvable")
        yield
    with patch("scrapers.base.chrome_session", broken):
        assert FakeScraper(["https://fake.test/p1"]).scrape() == []


def test_selector_missing_dumps_debug():
    page = _make_page()
    page.wait_for_selector.side_effect = Exception("not found")
    scraper = FakeScraper(["https://fake.test/p1"])
    with patch("scrapers.base.chrome_session", _session(page)), \
         patch.object(FakeScraper, "_dump_debug") as dump:
        assert scraper.scrape() == []
    dump.assert_called_once()


def test_navigation_and_pagination_use_delay_hooks():
    page = _make_page()
    urls = ["https://fake.test/p1", "https://fake.test/p2", "https://fake.test/p3"]
    scraper = FakeScraper(urls)
    scraper.step_delay = MagicMock()
    scraper.page_delay = MagicMock()
    with patch("scrapers.base.chrome_session", _session(page)):
        scraper.scrape()
    assert scraper.step_delay.call_count == 1   # entre accueil et recherche
    assert scraper.page_delay.call_count == 2   # avant les pages 2 et 3


def test_picks_selector_with_most_cards():
    class Multi(FakeScraper):
        def fallback_card_selectors(self):
            return ["article.new"]

    page = MagicMock()
    page.query_selector_all.side_effect = lambda sel: (
        [MagicMock()] * 5 if sel == "article" else [MagicMock()] * 35
    )
    selector, cards = Multi(["https://fake.test/p1"])._best_selector_cards(page, "article")
    assert selector == "article.new" and len(cards) == 35
