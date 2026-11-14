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
import os
import socket

from scrapers.browser import (
    BrowserError, _profile_locked, chrome_env, find_chrome_binary, free_port,
    port_in_use, wait_for_cdp,
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


def _page(url="https://www.leboncoin.fr/recherche", text="Résultats", title="Locations", frames=()):
    page = MagicMock()
    page.url = url
    page.frames = [MagicMock(url=f) for f in frames]
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

    def test_datadome_iframe(self):
        # Challenge DataDome dans une iframe : URL principale et titre du site inchangés
        page = _page(title="leboncoin.fr", frames=(
            "https://www.leboncoin.fr/recherche",
            "https://geo.captcha-delivery.com/captcha/?initialCid=abc",
        ))
        assert antibot.is_page_blocked(page, site_domain="www.leboncoin.fr")

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


class TestProfileLock:
    def test_no_lock(self, tmp_path):
        assert not _profile_locked(tmp_path)

    def test_stale_lock_removed(self, tmp_path):
        # PID très improbable -> processus mort
        os.symlink(f"{socket.gethostname()}-999999999", tmp_path / "SingletonLock")
        os.symlink("123", tmp_path / "SingletonCookie")
        assert not _profile_locked(tmp_path)
        assert not (tmp_path / "SingletonLock").is_symlink()
        assert not (tmp_path / "SingletonCookie").is_symlink()

    def test_live_lock_kept(self, tmp_path):
        os.symlink(f"{socket.gethostname()}-{os.getpid()}", tmp_path / "SingletonLock")
        assert _profile_locked(tmp_path)

    def test_other_host_lock_kept(self, tmp_path):
        os.symlink("autre-machine-999999999", tmp_path / "SingletonLock")
        assert _profile_locked(tmp_path)


class TestChromeEnv:
    def test_no_snap_unchanged(self):
        base = {"PATH": "/usr/bin", "GTK_PATH": "/x", "XDG_DATA_DIRS": "/usr/share"}
        assert chrome_env(base) == base

    def test_snap_leak_without_snap_var(self):
        # Terminal VS Code : variables snap héritées mais pas de $SNAP
        env = chrome_env({
            "GSETTINGS_SCHEMA_DIR": "/home/u/snap/code/275/.local/share/glib-2.0/schemas",
            "GTK_PATH": "/snap/code/275/usr/lib/x86_64-linux-gnu/gtk-3.0",
            "XDG_DATA_DIRS": "/home/u/snap/code/275/.local/share:/snap/code/275/usr/share:/usr/share",
        })
        assert "GSETTINGS_SCHEMA_DIR" not in env and "GTK_PATH" not in env
        assert env["XDG_DATA_DIRS"] == "/usr/share"

    def test_snap_vars_cleaned(self):
        env = chrome_env({
            "SNAP": "/snap/code/275",
            "PATH": "/usr/bin",
            "GSETTINGS_SCHEMA_DIR": "/snap/schemas",
            "GTK_PATH": "/snap/gtk",
            "XDG_DATA_DIRS": "/snap/share:/usr/share",
            "XDG_DATA_DIRS_VSCODE_SNAP_ORIG": "/usr/share",
            "GDK_BACKEND_VSCODE_SNAP_ORIG": "",
            "GDK_BACKEND": "x11",
        })
        assert env["PATH"] == "/usr/bin"
        assert "GSETTINGS_SCHEMA_DIR" not in env and "GTK_PATH" not in env
        assert env["XDG_DATA_DIRS"] == "/usr/share"
        assert "GDK_BACKEND" not in env
        assert not any(k.endswith("_VSCODE_SNAP_ORIG") for k in env)


class TestDisplayFlags:
    """Chrome forcé en X11 quand XWayland est là (crash « Fatal Wayland communication error »)."""

    def test_x11_quand_display(self):
        from scrapers.browser import display_flags
        assert display_flags({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}) == ["--ozone-platform=x11"]

    def test_rien_sans_display(self):
        from scrapers.browser import display_flags
        assert display_flags({"WAYLAND_DISPLAY": "wayland-0"}) == []
