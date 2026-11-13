# tests/test_llm.py
# =========================
# Sprint 15.4 / 15.4-bis — analyse LLM : une seule lecture par texte, fournisseur au choix
# (aucun appel réel : backends simulés)
# =========================

import json
import os
import sqlite3
import stat
import threading
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2 as httpx   # client HTTP du SDK anthropic ≥ 1.0
import pytest

from analysis import llm
from analysis.providers import (
    AnthropicBackend, LlmCallError, LlmRefused, LlmResult, LlmSettings, LlmUnavailable,
    OpenAICompatibleBackend, load_settings, make_backend, save_settings,
)

TODAY = date(2026, 11, 13)

GOOD = {
    "summary": "T2 lumineux près du métro Saint-Agne.",
    "available_from": "2026-12-01", "lease_type": "classique", "colocation": False,
    "apl_ok": True, "visale_ok": True, "guarantor_required": None, "agency_fees_eur": None,
    "charges_eur": 40, "deposit_eur": 450, "parking": None, "outdoor": [], "heating": None,
    "scam_flags": [], "scam_risk": "faible",
}

DESC_1 = "T2 lumineux proche métro. Libre au 1er décembre. APL acceptées, garant Visale ok. Charges 40 €."
DESC_2 = "Deuxième annonce avec une description suffisante pour l'analyse."


class FakeBackend:
    """Backend simulé : renvoie les réponses données dans l'ordre et compte les appels."""

    def __init__(self, *outcomes, model="fake-model"):
        self.outcomes = list(outcomes)
        self.calls = []
        self.model = model
        self.settings = LlmSettings(provider="ollama", model=model)

    def complete(self, system, user, schema):
        self.calls.append(user)
        outcome = self.outcomes.pop(0) if self.outcomes else GOOD
        if isinstance(outcome, Exception):
            raise outcome
        return LlmResult(outcome, self.model, 900, 150)


# ---------------------------------------------------------------------------
# Base temporaire
# ---------------------------------------------------------------------------

@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    import analysis.providers as providers
    path = tmp_path / "llm_settings.json"
    monkeypatch.setattr(providers, "SETTINGS_FILE", path)
    monkeypatch.setattr(providers.load_settings, "__defaults__", (path,))
    monkeypatch.setattr(providers.save_settings, "__defaults__", (path,))
    monkeypatch.setattr(providers.delete_settings, "__defaults__", (path,))
    for var in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_ANALYSIS"):
        monkeypatch.delenv(var, raising=False)
    return path


@pytest.fixture
def db(temp_db, settings_file):
    from storage.sqlite import init_db
    init_db()
    _add(1, DESC_1)
    _add(2, DESC_2)
    _add(3, None)
    return temp_db


def _add(n, description, price=450, site="LeBonCoin"):
    from storage.sqlite import insert_annonce, update_annonce_enrichment, upsert_annonce_profile
    url = f"https://{site.lower()}/{n}"
    insert_annonce({"site": site, "title": f"T2 n°{n}", "price": price, "location_raw": "Toulouse 31400",
                    "distance_enac_km": 2.0, "url": url})
    upsert_annonce_profile(url, "enac", 2.0)
    if description:
        update_annonce_enrichment(url, {"description": description, "surface_m2": 38})
    return url


def _rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = {r["url"]: dict(r) for r in conn.execute("SELECT * FROM annonces")}
    conn.close()
    return rows


