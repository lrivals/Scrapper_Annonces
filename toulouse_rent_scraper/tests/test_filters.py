# tests/test_filters.py
# =========================
# Tests unitaires pour les filtres
# =========================

import pytest
from unittest.mock import patch
from filters.price_and_distance import parse_price, apply_price_and_distance_filter


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
        assert parse_price("99€") == 99
        assert parse_price("9999€") == 9999
        assert parse_price("1€") is None  # 1 seul chiffre, regex demande 2+
    
    def test_parse_price_with_text(self):
        """Test extraction de prix noyé dans du texte."""
        assert parse_price("Loyer : 420 euros par mois") == 420
        assert parse_price("Prix 450 €/mois") == 450


class TestMinPriceFilter:
    """Tests pour le filtre de prix minimum (annonces aberrantes)."""

    def _make_annonce(self, price_str, location="Toulouse 31000"):
        return {
            "site": "SeLoger",
            "title": "Studio",
            "price": price_str,
            "location_raw": location,
            "url": "https://example.com/annonce",
        }

    @patch("filters.price_and_distance.distance_from_enac_km", return_value=2.0)
    def test_reject_price_below_50(self, mock_dist):
        """Les annonces < 50€ (garages, erreurs) sont rejetées."""
        assert apply_price_and_distance_filter(self._make_annonce("11")) is None
        assert apply_price_and_distance_filter(self._make_annonce("12")) is None
        assert apply_price_and_distance_filter(self._make_annonce("49")) is None

    @patch("filters.price_and_distance.distance_from_enac_km", return_value=2.0)
    def test_accept_price_at_50(self, mock_dist):
        """Le seuil 50€ est accepté."""
        result = apply_price_and_distance_filter(self._make_annonce("50"))
        assert result is not None
        assert result["price"] == 50

    @patch("filters.price_and_distance.distance_from_enac_km", return_value=2.0)
    def test_accept_normal_price(self, mock_dist):
        """Un prix normal passe le filtre."""
        result = apply_price_and_distance_filter(self._make_annonce("430"))
        assert result is not None
        assert result["price"] == 430

    @patch("filters.price_and_distance.distance_from_enac_km", return_value=2.0)
    def test_reject_price_above_max(self, mock_dist):
        """Un prix au-dessus du max est rejeté."""
        assert apply_price_and_distance_filter(self._make_annonce("600")) is None


class TestDistanceFilter:
    """Tests pour le filtre de distance (nécessite mock du géocodage)."""

    @pytest.mark.skip(reason="Nécessite mock de geopy pour éviter appels API réels")
    def test_distance_calculation(self):
        """Test calcul de distance (à implémenter avec mock)."""
        pass
