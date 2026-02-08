# tests/test_filters.py
# =========================
# Tests unitaires pour les filtres
# =========================

import pytest
from filters.price_and_distance import parse_price


class TestPriceParser:
    """Tests pour le parseur de prix."""
    
    def test_parse_standard_price(self):
        """Test parsing de prix standards."""
        assert parse_price("450€") == 450
        assert parse_price("450 €") == 450
        assert parse_price("420€") == 420
    
    def test_parse_price_with_cc(self):
        """Test parsing de prix avec mentions CC (charges comprises)."""
        assert parse_price("450€ CC") == 450
        assert parse_price("450€ charges comprises") == 450
    
    def test_parse_price_with_non_breaking_space(self):
        """Test parsing avec espace insécable (\\u202f)."""
        assert parse_price("450\u202f€") == 450
        assert parse_price("420\u202f€\u202fCC") == 420
    
    def test_parse_price_invalid(self):
        """Test parsing de prix invalides."""
        assert parse_price(None) is None
        assert parse_price("") is None
        assert parse_price("abc") is None
        assert parse_price("pas de prix") is None
    
    def test_parse_price_edge_cases(self):
        """Test cas limites."""
        assert parse_price("99€") == 99  # Très bas
        assert parse_price("9999€") == 9999  # Très haut
        assert parse_price("1€") is None  # Trop bas (regex demande 2-4 chiffres)
    
    def test_parse_price_with_text(self):
        """Test extraction de prix noyé dans du texte."""
        assert parse_price("Loyer : 420 euros par mois") == 420
        assert parse_price("Prix 450 €/mois") == 450


class TestDistanceFilter:
    """Tests pour le filtre de distance (nécessite mock du géocodage)."""
    
    @pytest.mark.skip(reason="Nécessite mock de geopy pour éviter appels API réels")
    def test_distance_calculation(self):
        """Test calcul de distance (à implémenter avec mock)."""
        pass
