# scrapers/browser.py
# =========================
# Session Chrome partagée : vrai Chrome (profil persistant) piloté via CDP.
# Utilisé par les scrapers, l'enrichissement et les scripts de debug.
# =========================

import json
import os
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
    LOG_DIR,
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


CHROME_STDERR_LOG = LOG_DIR / "chrome_stderr.log"


def _log_tail(path: Path, lines: int = 8) -> str:
    try:
        content = path.read_text(errors="replace").splitlines()
    except OSError:
        return "(illisible)"
    # Les lignes crashpad n'aident pas au diagnostic
    useful = [l for l in content if "crashpad" not in l]
    return "\n".join(useful[-lines:]) or "(vide)"


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


# Variables injectées par les applis snap (ex. VS Code en snap) : elles font
# charger à Chrome les schémas GSettings/GTK du snap -> crash GLib (SIGTRAP).
_SNAP_LEAKED_VARS = (
    "GSETTINGS_SCHEMA_DIR", "GTK_PATH", "GTK_EXE_PREFIX", "GTK_IM_MODULE_FILE",
    "GDK_PIXBUF_MODULE_FILE", "GDK_PIXBUF_MODULEDIR", "GIO_MODULE_DIR", "LOCPATH",
)


def _is_snap_path(value: str) -> bool:
    return "/snap/" in value


def chrome_env(base: Optional[dict] = None) -> dict:
    """
    Environnement pour Chrome, débarrassé des chemins injectés par un snap.
    Ne dépend pas de $SNAP : un terminal ouvert depuis VS Code (snap) peut
    hériter de GSETTINGS_SCHEMA_DIR & co sans avoir $SNAP.
    """
    env = dict(os.environ if base is None else base)
    for var in _SNAP_LEAKED_VARS:
        if _is_snap_path(env.get(var, "")):
            env.pop(var)
    for key in list(env):
        if key.endswith("_VSCODE_SNAP_ORIG"):
            orig = env.pop(key)
            target = key[: -len("_VSCODE_SNAP_ORIG")]
            if orig:
                env[target] = orig
            else:
                env.pop(target, None)
    # Sans valeur d'origine à restaurer : retirer les entrées snap des listes de chemins
    for var in ("XDG_DATA_DIRS", "XDG_CONFIG_DIRS"):
        if var in env:
            parts = [d for d in env[var].split(":") if d and not _is_snap_path(d)]
            if parts:
                env[var] = ":".join(parts)
            else:
                env.pop(var)
    return env


def _profile_locked(profile_dir: Path) -> bool:
    """
    Chrome crée un lien SingletonLock -> "<hostname>-<pid>" tant qu'une instance
    utilise le profil. Un verrou laissé par un Chrome mort (crash, kill) est
    supprimé ici pour ne pas bloquer les runs suivants.
    """
    lock = profile_dir / "SingletonLock"
    if not lock.is_symlink():
        return False
    host, _, pid = os.readlink(lock).rpartition("-")
    if host == socket.gethostname() and pid.isdigit() and not _pid_alive(int(pid)):
        logger.warning(f"Verrou Chrome orphelin (PID {pid} mort) supprimé")
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                (profile_dir / name).unlink()
            except FileNotFoundError:
                pass
        return False
    return True


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    CHROME_STDERR_LOG.parent.mkdir(parents=True, exist_ok=True)
    stderr_file = open(CHROME_STDERR_LOG, "wb")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=stderr_file, env=chrome_env()
    )
    try:
        try:
            wait_for_cdp(port, proc=proc)
        except BrowserError as e:
            stderr_file.flush()
            tail = _log_tail(CHROME_STDERR_LOG)
            raise BrowserError(f"{e}\nSortie de Chrome ({CHROME_STDERR_LOG}) :\n{tail}") from None
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
        stderr_file.close()
