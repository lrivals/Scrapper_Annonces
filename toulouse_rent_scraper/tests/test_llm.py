# tests/test_llm.py
# =========================
# Sprint 15.4 — analyse des descriptions par LLM (client Anthropic simulé : aucun appel réel)
# =========================

import json
import sqlite3
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2 as httpx   # client HTTP du SDK anthropic ≥ 1.0
import pytest

from analysis import llm

TODAY = date(2026, 11, 13)

ANNONCE = {
    "id": 1, "url": "https://lbc/1", "site": "LeBonCoin", "title": "T2 Saint-Agne", "price": 450,
    "surface_m2": 38.0, "location_raw": "Toulouse 31400", "publisher_type": "individual",
    "description": "T2 lumineux proche métro. Libre au 1er décembre. APL acceptées, garant Visale ok. "
                   "Charges 40 €, dépôt 450 €.",
}

GOOD = {
    "summary": "T2 lumineux près du métro Saint-Agne.",
    "available_from": "2026-12-01", "lease_type": "classique", "colocation": False,
    "apl_ok": True, "visale_ok": True, "guarantor_required": None, "agency_fees_eur": None,
    "charges_eur": 40, "deposit_eur": 450, "parking": None, "outdoor": [], "heating": None,
    "scam_flags": [], "scam_risk": "faible",
}


def _response(data=None, stop_reason="end_turn", text=None, model="claude-opus-5-5"):
    blocks = [SimpleNamespace(type="thinking", thinking="")]
    if data is not None or text is not None:
        blocks.append(SimpleNamespace(type="text", text=text if text is not None else json.dumps(data)))
    return SimpleNamespace(
        stop_reason=stop_reason, content=blocks, model=model,
        stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
        usage=SimpleNamespace(input_tokens=900, output_tokens=150),
    )


def _client(*responses):
    client = MagicMock()
    client.beta.messages.create.side_effect = list(responses)
    return client


def _api_error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("erreur", response=httpx.Response(status, request=request), body=None)


# ---------------------------------------------------------------------------
# Requête
# ---------------------------------------------------------------------------

class TestRequest:

    def test_structured_output_and_effort(self):
        req = llm.build_request(ANNONCE, TODAY)
        assert req["model"] == "claude-opus-5-5"
        fmt = req["output_config"]["format"]
        assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
        assert set(fmt["schema"]["required"]) == set(fmt["schema"]["properties"])
        assert req["output_config"]["effort"] == "low"
        assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
        assert req["cache_control"] == {"type": "ephemeral"}
        assert "thinking" not in req and "temperature" not in req

    def test_model_without_server_fallback(self):
        req = llm.build_request(ANNONCE, TODAY, model="claude-haiku-5-5")
        assert "fallbacks" not in req and "betas" not in req

    def test_user_message_wraps_untrusted_text(self):
        msg = llm.build_request(ANNONCE, TODAY)["messages"][0]["content"]
        assert msg.startswith("Date du jour : 2026-11-13")
        assert "<annonce>" in msg and ANNONCE["description"] in msg and "particulier" in msg

    def test_system_prompt_is_stable(self):
        """Le prompt système ne dépend pas de l'annonce ni de la date (cache)."""
        other = {**ANNONCE, "description": "autre texte assez long pour être analysé"}
        assert llm.build_request(ANNONCE, TODAY)["system"] == llm.build_request(other, date(2027, 1, 1))["system"]

    def test_long_description_truncated(self):
        long = {**ANNONCE, "description": "x" * 10_000}
        assert len(llm._description(long)) < 6_100

    def test_hash_changes_with_text_not_date(self):
        h = llm.input_hash(ANNONCE)
        assert h == llm.input_hash(dict(ANNONCE))
        assert h != llm.input_hash({**ANNONCE, "description": ANNONCE["description"] + " Parking."})
        assert h != llm.input_hash({**ANNONCE, "price": 430})


# ---------------------------------------------------------------------------
# Réponse
# ---------------------------------------------------------------------------

