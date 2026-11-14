# tests/test_quartier_parser.py
# =========================
# Sprint 5.4 — commune / code postal / quartier depuis location_raw (formats réels des sites)
# =========================

import pytest

from geo.quartier_parser import Location, parse_location, quartier_key


@pytest.mark.parametrize("raw,expected", [
    # SeLoger
    ("Croix-daurade, Toulouse (31200)", Location("Toulouse", "31200", "Croix-Daurade")),
    ("Patte d'Oie, Toulouse (31300)", Location("Toulouse", "31300", "Patte d'Oie")),
    ("Saint-Aubin - Dupuy, Toulouse (31000)", Location("Toulouse", "31000", "Saint-Aubin - Dupuy")),
    ("Toulouse (31000)", Location("Toulouse", "31000", None)),
    # PAP
    ("Blagnac (31700)", Location("Blagnac", "31700", None)),
    # Bien'ici
    ("Toulouse 31200 (Toulouse - Croix Bénite)", Location("Toulouse", "31200", "Croix Bénite")),
    ("Blagnac 31700 (Blagnac - Grand-Noble - Pinot - Brassens)",
     Location("Blagnac", "31700", "Grand-Noble - Pinot - Brassens")),
    # LeBonCoin
    ("Toulouse 31200 Croix Bénite", Location("Toulouse", "31200", "Croix Bénite")),
    ("Toulouse 31400", Location("Toulouse", "31400", None)),
    ("Toulouse 31200 3 Cocus-Borderouge-Cx Daurade-Pale.",
     Location("Toulouse", "31200", "Trois Cocus-Borderouge-Croix Daurade-Palé")),
    # Sans code postal
    ("Colomiers", Location("Colomiers", None, None)),
])
def test_parse_real_formats(raw, expected):
    assert parse_location(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_empty(raw):
    assert parse_location(raw) == Location(None, None, None)
    assert parse_location(raw).label == "Inconnu"


def test_quartier_equal_to_commune_is_dropped():
    assert parse_location("Blagnac 31700 (Blagnac)").quartier is None


def test_same_quartier_across_sites_shares_key():
    seloger = parse_location("Croix-daurade, Toulouse (31200)").quartier
    lbc = parse_location("Toulouse 31200 Croix Daurade").quartier
    assert quartier_key(seloger) == quartier_key(lbc) == "croix daurade"
    assert quartier_key("Les Minimes") == quartier_key("Minimes")
    assert quartier_key("St-Cyprien") == quartier_key("Saint Cyprien")


def test_label():
    assert parse_location("Pinot, Blagnac (31700)").label == "Blagnac — Pinot"
    assert parse_location("Toulouse (31000)").label == "Toulouse"