def _registry(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM llm_analyses")]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Une seule lecture par texte
# ---------------------------------------------------------------------------

class TestReadOnce:

    def test_first_run_reads_each_text_once(self, db):
        backend = FakeBackend()
        s = llm.analyze_pending(backend=backend, today=TODAY)
        assert (s["calls"], s["done"], len(backend.calls)) == (2, 2, 2)
        assert _rows(db)["https://leboncoin/3"]["llm_status"] is None    # pas de description
        assert {r["calls"] for r in _registry(db)} == {1}

    def test_second_run_makes_no_call(self, db):
        llm.analyze_pending(backend=FakeBackend(), today=TODAY)
        backend = FakeBackend()
        s = llm.analyze_pending(backend=backend, today=TODAY)
        assert backend.calls == [] and s["candidates"] == 0

    def test_price_change_does_not_trigger_reread(self, db):
        from storage.sqlite import insert_annonce
        llm.analyze_pending(backend=FakeBackend(), today=TODAY)
        insert_annonce({"site": "LeBonCoin", "title": "T2 n°1", "price": 420, "location_raw": "Toulouse 31400",
                        "url": "https://leboncoin/1"})
        backend = FakeBackend()
        llm.analyze_pending(backend=backend, today=TODAY)
        assert backend.calls == []

    def test_description_change_does_not_trigger_reread(self, db):
        from storage.sqlite import update_annonce_enrichment
        llm.analyze_pending(backend=FakeBackend(), today=TODAY)
        update_annonce_enrichment("https://leboncoin/2", {"description": DESC_2 + " Parking en sus."})
        backend = FakeBackend()
        llm.analyze_pending(backend=backend, today=TODAY)
        assert backend.calls == []

    def test_republished_text_reused_without_call(self, db):
        """Même texte sur une nouvelle URL (republication, autre site) : résultat réutilisé."""
        llm.analyze_pending(backend=FakeBackend(), today=TODAY)
        _add(4, "  t2 LUMINEUX proche métro.\nLibre au 1er décembre. APL acceptées, garant Visale ok. Charges 40 €. ")
        backend = FakeBackend()
        s = llm.analyze_pending(backend=backend, today=TODAY)
        assert backend.calls == [] and s["reused"] == 1
        row = _rows(db)["https://leboncoin/4"]
        assert (row["llm_status"], row["summary"]) == ("done", GOOD["summary"])

    def test_cross_site_duplicate_reuses_original(self, db):
        from storage.sqlite import set_duplicate_of
        llm.analyze_pending(backend=FakeBackend(), today=TODAY)
        dup = _add(5, "Texte différent rédigé par l'agence sur Bien'ici pour le même bien.", site="BienIci")
        original_id = _rows(db)["https://leboncoin/1"]["id"]
        set_duplicate_of(dup, original_id)
        backend = FakeBackend()
        s = llm.analyze_pending(backend=backend, today=TODAY)
        assert backend.calls == [] and s["reused"] == 1
        assert _rows(db)[dup]["llm_input_hash"] == _rows(db)["https://leboncoin/1"]["llm_input_hash"]

    def test_duplicate_waits_for_active_original(self, db):
        from storage.sqlite import set_duplicate_of
        dup = _add(6, "Texte du doublon, l'original n'est pas encore analysé.", site="BienIci")
        set_duplicate_of(dup, _rows(db)["https://leboncoin/1"]["id"])
        backend = FakeBackend()
        s = llm.analyze_pending(backend=backend, today=TODAY)
        # Doublons traités après les originaux : 2 appels seulement, le doublon réutilise
        assert len(backend.calls) == 2 and s["reused"] == 1
        assert _rows(db)[dup]["llm_status"] == "done"

    def test_duplicate_not_read_while_original_pending(self, db):
        """Plafond atteint avant l'original : le doublon attend au lieu d'être lu à sa place."""
        from storage.sqlite import set_duplicate_of
        dup = _add(7, "Texte du doublon, l'original n'est pas encore analysé.", site="BienIci")
        set_duplicate_of(dup, _rows(db)["https://leboncoin/1"]["id"])
        backend = FakeBackend()
        llm.analyze_pending(limit=0, backend=backend, today=TODAY)
        assert backend.calls == [] and _rows(db)[dup]["llm_status"] is None

    def test_error_not_retried_automatically(self, db):
        backend = FakeBackend(LlmCallError("JSON illisible", (900, 20)), GOOD)
        s = llm.analyze_pending(backend=backend, today=TODAY)
        assert (s["errors"], s["done"]) == (1, 1)
        backend2 = FakeBackend()
        llm.analyze_pending(backend=backend2, today=TODAY)
        assert backend2.calls == []
        assert sum(r["input_tokens"] for r in _registry(db)) == 1800    # jetons de l'erreur comptés

    def test_retry_errors_once_then_never(self, db):
        llm.analyze_pending(backend=FakeBackend(LlmCallError("tronquée"), GOOD), today=TODAY)
        b2 = FakeBackend(LlmCallError("encore"))
        assert llm.analyze_pending(retry_errors=True, backend=b2, today=TODAY)["calls"] == 1
        b3 = FakeBackend()
        assert llm.analyze_pending(retry_errors=True, backend=b3, today=TODAY)["calls"] == 0
        assert max(r["calls"] for r in _registry(db)) == 2                 # plafond par texte

    def test_refusal_never_retried(self, db):
        llm.analyze_pending(backend=FakeBackend(LlmRefused("refus du modèle"), GOOD), today=TODAY)
        b = FakeBackend()
        llm.analyze_pending(retry_errors=True, backend=b, today=TODAY)
        assert b.calls == []

    def test_unavailable_releases_claim_without_marking(self, db):
        backend = FakeBackend(LlmUnavailable("service injoignable"))
        s = llm.analyze_pending(backend=backend, today=TODAY)
        assert s["calls"] == 0 and "injoignable" in s["stopped"]
        assert _registry(db) == []                                          # rien de facturé, rien de réservé
        assert all(r["llm_status"] is None for r in _rows(db).values())
        assert llm.analyze_pending(backend=FakeBackend(), today=TODAY)["calls"] == 2

    def test_concurrent_claim_only_one_wins(self, db):
        from storage.sqlite import claim_llm_entry
        h = llm.content_hash(DESC_1)
        results = []
        threads = [threading.Thread(target=lambda: results.append(claim_llm_entry(h, "m", 2))) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results.count(True) == 1

    def test_text_in_progress_elsewhere_is_skipped(self, db):
        from storage.sqlite import claim_llm_entry
        claim_llm_entry(llm.content_hash(DESC_1), "m", 2)       # autre run en cours sur ce texte
        backend = FakeBackend()
        s = llm.analyze_pending(backend=backend, today=TODAY)
        assert (len(backend.calls), s["waiting"]) == (1, 1)

    def test_run_limit(self, db):
        backend = FakeBackend()
        s = llm.analyze_pending(limit=1, backend=backend, today=TODAY)
        assert len(backend.calls) == 1 and "plafond du run" in s["stopped"]

    def test_daily_cap(self, db, monkeypatch):
        monkeypatch.setattr(llm, "LLM_MAX_CALLS_PER_DAY", 1)
        llm.analyze_pending(backend=FakeBackend(), today=TODAY)
        backend = FakeBackend()
        s = llm.analyze_pending(backend=backend, today=TODAY)
        assert backend.calls == [] and "quotidien" in s["stopped"]

    def test_no_provider_no_call(self, db):
        s = llm.analyze_pending(today=TODAY)          # aucun réglage : make_backend refuse
        assert s["calls"] == 0 and "aucun fournisseur" in s["stopped"]


# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------

def test_results_stored(db):
    risky = {**GOOD, "scam_flags": ["propriétaire à l'étranger"], "scam_risk": "eleve", "charges_eur": 60}
    s = llm.analyze_pending(backend=FakeBackend(GOOD, risky), today=TODAY)
    assert s["risky"] == 1
    rows = _rows(db)
    first = rows["https://leboncoin/2"] if rows["https://leboncoin/2"]["scam_risk"] == "faible" else rows["https://leboncoin/1"]
    assert (first["available_from"], first["apl_ok"], first["charges"]) == ("2026-12-01", 1, 40)
    assert json.loads(first["llm_data"])["summary"] == GOOD["summary"]


def test_existing_charges_not_overwritten(db):
    from storage.sqlite import update_annonce_enrichment
    update_annonce_enrichment("https://leboncoin/1", {"charges": 25})
    llm.analyze_pending(backend=FakeBackend(), today=TODAY)
    assert _rows(db)["https://leboncoin/1"]["charges"] == 25


def test_user_message_and_hash():
    a = {"title": "T2", "price": 450, "description": DESC_1, "publisher_type": "individual"}
    msg = llm.user_message(a, TODAY)
    assert msg.startswith("Date du jour : 2026-11-13") and "<annonce>" in msg and "particulier" in msg
    assert llm.content_hash(DESC_1) == llm.content_hash("  " + DESC_1.upper().replace(" ", "\n "))
    assert llm.content_hash(DESC_1) != llm.content_hash(DESC_1 + " Parking.")


class TestNormalize:

    def test_values(self):
        f = llm.normalize({**GOOD, "agency_fees_eur": 380, "scam_flags": [" paiement avant visite ", 3]})
        assert (f["available_from"], f["apl_ok"], f["agency_fees"], f["scam_flags"]) == \
            ("2026-12-01", True, 380, ["paiement avant visite"])

    @pytest.mark.parametrize("value,expected", [
        ("immediate", "immediate"), ("2026-12-01", "2026-12-01"), ("2026-02-30", None), ("1er décembre", None),
    ])
    def test_available_from(self, value, expected):
        assert llm.normalize({**GOOD, "available_from": value})["available_from"] == expected

    def test_out_of_range(self):
        f = llm.normalize({**GOOD, "lease_type": "autre", "scam_risk": "énorme", "charges_eur": -5, "apl_ok": "oui"})
        assert (f["lease_type"], f["scam_risk"], f["charges"], f["apl_ok"]) == (None,) * 4

    def test_low_price_signal(self):
        f = llm.apply_low_price_signal(llm.normalize(GOOD), {"price": 150, "surface_m2": 38}, 12.0)
        assert f["scam_risk"] == "moyen" and "prix très bas" in f["scam_flags"][0]
        assert llm.median_price_per_m2([{"price": 450, "surface_m2": 38}] * 4) is None


# ---------------------------------------------------------------------------
# Fournisseurs
# ---------------------------------------------------------------------------

class TestSettings:

    def test_nothing_configured(self, settings_file):
        s = load_settings()
        assert not s.ready and s.problems() == ["aucun fournisseur de LLM configuré"]
        with pytest.raises(LlmUnavailable):
            make_backend(s)

    def test_machine_anthropic_key_never_used(self, settings_file, monkeypatch):
        """Une clé ANTHROPIC_API_KEY de la machine ne doit jamais être utilisée implicitement."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-proprietaire")
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        s = load_settings()
        assert s.api_key == "" and "clé d'API à renseigner" in s.problems()

    def test_env_settings(self, settings_file, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "mistral")
        monkeypatch.setenv("LLM_MODEL", "mon-modele")
        monkeypatch.setenv("LLM_API_KEY", "cle-123456789")
        monkeypatch.setenv("LLM_ANALYSIS", "1")
        s = load_settings()
        assert (s.ready, s.auto, s.source, s.effective_base_url) == (True, True, ".env", "https://api.mistral.ai/v1")
        assert isinstance(make_backend(s), OpenAICompatibleBackend)

    def test_ui_file_wins_and_is_private(self, settings_file, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "mistral")
        save_settings(LlmSettings(provider="ollama", model="llama-local"))
        s = load_settings()
        assert (s.provider, s.source, s.ready) == ("ollama", "interface", True)   # pas de clé pour Ollama
        assert stat.S_IMODE(os.stat(settings_file).st_mode) == 0o600

    def test_anthropic_default_model_and_explicit_key(self, settings_file):
        s = LlmSettings(provider="anthropic", api_key="sk-ant-utilisateur-xyz")
        backend = make_backend(s)
        assert isinstance(backend, AnthropicBackend) and backend.model == "claude-opus-5-5"
        assert backend.client.api_key == "sk-ant-utilisateur-xyz"
        assert s.masked_key() == "••••-xyz"

    def test_openai_compatible_needs_model(self, settings_file):
        assert "modèle à renseigner" in LlmSettings(provider="openai", api_key="k" * 20).problems()
        assert "URL de l'API à renseigner" in LlmSettings(provider="openai_compatible", model="m").problems()


def _anthropic_response(data=None, stop_reason="end_turn"):
    blocks = [SimpleNamespace(type="thinking", thinking="")]
    if data is not None:
        blocks.append(SimpleNamespace(type="text", text=json.dumps(data)))
    return SimpleNamespace(stop_reason=stop_reason, content=blocks, model="claude-opus-5-5",
                           stop_details=SimpleNamespace(category="cyber"),
                           usage=SimpleNamespace(input_tokens=900, output_tokens=150))


class TestAnthropicBackend:

    def _backend(self, *responses, model=""):
        client = MagicMock()
        client.beta.messages.create.side_effect = list(responses)
        return AnthropicBackend(LlmSettings(provider="anthropic", model=model, api_key="sk-x"), client=client), client

    def test_request(self):
        b, _ = self._backend()
        req = b.build_request("sys", "user", llm.SCHEMA)
        assert req["output_config"]["format"]["schema"] is llm.SCHEMA and req["output_config"]["effort"] == "low"
        assert req["fallbacks"] == "default" and req["cache_control"] == {"type": "ephemeral"}
        assert "thinking" not in req and "temperature" not in req
        b2, _ = self._backend(model="claude-haiku-5-5")
        assert "fallbacks" not in b2.build_request("s", "u", {})

    def test_complete(self):
        b, _ = self._backend(_anthropic_response(GOOD))
        r = b.complete("s", "u", llm.SCHEMA)
        assert (r.data, r.input_tokens) == (GOOD, 900)

    def test_refusal_and_truncation(self):
        b, _ = self._backend(_anthropic_response(stop_reason="refusal"), _anthropic_response(GOOD, "max_tokens"))
        with pytest.raises(LlmRefused):
            b.complete("s", "u", {})
        with pytest.raises(LlmCallError, match="tronquée") as e:
            b.complete("s", "u", {})
        assert e.value.tokens == (900, 150)

    @pytest.mark.parametrize("cls,status,expected", [
        ("AuthenticationError", 401, LlmUnavailable), ("RateLimitError", 429, LlmUnavailable),
        ("InternalServerError", 500, LlmUnavailable), ("BadRequestError", 400, LlmCallError),
    ])
    def test_errors(self, cls, status, expected):
        import anthropic
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        err = getattr(anthropic, cls)("erreur", response=httpx.Response(status, request=request), body=None)
        b, _ = self._backend(err)
        with pytest.raises(expected):
            b.complete("s", "u", {})


def _http(status, body=None, text=""):
    resp = MagicMock(status_code=status, text=text or json.dumps(body or {}))
    resp.json.return_value = body
    return resp


def _chat(content, finish="stop", refusal=None):
    return {"model": "mon-modele", "usage": {"prompt_tokens": 800, "completion_tokens": 120},
            "choices": [{"finish_reason": finish, "message": {"content": content, "refusal": refusal}}]}


class TestOpenAICompatibleBackend:

    def _backend(self, *responses, provider="mistral", key="cle-utilisateur"):
        session = MagicMock()
        session.post.side_effect = list(responses)
        settings = LlmSettings(provider=provider, model="mon-modele", api_key=key)
        return OpenAICompatibleBackend(settings, session=session), session

    def test_request_and_parse(self):
        b, session = self._backend(_http(200, _chat(json.dumps(GOOD))))
        r = b.complete("sys", "user", llm.SCHEMA)
        assert (r.data, r.input_tokens, r.output_tokens) == (GOOD, 800, 120)
        args, kwargs = session.post.call_args
        assert args[0] == "https://api.mistral.ai/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer cle-utilisateur"
        rf = kwargs["json"]["response_format"]
        assert rf["type"] == "json_schema" and rf["json_schema"]["schema"] is llm.SCHEMA

    def test_local_without_key(self):
        b, session = self._backend(_http(200, _chat("```json\n" + json.dumps(GOOD) + "\n```")), provider="ollama", key="")
        assert b.complete("s", "u", {}).data == GOOD
        assert "Authorization" not in session.post.call_args.kwargs["headers"]
        assert session.post.call_args.args[0] == "http://localhost:11434/v1/chat/completions"

    def test_json_schema_unsupported_falls_back(self):
        b, session = self._backend(_http(400, text="unsupported response_format json_schema"),
                                   _http(200, _chat(json.dumps(GOOD))))
        assert b.complete("s", "u", llm.SCHEMA).data == GOOD
        second = session.post.call_args.kwargs["json"]
        assert second["response_format"] == {"type": "json_object"} and "schéma" in second["messages"][0]["content"]

    @pytest.mark.parametrize("status,expected", [(401, LlmUnavailable), (404, LlmUnavailable),
                                                 (429, LlmUnavailable), (503, LlmUnavailable), (422, LlmCallError)])
    def test_http_errors(self, status, expected):
        b, _ = self._backend(_http(status, {}))
        with pytest.raises(expected):
            b.complete("s", "u", {})

    def test_network_error(self):
        import requests
        b, _ = self._backend(requests.ConnectionError("refusé"))
        with pytest.raises(LlmUnavailable):
            b.complete("s", "u", {})

    def test_refusal_truncation_bad_json(self):
        b, _ = self._backend(_http(200, _chat(None, refusal="non")), _http(200, _chat("{", finish="length")),
                             _http(200, _chat("pas du json")))
        with pytest.raises(LlmRefused):
            b.complete("s", "u", {})
        with pytest.raises(LlmCallError, match="tronquée"):
            b.complete("s", "u", {})
        with pytest.raises(LlmCallError, match="JSON"):
            b.complete("s", "u", {})


# ---------------------------------------------------------------------------
# Automatique, score, notification, UI, CLI
# ---------------------------------------------------------------------------

def test_maybe_analyze_requires_user_opt_in(db):
    with patch("analysis.llm.analyze_pending") as run:
        assert llm.maybe_analyze("test") is None                 # rien de configuré
        save_settings(LlmSettings(provider="ollama", model="m", auto=False))
        assert llm.maybe_analyze("test") is None                 # configuré mais pas automatique
        save_settings(LlmSettings(provider="openai", model="m", auto=True))
        assert llm.maybe_analyze("test") is None                 # automatique mais sans clé
        run.assert_not_called()
        save_settings(LlmSettings(provider="ollama", model="m", auto=True))
        llm.maybe_analyze("test")
        run.assert_called_once()


def test_scam_risk_penalizes_score():
    from config import SEARCH_PROFILES
    from scoring import compute_score
    base = {"price": 400, "surface_m2": 30, "furnished": True, "dpe_rating": "C"}
    clean, _ = compute_score(base, 2.0, SEARCH_PROFILES["enac"], 13.0)
    risky, detail = compute_score({**base, "scam_risk": "eleve"}, 2.0, SEARCH_PROFILES["enac"], 13.0)
    assert risky == pytest.approx(clean * 0.5, abs=0.1) and detail["risque"] == 0.5


def test_notification_line():
    from notify.messages import _line
    line = _line({"title": "T2", "price": 450, "available_from": "2026-12-01", "scam_risk": "eleve"})
    assert line.startswith("⚠️ T2") and "dispo 01/12" in line


def test_ui_shows_analysis(db):
    from ui import app
    llm.analyze_pending(backend=FakeBackend({**GOOD, "agency_fees_eur": 380},
                                            {**GOOD, "scam_flags": ["paiement avant visite"], "scam_risk": "eleve"}),
                        today=TODAY)
    app.config["TESTING"] = True
    html = app.test_client().get("/?profile=enac").get_data(as_text=True)
    for text in ("T2 lumineux près du métro", "Dispo 01/12", "APL ✓", "Frais 380 €", "⚠️ Arnaque ?",
                 "paiement avant visite", "Connexion LLM"):
        assert text in html


class TestSettingsPage:

    @pytest.fixture
    def client(self, db):
        from tests.test_ui import CsrfClient
        from ui import app
        app.config["TESTING"] = True
        return CsrfClient(app.test_client())

    def test_page_and_save_never_shows_key(self, client, settings_file):
        r = client.post("/settings/llm", data={"provider": "anthropic", "model": "", "api_key": "sk-ant-secret-9876",
                                               "auto": "on"})
        assert r.status_code == 302
        s = load_settings()
        assert (s.provider, s.api_key, s.auto) == ("anthropic", "sk-ant-secret-9876", True)
        html = client.get("/settings/llm").get_data(as_text=True)
        assert "sk-ant-secret-9876" not in html and "••••9876" in html

    def test_blank_key_kept_for_same_provider_only(self, client, settings_file):
        client.post("/settings/llm", data={"provider": "anthropic", "api_key": "sk-ant-secret-9876"})
        client.post("/settings/llm", data={"provider": "anthropic", "model": "claude-haiku-5-5", "api_key": ""})
        assert load_settings().api_key == "sk-ant-secret-9876"
        # Changement de fournisseur : la clé Anthropic n'est jamais envoyée ailleurs
        client.post("/settings/llm", data={"provider": "openai_compatible", "model": "m",
                                           "base_url": "https://autre.example/v1", "api_key": ""})
        assert load_settings().api_key == ""

    def test_csrf_required(self, db):
        from ui import app
        app.config["TESTING"] = True
        assert app.test_client().post("/settings/llm", data={"provider": "ollama"}).status_code == 403

    def test_test_button_and_delete(self, client, settings_file):
        client.post("/settings/llm", data={"provider": "ollama", "model": "llama"})
        with patch("analysis.llm.test_connection", return_value={"ok": True, "message": "OK (llama)"}):
            r = client.post("/settings/llm/test")
        assert "OK" in r.headers["Location"]
        client.post("/settings/llm/delete")
        assert not settings_file.exists() and load_settings().provider == ""

    def test_invalid_url_rejected(self, client, settings_file):
        client.post("/settings/llm", data={"provider": "openai_compatible", "model": "m", "base_url": "file:///etc"})
        assert load_settings().provider == ""


def test_cli_analyze_and_stats(db, capsys):
    from main import main
    with patch("analysis.llm.make_backend", return_value=FakeBackend()), patch("scoring.rescore") as rescore:
        main(["analyze", "--limit", "5"])
    rescore.assert_called_once()
    main(["analyze", "--stats"])
    out = capsys.readouterr().out
    assert "Textes lus : 2" in out and "Appels facturables : 2" in out


def test_migration_imports_previous_analyses(db):
    """Analyses faites avant le registre (15.4) : reprises, donc jamais relues."""
    from storage.sqlite import init_db
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE llm_analyses")
    conn.execute("UPDATE annonces SET llm_status = 'done', llm_model = 'claude-opus-5-5', llm_data = ? "
                 "WHERE url = 'https://leboncoin/1'", (json.dumps(GOOD),))
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()
    init_db()
    registry = _registry(db)
    assert len(registry) == 1 and registry[0]["content_hash"] == llm.content_hash(DESC_1)
    backend = FakeBackend()
    llm.analyze_pending(backend=backend, today=TODAY)
    assert len(backend.calls) == 1 and DESC_2 in backend.calls[0]     # seule l'annonce jamais lue
