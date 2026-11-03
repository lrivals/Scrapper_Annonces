# utils/lock.py
# =========================
# Verrou inter-processus (fcntl) : empêche deux scrapings simultanés
# (timer systemd + bouton de l'UI) qui se disputeraient le profil Chrome.
# =========================

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from config import SCRAPE_LOCK_FILE


class AlreadyRunning(RuntimeError):
    """Un autre scraping / enrichissement tient déjà le verrou."""


@contextmanager
def run_lock(path: Optional[Path] = None):
    path = Path(path or SCRAPE_LOCK_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            holder = handle.read().strip() or "?"
            raise AlreadyRunning(f"Un autre run est en cours (pid {holder})")
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def is_locked(path: Optional[Path] = None) -> bool:
    """True si un autre processus tient le verrou (le verrou est relâché aussitôt)."""
    try:
        with run_lock(path):
            return False
    except AlreadyRunning:
        return True
