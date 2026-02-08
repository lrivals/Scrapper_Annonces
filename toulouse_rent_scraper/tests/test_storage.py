# tests/test_storage.py
# =========================
# Tests unitaires pour le stockage SQLite
# =========================

import pytest
from storage.sqlite import init_db, insert_annonce, annonce_exists


class TestSQLiteStorage:
    """Tests pour le stockage SQLite."""
    
    def test_init_db(self, temp_db):
        """Test initialisation de la base de données."""
        init_db()
        assert temp_db.exists(), "La base de données devrait être créée"
    
    def test_insert_new_annonce(self, temp_db, sample_annonce_filtered):
        """Test insertion d'une nouvelle annonce."""
        init_db()
        
        result = insert_annonce(sample_annonce_filtered)
        assert result is True, "L'insertion devrait réussir pour une nouvelle annonce"
        
        # Vérifier que l'annonce existe
        assert annonce_exists(sample_annonce_filtered["url"])
    
    def test_insert_duplicate_annonce(self, temp_db, sample_annonce_filtered):
        """Test insertion d'une annonce déjà existante (déduplication)."""
        init_db()
        
        # Première insertion
        insert_annonce(sample_annonce_filtered)
        
        # Tentative de ré-insertion
        result = insert_annonce(sample_annonce_filtered)
        assert result is False, "La ré-insertion d'une annonce existante devrait échouer"
    
    def test_annonce_exists_false(self, temp_db):
        """Test vérification d'existence pour une annonce inexistante."""
        init_db()
        
        result = annonce_exists("https://example.com/fake/12345")
        assert result is False
    
    def test_annonce_exists_true(self, temp_db, sample_annonce_filtered):
        """Test vérification d'existence pour une annonce existante."""
        init_db()
        insert_annonce(sample_annonce_filtered)
        
        result = annonce_exists(sample_annonce_filtered["url"])
        assert result is True


class TestDatabaseIntegrity:
    """Tests d'intégrité de la base de données."""
    
    def test_unique_url_constraint(self, temp_db, sample_annonce_filtered):
        """Test que la contrainte UNIQUE sur l'URL fonctionne."""
        init_db()
        
        # Première insertion
        result1 = insert_annonce(sample_annonce_filtered)
        assert result1 is True
        
        # Modifier légèrement l'annonce mais garder la même URL
        annonce_modified = sample_annonce_filtered.copy()
        annonce_modified["price"] = 999
        annonce_modified["title"] = "Titre différent"
        
        # Tentative d'insertion avec même URL
        result2 = insert_annonce(annonce_modified)
        assert result2 is False, "Deux annonces avec la même URL ne devraient pas être insérées"
