# tests/test_validation.py
# =========================
# Tests unitaires pour la validation
# =========================

import pytest
from utils.validation import validate_annonce


class TestAnnonceValidation:
    """Tests pour la validation des annonces."""
    
    def test_valid_annonce(self, sample_annonce):
        """Test validation d'une annonce complète et valide."""
        error = validate_annonce(sample_annonce)
        assert error is None, "Une annonce valide ne devrait pas retourner d'erreur"
    
    def test_missing_field(self, sample_annonce):
        """Test validation avec champ manquant."""
        annonce = sample_annonce.copy()
        del annonce["price"]
        
        error = validate_annonce(annonce)
        assert error is not None
        assert "price" in error.lower()
    
    def test_empty_field(self, sample_annonce):
        """Test validation avec champ vide."""
        annonce = sample_annonce.copy()
        annonce["title"] = ""
        
        error = validate_annonce(annonce)
        assert error is not None
        assert "title" in error.lower()
    
    def test_none_field(self, sample_annonce):
        """Test validation avec champ None."""
        annonce = sample_annonce.copy()
        annonce["location_raw"] = None
        
        error = validate_annonce(annonce)
        assert error is not None
        assert "location_raw" in error.lower()
    
    def test_invalid_url(self, sample_annonce):
        """Test validation avec URL invalide."""
        annonce = sample_annonce.copy()
        annonce["url"] = "not-a-valid-url"
        
        error = validate_annonce(annonce)
        assert error is not None
        assert "url" in error.lower()
    
    def test_empty_url(self, sample_annonce):
        """Test validation avec URL vide."""
        annonce = sample_annonce.copy()
        annonce["url"] = ""
        
        error = validate_annonce(annonce)
        assert error is not None
