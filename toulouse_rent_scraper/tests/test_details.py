# tests/test_details.py
# =========================
# Panneau « Détails » d'une carte dépliée (ui/details.py)
# =========================

import json

from ui.details import detail_view

LBC_EXTRA = {
    "district_id": "300241", "external_ad_id": "ubiflow_X", "store_logo": "https://img/x.png",
    "is_import": "true", "square": "42 m²", "furnished": "Non meublé", "energy_rate": "Vierge",
    "specificities": "Cuisine équipée, Climatisation", "heating_mode": "Électrique",
    "outside_access": "Balcon", "nb_parkings": "1", "elevator": "Non",
    "annual_energy_budget_min": "920 €", "annual_energy_budget_max": "990 €",
    "rent_excluding_charges": "560", "inventory_fees": "99 €", "is_public_rent_control": "Oui",
    "store_name": "Ticket Immobilier", "custom_ref": "X7K5", "rental_fees": "983",
}


def _rows(view, group):
    return dict(view["groups"]).get(group, [])


def test_lbc_keeps_useful_keys_only():
    v = detail_view({"site": "LeBonCoin", "extra_attributes": json.dumps(LBC_EXTRA), "charges": 45,
                     "description": "Bel appartement\n\nProche tram", "enrichment_status": "done",
                     "enriched_at": "2026-11-13T16:49:04"}, [])
    flat = repr(v["groups"])
    for hidden in ("300241", "ubiflow", "img/x.png", "true", "42 m²", "Non meublé", "Vierge"):
        assert hidden not in flat                                   # technique ou déjà sur la carte
    assert ("Particularités", "Cuisine équipée, Climatisation") in _rows(v, "Logement")
    assert ("Places de parking", "1") in _rows(v, "Extérieurs & stationnement")
    assert ("Budget énergie", "920 – 990 € / an") in _rows(v, "Chauffage & énergie")
    frais = _rows(v, "Frais & conditions")
    assert frais[:2] == [("Charges", "45 € / mois"), ("Honoraires", "983 €")]
    assert ("Loyer hors charges", "560 €") in frais and (None, "Loyer encadré") in frais
    assert ("Annonceur", "Ticket Immobilier") in v["meta"] and ("Fiche lue le", "13/11/2026") in v["meta"]
    assert v["description"] == "Bel appartement\n\nProche tram"


def test_seloger_negative_values_dropped():
    extra = {"cellar": "Pas de cave", "balcony": "Balcon (Total 6,2 m²)", "elevator": "Pas d'ascenseur",
             "barrier-free": "Non accessible, Non accessible aux personnes à mobilité réduite",
             "with-view": "Belle vue, Sans vis-à-vis", "Type de chauffage": "Radiateur"}
    v = detail_view({"site": "SeLoger", "extra_attributes": json.dumps(extra)}, [])
    flat = repr(v["groups"])
    assert "cave" not in flat.lower() and "Non accessible" not in flat
    assert (None, "Balcon (Total 6,2 m²)") in _rows(v, "Extérieurs & stationnement")
    assert (None, "Belle vue, Sans vis-à-vis") in _rows(v, "Extérieurs & stationnement")
    assert ("Chauffage", "Radiateur") in _rows(v, "Chauffage & énergie")


def test_bienici_booleans_and_quantities():
    extra = {"hasTerrace": True, "terracesQuantity": 2, "hasBalcony": False, "hasCellar": True,
             "isDisabledPeopleFriendly": False, "parkingPlacesQuantity": 1, "heating": "électrique individuel",
             "agencyRentalFee": 525.12, "reference": "357324", "newProperty": False}
    v = detail_view({"site": "Bien'ici", "extra_attributes": json.dumps(extra)}, [])
    assert _rows(v, "Extérieurs & stationnement") == [(None, "2 terrasses"), (None, "Cave"), ("Places de parking", "1")]
    assert ("Honoraires", "525 €") in _rows(v, "Frais & conditions")
    assert ("Référence", "357324") in v["meta"]


def test_score_history_and_pending():
    v = detail_view({"site": "LeBonCoin", "enrichment_status": "pending",
                     "score_detail": json.dumps({"loyer": 0.97, "distance": 0.5})},
                    [{"price": 650, "seen_at": "2026-11-01T10:00:00"}])
    assert v["score_bars"] == [("Loyer CC", 10), ("Distance", 5)]
    assert v["price_history"] == []                                 # un seul relevé : rien à montrer
    assert v["pending"] and v["groups"] == [] and v["photos"] == []
    two = detail_view({}, [{"price": 650, "seen_at": "2026-11-01"}, {"price": 620, "seen_at": "2026-11-08"}])
    assert len(two["price_history"]) == 2