class TestResponse:

    def test_normalize(self):
        f = llm.normalize({**GOOD, "agency_fees_eur": 380, "scam_flags": [" paiement avant visite ", 3]})
        assert (f["available_from"], f["apl_ok"], f["visale_ok"], f["agency_fees"]) == ("2026-12-01", True, True, 380)
        assert (f["charges"], f["deposit"], f["scam_flags"]) == (40, 450, ["paiement avant visite"])

    @pytest.mark.parametrize("value,expected", [
        ("immediate", "immediate"), ("2026-12-01", "2026-12-01"), ("2026-02-30", None),
        ("1er décembre", None), (None, None),
    ])
    def test_available_from(self, value, expected):
        assert llm.normalize({**GOOD, "available_from": value})["available_from"] == expected

    def test_out_of_range_values_dropped(self):
        f = llm.normalize({**GOOD, "lease_type": "autre", "scam_risk": "énorme", "charges_eur": -5,
                           "deposit_eur": True, "apl_ok": "oui"})
        assert (f["lease_type"], f["scam_risk"], f["charges"], f["deposit"], f["apl_ok"]) == (None,) * 5

    def test_refusal_and_truncation(self):
        with pytest.raises(ValueError, match="refus"):
            llm.response_json(_response(stop_reason="refusal"))
        with pytest.raises(ValueError, match="tronquée"):
            llm.response_json(_response(GOOD, stop_reason="max_tokens"))
        with pytest.raises(ValueError):
            llm.response_json(_response(text="pas du json"))


class TestLowPrice:

    def test_flag_added(self):
        cheap = {**ANNONCE, "price": 150}      # 3,9 €/m² vs médiane 12
        f = llm.apply_low_price_signal(llm.normalize(GOOD), cheap, 12.0)
        assert f["scam_risk"] == "moyen" and "prix très bas" in f["scam_flags"][0]

    def test_high_risk_kept(self):
        f = llm.apply_low_price_signal({**llm.normalize(GOOD), "scam_risk": "eleve"}, {**ANNONCE, "price": 100}, 12.0)
        assert f["scam_risk"] == "eleve"

    def test_normal_price_or_unknown_median(self):
        base = llm.normalize(GOOD)
        assert llm.apply_low_price_signal(base, ANNONCE, 12.0) == base
        assert llm.apply_low_price_signal(base, {**ANNONCE, "price": 50}, None) == base

    def test_median_needs_enough_values(self):
        assert llm.median_price_per_m2([ANNONCE] * 4) is None
        assert llm.median_price_per_m2([ANNONCE] * 5) == pytest.approx(450 / 38)


# ---------------------------------------------------------------------------
# Run complet sur une base temporaire
# ---------------------------------------------------------------------------

@pytest.fixture
def db(temp_db):
    from storage.sqlite import init_db, insert_annonce, update_annonce_enrichment, upsert_annonce_profile
    init_db()
    for i, desc in enumerate([ANNONCE["description"], "Deuxième annonce avec une description suffisante.",
                              None], start=1):
        url = f"https://lbc/{i}"
        insert_annonce({"site": "LeBonCoin", "title": f"T2 n°{i}", "price": 450, "location_raw": "Toulouse",
                        "distance_enac_km": 2.0, "url": url})
        upsert_annonce_profile(url, "enac", 2.0)
        if desc:
            update_annonce_enrichment(url, {"description": desc, "surface_m2": 38})
    return temp_db


def _rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = {r["url"]: dict(r) for r in conn.execute("SELECT * FROM annonces")}
    conn.close()
    return rows


def test_analyze_pending_stores_results(db):
    risky = {**GOOD, "scam_flags": ["propriétaire à l'étranger"], "scam_risk": "eleve", "charges_eur": 60}
    client = _client(_response(GOOD), _response(risky))
    summary = llm.analyze_pending(client=client, today=TODAY)
    assert summary == {"candidates": 2, "done": 2, "errors": 0, "refused": 0, "risky": 1}

    rows = _rows(db)
    first = rows["https://lbc/1"] if rows["https://lbc/1"]["scam_risk"] == "faible" else rows["https://lbc/2"]
    assert (first["llm_status"], first["available_from"], first["apl_ok"], first["charges"]) == ("done", "2026-12-01", 1, 40)
    assert json.loads(first["llm_data"])["summary"] == GOOD["summary"]
    assert rows["https://lbc/3"]["llm_status"] is None          # pas de description : ignorée

    # Deuxième run : rien à refaire
    client2 = _client()
    assert llm.analyze_pending(client=client2, today=TODAY)["candidates"] == 0
    client2.beta.messages.create.assert_not_called()


def test_existing_charges_not_overwritten(db):
    from storage.sqlite import update_annonce_enrichment
    update_annonce_enrichment("https://lbc/1", {"charges": 25})
    llm.analyze_pending(client=_client(_response(GOOD), _response(GOOD)), today=TODAY)
    assert _rows(db)["https://lbc/1"]["charges"] == 25


