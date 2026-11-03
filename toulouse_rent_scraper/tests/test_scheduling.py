# tests/test_scheduling.py
# =========================
# Runs planifiés (Sprint 13.2) : verrou, mémoire des blocages, mode unattended
# =========================

import multiprocessing
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from config import SEARCH_PROFILES
from scrapers import antibot
from utils.lock import AlreadyRunning, is_locked, run_lock


def _hold_lock(path, ready, release):
    with run_lock(path):
        ready.set()
        release.wait(5)


class TestLock:
    def test_second_process_is_refused(self, tmp_path):
        path = tmp_path / "x.lock"
        ready, release = multiprocessing.Event(), multiprocessing.Event()
        proc = multiprocessing.Process(target=_hold_lock, args=(path, ready, release))
        proc.start()
        try:
            assert ready.wait(5)
            assert is_locked(path)
            with pytest.raises(AlreadyRunning, match="pid"):
                with run_lock(path):
                    pass
        finally:
            release.set()
            proc.join(5)
        assert not is_locked(path)

    def test_lock_released_after_exception(self, tmp_path):
        path = tmp_path / "x.lock"
        with pytest.raises(ValueError):
            with run_lock(path):
                raise ValueError
        assert not is_locked(path)

    def test_cli_exits_when_locked(self):
        import main
        with patch("utils.lock.run_lock", side_effect=AlreadyRunning("pid 1")), \
             patch.object(main, "cmd_scrape") as scrape:
            with pytest.raises(SystemExit) as exit_info:
                main.main(["scrape"])
        assert exit_info.value.code == main.EXIT_ALREADY_RUNNING
        scrape.assert_not_called()


class TestBlockMemory:
    def test_record_and_cooldown(self, tmp_path):
        path = tmp_path / "blocks.json"
        now = datetime(2026, 11, 3, 12, 0)
        antibot.record_block("LeBonCoin", path=path, now=now)
        assert antibot.recently_blocked("LeBonCoin", hours=6, path=path, now=now + timedelta(hours=5))
        assert not antibot.recently_blocked("LeBonCoin", hours=6, path=path, now=now + timedelta(hours=7))
        assert not antibot.recently_blocked("SeLoger", path=path, now=now)

    def test_corrupt_file_ignored(self, tmp_path):
        path = tmp_path / "blocks.json"
        path.write_text("{oops")
        assert antibot.recently_blocked("LeBonCoin", path=path) is None


class _Fake:
    created = []

    def __init__(self, profile, unattended=False):
        self.profile, self.unattended = profile, unattended
        _Fake.created.append(self)

    def site_name(self):
        return "LeBonCoin"

    def search_url(self):
        return "https://lbc.fr/s"

    def scrape(self):
        self.scraped = True
        return []


@pytest.fixture
def fake_pipeline(temp_db):
    from storage.sqlite import init_db
    init_db()
    _Fake.created = []
    with patch("scrapers.get_scraper_class", return_value=_Fake), \
         patch("reporting.generator.generate_summary_reports"):
        yield


def test_unattended_skips_recently_blocked_site(fake_pipeline):
    from pipeline import run_scraping
    antibot.record_block("LeBonCoin")
    run_scraping([SEARCH_PROFILES["enac"]], ["leboncoin"], sleep=MagicMock(), unattended=True)
    assert not hasattr(_Fake.created[0], "scraped")


def test_manual_run_still_scrapes_blocked_site(fake_pipeline):
    from pipeline import run_scraping
    antibot.record_block("LeBonCoin")
    run_scraping([SEARCH_PROFILES["enac"]], ["leboncoin"], sleep=MagicMock())
    assert _Fake.created[0].scraped and not _Fake.created[0].unattended


def test_scraper_challenge_timeout_and_notification():
    from scrapers.leboncoin import LeBonCoinScraper
    scraper = LeBonCoinScraper(unattended=True)
    assert scraper.challenge_timeout == 600
    with patch("scrapers.antibot.wait_for_challenge", return_value=False) as wait, \
         patch("notify.notify_captcha") as captcha:
        assert scraper.wait_for_challenge(MagicMock()) is False
        wait.call_args.kwargs["on_challenge"]()
    assert wait.call_args.args[1] == 600
    captcha.assert_called_once_with("LeBonCoin", 600)
    assert antibot.recently_blocked("LeBonCoin")


def test_ui_reports_external_run(temp_db):
    from storage.sqlite import init_db
    from ui import app
    init_db()
    with patch("ui.routes.is_locked", return_value=True):
        data = app.test_client().get("/scraping-status").get_json()
    assert data["running"] is True and "hors de l'interface" in data["last_line"]
