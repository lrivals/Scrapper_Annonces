# tests/test_cards.py
# =========================
# Affichage des cartes d'annonces (ui/cards.py)
# =========================

from ui.cards import card_view

FULL = {
    "price": 605, "surface_m2": 42.0, "nb_rooms": 2, "nb_bedrooms": 1, "floor": 2,
    "charges_included": 1, "charges": 40, "deposit": 605, "dpe_rating": "B", "ges_rating": "c",
    "furnished": 0, "elevator": 1, "publisher_type": "individual", "published_at": "2026-11-12",
    "created_at": "2026-11-13T16:49:04", "distance_km": 4.53, "geo_precision": "exact",
    "photos": '["a.jpg", "b.jpg", "c.jpg"]', "enrichment_status": "done",
    "available_from": "2026-12-01", "apl_ok": 1, "visale_ok": 0,
}


def test_full_detail():
    v = card_view(FULL)
    assert v["key_facts"] == ["T2", "42 m²", "2ᵉ ét."]          # 1 ch. d'un T2 : implicite
    assert (v["price_note"], v["price_per_m2"]) == ("CC", 14)
    assert v["distance_label"] == "4,5 km"
    assert (v["publisher_label"], v["date_label"]) == ("Particulier", "publiée le 12/11")
    assert v["photo_count"] == 3
    assert v["energy"] == [("DPE", "B"), ("GES", "C")]
    housing, conditions = v["chip_groups"]
    assert [c[0] for c in housing] == ["Vide", "Ascenseur", "Dépôt 605 €"]
    assert [c[0] for c in conditions] == ["Dispo 01/12", "APL ✓", "Visale ✗"]
    assert v["partial"] is False


def test_pending_card_is_partial_and_ignores_default_furnished():
    v = card_view({"price": 500, "furnished": 0, "enrichment_status": "pending",
                   "created_at": "2026-11-13T10:00:00", "distance_km": 3.0, "geo_precision": "approx"})
    assert v["partial"] is True
    assert v["chip_groups"] == []                               # « Vide » non fiable avant la fiche
    assert v["distance_label"] == "≈ 3,0 km"
    assert v["date_label"] == "vue le 13/11"
    assert v["price_per_m2"] is None and v["key_facts"] == []


def test_charges_on_top_and_odd_bedrooms():
    v = card_view({"price": 700, "charges": 50, "surface_m2": 60, "nb_rooms": 3, "nb_bedrooms": 1, "floor": 0})
    assert v["price_note"] == "+50 € ch."
    assert v["key_facts"] == ["T3", "60 m²", "1 ch.", "RDC"]


def test_unknown_values_are_omitted():
    v = card_view({"price": None, "dpe_rating": "NC", "photos": "pas du json", "publisher_type": None})
    assert v["energy"] == [] and v["photo_count"] == 0
    assert v["publisher_label"] is None and v["distance_label"] is None
    assert v["date_label"] == "Récent"


def test_duplicate_never_marked_partial():
    assert card_view({"enrichment_status": "pending", "duplicate_of": 12})["partial"] is False


def test_surface_rounded():
    assert card_view({"surface_m2": 46.73, "nb_rooms": 2})["key_facts"] == ["T2", "47 m²"]