def test_changed_description_reanalyzed(db):
    from storage.sqlite import update_annonce_enrichment
    llm.analyze_pending(client=_client(_response(GOOD), _response(GOOD)), today=TODAY)
    update_annonce_enrichment("https://lbc/2", {"description": "Description modifiée par l'annonceur, plus longue."})
    client = _client(_response(GOOD))
    assert llm.analyze_pending(client=client, today=TODAY)["done"] == 1


def test_refusal_and_error_statuses(db):
    client = _client(_response(stop_reason="refusal"), _response(text="{tronqué"))
    summary = llm.analyze_pending(client=client, today=TODAY)
    assert (summary["refused"], summary["errors"]) == (1, 1)
    statuses = sorted(r["llm_status"] or "" for r in _rows(db).values())
    assert statuses == ["", "error", "refused"]
    # L'erreur est retentée, le refus non
    assert llm.analyze_pending(client=_client(_response(GOOD)), today=TODAY)["candidates"] == 1


def test_service_unavailable_stops_run(db):
    import anthropic
    client = _client(_api_error(anthropic.AuthenticationError, 401))
    summary = llm.analyze_pending(client=client, today=TODAY)
    assert summary["done"] == 0 and client.beta.messages.create.call_count == 1
    assert all(r["llm_status"] is None for r in _rows(db).values())    # rien marqué : retenté plus tard


def test_bad_request_marks_annonce(db):
    import anthropic
    client = _client(_api_error(anthropic.BadRequestError, 400), _response(GOOD))
    summary = llm.analyze_pending(client=client, today=TODAY)
    assert (summary["errors"], summary["done"]) == (1, 1)


def test_limit_and_force(db):
    assert llm.analyze_pending(limit=1, client=_client(_response(GOOD)), today=TODAY)["candidates"] == 1
    llm.analyze_pending(client=_client(_response(GOOD)), today=TODAY)
    assert llm.analyze_pending(force=True, client=_client(_response(GOOD), _response(GOOD)),
                               today=TODAY)["done"] == 2


def test_maybe_analyze_respects_setting(db, monkeypatch):
    import config
    monkeypatch.setattr(config, "LLM_ANALYSIS_ENABLED", False)
    with patch("analysis.llm.analyze_pending") as run:
        assert llm.maybe_analyze("test") is None
    run.assert_not_called()
    monkeypatch.setattr(config, "LLM_ANALYSIS_ENABLED", True)
    with patch("analysis.llm.analyze_pending", side_effect=RuntimeError("boom")):
        assert llm.maybe_analyze("test") is None          # jamais bloquant


# ---------------------------------------------------------------------------
# Score, notification, UI, CLI
# ---------------------------------------------------------------------------

def test_scam_risk_penalizes_score():
    from config import SEARCH_PROFILES
    from scoring import compute_score
    base = {"price": 400, "surface_m2": 30, "furnished": True, "dpe_rating": "C"}
    clean, _ = compute_score(base, 2.0, SEARCH_PROFILES["enac"], 13.0)
    risky, detail = compute_score({**base, "scam_risk": "eleve"}, 2.0, SEARCH_PROFILES["enac"], 13.0)
    assert risky == pytest.approx(clean * 0.5, abs=0.1) and detail["risque"] == 0.5
    low, detail_low = compute_score({**base, "scam_risk": "faible"}, 2.0, SEARCH_PROFILES["enac"], 13.0)
    assert low == clean and "risque" not in detail_low


def test_notification_line():
    from notify.messages import _line
    line = _line({"title": "T2", "price": 450, "available_from": "2026-12-01", "scam_risk": "eleve"})
    assert line.startswith("⚠️ T2") and "dispo 01/12" in line


def test_ui_shows_analysis(db):
    from ui import app
    llm.analyze_pending(client=_client(
        _response({**GOOD, "agency_fees_eur": 380}),
        _response({**GOOD, "scam_flags": ["paiement avant visite"], "scam_risk": "eleve"}),
    ), today=TODAY)
    app.config["TESTING"] = True
    html = app.test_client().get("/?profile=enac").get_data(as_text=True)
    for text in ("T2 lumineux près du métro", "Dispo 01/12", "APL ✓", "Visale ✓", "Frais 380 €",
                 "⚠️ Arnaque ?", "paiement avant visite"):
        assert text in html


def test_cli_analyze(db):
    from main import main
    with patch("analysis.llm.make_client", return_value=_client(_response(GOOD), _response(GOOD))), \
         patch("scoring.rescore") as rescore:
        main(["analyze", "--limit", "5"])
    rescore.assert_called_once()
    assert sum(r["llm_status"] == "done" for r in _rows(db).values()) == 2
