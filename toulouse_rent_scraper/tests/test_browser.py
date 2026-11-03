# tests/test_browser.py
# =========================
# Tests de la session Chrome (sans lancer Chrome) et de la détection anti-bot
# =========================

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import MagicMock, patch

import pytest

from scrapers import antibot
from scrapers.browser import (
    BrowserError, find_chrome_binary, free_port, port_in_use, wait_for_cdp,
)


class _CdpHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"Browser": "Chrome/fake"}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_cdp():
    server = HTTPServer(("127.0.0.1", 0), _CdpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


class TestBrowser:
    def test_free_port_is_free(self):
        port = free_port()
        assert 1024 < port < 65536
        assert not port_in_use(port)

    def test_wait_for_cdp_ok(self, fake_cdp):
        assert wait_for_cdp(fake_cdp, timeout=3)["Browser"] == "Chrome/fake"

    def test_wait_for_cdp_timeout(self):
        with pytest.raises(BrowserError, match="injoignable"):
            wait_for_cdp(free_port(), timeout=0.5)

    def test_wait_for_cdp_process_died(self):
        proc = MagicMock()
        proc.poll.return_value = 1
        proc.returncode = 1
        with pytest.raises(BrowserError, match="arrêté"):
            wait_for_cdp(free_port(), timeout=2, proc=proc)

    def test_missing_configured_binary(self):
        with pytest.raises(BrowserError, match="introuvable"):
            find_chrome_binary("/nope/chrome")

    def test_no_binary_in_path(self):
        with patch("scrapers.browser.shutil.which", return_value=None):
            with pytest.raises(BrowserError, match="PATH"):
                find_chrome_binary(None)

    def test_locked_profile_refused(self, tmp_path):
        from scrapers.browser import chrome_session
        (tmp_path / "SingletonLock").symlink_to("host-1234")
        with pytest.raises(BrowserError, match="déjà utilisé"):
            with chrome_session(profile_dir=tmp_path, port=0):
                pass

    def test_lock_held_by_live_process(self, tmp_path):
        import os, socket
        from scrapers.browser import _profile_locked
        (tmp_path / "SingletonLock").symlink_to(f"{socket.gethostname()}-{os.getpid()}")
        assert _profile_locked(tmp_path)
        assert (tmp_path / "SingletonLock").is_symlink()

    def test_stale_lock_removed(self, tmp_path):
        import socket
        from scrapers.browser import _profile_locked
        (tmp_path / "SingletonLock").symlink_to(f"{socket.gethostname()}-999999999")
        (tmp_path / "SingletonSocket").symlink_to("/tmp/nope/SingletonSocket")
        assert not _profile_locked(tmp_path)
        assert not (tmp_path / "SingletonLock").is_symlink()
        assert not (tmp_path / "SingletonSocket").is_symlink()

    def test_no_lock(self, tmp_path):
        from scrapers.browser import _profile_locked
        assert not _profile_locked(tmp_path)


def _page(url="https://www.leboncoin.fr/recherche", text="Résultats", title="Locations"):
    page = MagicMock()
    page.url = url
    page.inner_text.return_value = text
    page.content.return_value = f"<html>{text}</html>"
    page.title.return_value = title
    return page


class TestAntibot:
    def test_normal_page(self):
        assert not antibot.is_page_blocked(_page(), site_domain="www.leboncoin.fr")

    def test_datadome_domain(self):
        assert antibot.is_page_blocked(_page(url="https://geo.captcha-delivery.com/x"))

    def test_marker_in_text(self):
        assert antibot.is_page_blocked(_page(text="Nous avons détecté une activité suspecte"))

    def test_redirect_outside_site(self):
        assert antibot.is_page_blocked(_page(url="https://ailleurs.com"), site_domain="www.leboncoin.fr")

    def test_block_title(self):
        assert antibot.is_page_blocked(_page(title="Accès restreint"))

    def test_wait_resolved(self):
        states = iter([True, True, False])
        callback = MagicMock()
        with patch("scrapers.antibot.time.sleep"):
            assert antibot.wait_for_challenge(
                MagicMock(), timeout_seconds=60, is_blocked=lambda p: next(states), on_challenge=callback
            )
        callback.assert_called_once()

    def test_wait_timeout(self):
        with patch("scrapers.antibot.time.sleep"):
            assert not antibot.wait_for_challenge(
                MagicMock(), timeout_seconds=0.01, is_blocked=lambda p: True, poll_seconds=0
            )

    def test_wait_not_blocked_returns_immediately(self):
        callback = MagicMock()
        assert antibot.wait_for_challenge(MagicMock(), is_blocked=lambda p: False, on_challenge=callback)
        callback.assert_not_called()
