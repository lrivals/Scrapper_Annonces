# tests/conftest.py
# =========================
# Configuration pytest et fixtures
# =========================

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_db(monkeypatch):
    """
    Fixture qui crée une base de données SQLite temporaire pour les tests.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        # Monkey patch le chemin de la DB pour les tests
        import storage.sqlite
        monkeypatch.setattr(storage.sqlite, 'DB_PATH', db_path)
        
        yield db_path


@pytest.fixture
def sample_annonce():
    """Fixture fournissant une annonce exemple pour les tests."""
    return {
        "site": "SeLoger",
        "title": "Studio meublé proche ENAC",
        "price": "420€",
        "location_raw": "Rangueil, Toulouse",
        "url": "https://www.seloger.com/annonces/achat/maison/test/123456.htm"
    }


@pytest.fixture
def sample_annonce_filtered():
    """Fixture fournissant une annonce déjà filtrée."""
    return {
        "site": "SeLoger",
        "title": "Studio meublé proche ENAC",
        "price": 420,
        "location_raw": "Rangueil, Toulouse",
        "distance_enac_km": 1.5,
        "url": "https://www.seloger.com/annonces/achat/maison/test/123456.htm"
    }
