# scrapers/browser.py
# =========================
# Session Chrome partagée : vrai Chrome (profil persistant) piloté via CDP.
# Utilisé par les scrapers, l'enrichissement et les scripts de debug.
# =========================

import json
import shutil
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from config import (
    BROWSER_PROFILE_DIR,
    CHROME_BINARY,
    CHROME_DEBUG_PORT,
    CHROME_STARTUP_TIMEOUT,
)
from utils.logger import setup_logger

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # Playwright absent (UI, tests) : rien ne lèvera cette exception
    class PlaywrightTimeoutError(Exception):
        pass

logger = setup_logger("browser")

_CHROME_CANDIDATES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]


class BrowserError(RuntimeError):
    """Chrome introuvable, profil verrouillé ou port CDP injoignable."""


def find_chrome_binary(configured: Optional[str] = CHROME_BINARY) -> str:
    if configured:
        path = shutil.which(configured) or (configured if Path(configured).exists() else None)
        if not path:
            raise BrowserError(f"CHROME_BINARY introuvable : {configured}")
        return path
    for name in _CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    raise BrowserError(
        "Chrome/Chromium introuvable dans le PATH "
        f"({', '.join(_CHROME_CANDIDATES)}) — renseigner CHROME_BINARY dans config.py"
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_cdp(port: int, timeout: float = CHROME_STARTUP_TIMEOUT, proc=None) -> dict:
    """Attend que Chrome réponde sur /json/version. Retourne la réponse JSON."""
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise BrowserError(
                f"Chrome s'est arrêté au démarrage (code {proc.returncode}) — "
                "profil déjà utilisé par une autre fenêtre Chrome ?"
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                return json.loads(resp.read().decode())
        except (OSError, ValueError):
            time.sleep(0.25)
    raise BrowserError(f"Port CDP {port} injoignable après {timeout}s")


def _profile_locked(profile_dir: Path) -> bool:
    # Chrome crée un lien SingletonLock tant qu'une instance utilise le profil
    return (profile_dir / "SingletonLock").is_symlink()


@contextmanager
def chrome_session(profile_dir: Path = BROWSER_PROFILE_DIR, port: int = CHROME_DEBUG_PORT):
    """
    Lance Chrome avec le profil persistant puis s'y connecte via CDP.
    Yield (browser, page). Ferme proprement Chrome en sortie, même en cas d'erreur.
    """
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    if _profile_locked(profile_dir):
        raise BrowserError(
            f"Profil Chrome déjà utilisé ({profile_dir}) — fermer l'autre fenêtre Chrome "
            "(scraping ou enrichissement en cours ?)"
        )

    if port == 0:
        port = free_port()
    elif port_in_use(port):
        raise BrowserError(f"Port {port} déjà utilisé — mettre CHROME_DEBUG_PORT = 0 pour un port libre")

    cmd = [
        find_chrome_binary(),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1920,1080",
    ]
    from playwright.sync_api import sync_playwright  # import paresseux, après les vérifications

    logger.info(f"Lancement de Chrome (port CDP {port})...")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_cdp(port, proc=proc)
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            try:
                yield browser, page
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
