# tests/conftest.py
# =========================
# Configuration pytest et fixtures
# =========================

import pytest
import tempfile
from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Verrou, mémoire des blocages et notifications : jamais les vrais fichiers / services."""
    import scrapers.antibot
    import utils.lock
    import config
    monkeypatch.setattr(utils.lock, "SCRAPE_LOCK_FILE", tmp_path / ".scrape.lock")
    monkeypatch.setattr(scrapers.antibot, "BLOCK_STATE_FILE", tmp_path / ".last_block.json")
    monkeypatch.setattr(config, "NOTIFY_BACKEND", None)
    # Poids appris (15.6) : jamais le vrai fichier
    monkeypatch.setattr(config, "SCORE_WEIGHTS_FILE", tmp_path / "score_weights.json")
    # Critères saisis dans l'interface (15.5) : jamais le vrai fichier
    monkeypatch.setattr(config, "REQUIREMENTS_FILE", tmp_path / "profile_requirements.json")
    # Doublons par photo (15.8) : aucun téléchargement pendant les tests (activé au cas par cas)
    monkeypatch.setattr(config, "PHOTO_DEDUP_ENABLED", False)


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
