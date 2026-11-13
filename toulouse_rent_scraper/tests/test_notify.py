# tests/test_notify.py
# =========================
# Notifications (Sprint 13.1) — aucun appel réseau réel
# =========================

from unittest.mock import MagicMock, patch

import pytest

import config
import notify
from notify.messages import build_messages
from storage.sqlite import init_db, insert_annonce, upsert_annonce_profile


@pytest.fixture
def ntfy(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_BACKEND", "ntfy")
    monkeypatch.setattr(config, "NTFY_TOPIC", "topic-secret-123")
    monkeypatch.setattr(config, "NTFY_SERVER", "https://ntfy.example")
    monkeypatch.setattr(config, "NTFY_TOKEN", None)
    with patch("notify.ntfy.requests.post") as post:
        post.return_value = MagicMock(status_code=200)
        yield post


class TestBackends:
    def test_disabled_is_noop(self):
        with patch("notify.ntfy.requests.post") as post:
            assert notify.send("t", "b") is False
        post.assert_not_called()

    def test_ntfy_uses_json_with_unicode(self, ntfy):
        assert notify.send("Nouvelle annonce — Blagnac", "T2 700 €", url="https://lbc.fr/1", priority="high")
        payload = ntfy.call_args.kwargs["json"]
        assert payload["topic"] == "topic-secret-123"
        assert payload["title"] == "Nouvelle annonce — Blagnac"
        assert payload["click"] == "https://lbc.fr/1"
        assert payload["priority"] == 4
        assert ntfy.call_args.args[0] == "https://ntfy.example"

    def test_ntfy_token_header(self, ntfy, monkeypatch):
        monkeypatch.setattr(config, "NTFY_TOKEN", "tk")
        notify.send("t", "b")
        assert ntfy.call_args.kwargs["headers"] == {"Authorization": "Bearer tk"}

    def test_send_failure_is_swallowed(self, ntfy):
        ntfy.side_effect = ConnectionError("réseau coupé")
        assert notify.send("t", "b") is False

    def test_missing_topic(self, ntfy, monkeypatch):
        monkeypatch.setattr(config, "NTFY_TOPIC", None)
        assert notify.send("t", "b") is False
        ntfy.assert_not_called()

    def test_telegram(self, monkeypatch):
        monkeypatch.setattr(config, "NOTIFY_BACKEND", "telegram")
        monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
        with patch("notify.telegram.requests.post") as post:
            assert notify.send("Titre", "Corps", url="https://x", priority="high")
        assert post.call_args.args[0] == "https://api.telegram.org/bot123:abc/sendMessage"
        text = post.call_args.kwargs["json"]["text"]
        assert text.startswith("🚨 Titre") and text.endswith("https://x")

    def test_unknown_backend(self, monkeypatch):
        monkeypatch.setattr(config, "NOTIFY_BACKEND", "pigeon")
        assert notify.send("t", "b") is False


def _add(url, profile, price, distance, score):
    import sqlite3
    insert_annonce({"site": "LeBonCoin", "title": f"Annonce {price}", "price": price,
                    "location_raw": "Blagnac", "url": url})
    upsert_annonce_profile(url, profile, distance)
    from storage.sqlite import DB_PATH
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "UPDATE annonce_profiles SET score = ? WHERE profile = ? AND annonce_id = "
            "(SELECT id FROM annonces WHERE url = ?)", (score, profile, url))


class TestMessages:
    def test_threshold_and_individual_messages(self, temp_db, monkeypatch):
        init_db()
        monkeypatch.setattr(config, "NOTIFY_MIN_SCORE", 55)
        _add("https://a/good", "blagnac", 650, 2.0, 80)
        _add("https://a/meh", "blagnac", 740, 7.0, 30)
        msgs = build_messages([
            {"kind": "new", "profile": "blagnac", "url": "https://a/good"},
            {"kind": "new", "profile": "blagnac", "url": "https://a/meh"},
        ])
        assert len(msgs) == 1
        assert msgs[0]["title"] == "Nouvelle annonce — Blagnac — Pl. Marcel Dassault"
        assert "650 €" in msgs[0]["body"] and "★ 80" in msgs[0]["body"]
        assert msgs[0]["url"] == "https://a/good"
        assert msgs[0]["priority"] == "high"   # score ≥ 75

    def test_grouped_when_many(self, temp_db, monkeypatch):
        init_db()
        monkeypatch.setattr(config, "NOTIFY_GROUP_THRESHOLD", 3)
        monkeypatch.setattr(config, "NOTIFY_GROUP_MAX_ITEMS", 2)
        events = []
        for i, score in enumerate([60, 90, 70, 80]):
            _add(f"https://a/{i}", "enac", 400 + i, 1.0, score)
            events.append({"kind": "new", "profile": "enac", "url": f"https://a/{i}"})
        msgs = build_messages(events)
        assert len(msgs) == 1
        assert msgs[0]["title"] == "4 annonces intéressantes — ENAC"
        assert msgs[0]["url"] == "https://a/1"            # meilleur score en premier
        assert "… et 2 autre(s)" in msgs[0]["body"]

    def test_price_drop_message(self, temp_db):
        init_db()
        _add("https://a/1", "enac", 420, 1.0, 70)
        msgs = build_messages([{"kind": "price_drop", "profile": "enac", "url": "https://a/1", "old_price": 470}])
        assert msgs[0]["title"] == "Baisse de 50 € — ENAC"
        assert "avant : 470 €" in msgs[0]["body"]

    def test_hidden_annonce_not_notified(self, temp_db):
        from storage.sqlite import set_annonce_status
        init_db()
        _add("https://a/1", "enac", 420, 1.0, 90)
        set_annonce_status(1, "hidden")
        assert build_messages([{"kind": "new", "profile": "enac", "url": "https://a/1"}]) == []

    def test_notify_events_sends_each_message(self, temp_db, ntfy):
        init_db()
        _add("https://a/1", "enac", 420, 1.0, 90)
        assert notify.notify_events([{"kind": "new", "profile": "enac", "url": "https://a/1"}]) == 1
        assert ntfy.call_count == 1


def test_notify_captcha(ntfy):
    assert notify.notify_captcha("LeBonCoin", 600)
    payload = ntfy.call_args.kwargs["json"]
    assert payload["title"] == "Captcha à résoudre — LeBonCoin"
    assert payload["priority"] == 4 and "10 min" in payload["message"]


def test_cli_notify_test(ntfy):
    import main
    with pytest.raises(SystemExit) as exit_info:
        main.main(["notify-test"])
    assert exit_info.value.code == 0
    assert ntfy.call_count == 1


def test_cli_notify_test_disabled():
    import main
    with pytest.raises(SystemExit) as exit_info:
        main.main(["notify-test"])
    assert exit_info.value.code == 1


def test_env_file_loader(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# commentaire\nNTFY_TOPIC_TEST="abc"\nAUTRE=1\nNTFY_DEJA=nouveau\n', encoding="utf-8")
    monkeypatch.delenv("NTFY_TOPIC_TEST", raising=False)
    monkeypatch.setenv("NTFY_DEJA", "existant")
    config._load_env_file(env)
    import os
    assert os.environ["NTFY_TOPIC_TEST"] == "abc"
    assert os.environ["NTFY_DEJA"] == "existant"   # l'environnement réel prime
    monkeypatch.delenv("NTFY_TOPIC_TEST")
    monkeypatch.delenv("AUTRE", raising=False)


class TestLine:
    """Sprint 16.4 — ligne de notification avec la fiche complète."""

    def test_full_detail(self):
        from notify.messages import _line
        line = _line({"title": "T2 Blagnac", "price": 690, "nb_rooms": 2, "surface_m2": 38.0, "charges": 40,
                      "dpe_rating": "C", "distance_km": 5.23, "geo_precision": "exact", "score": 81.6})
        assert line == "T2 Blagnac — T2 · 38 m² · 690 € (+40 € ch.) · DPE C · 5,2 km · ★ 82"

    def test_missing_fields_omitted_and_approx_distance(self):
        from notify.messages import _line
        line = _line({"title": "Studio", "price": 450, "distance_km": 3.0, "geo_precision": "approx"})
        assert line == "Studio — 450 € · ≈ 3,0 km"

    def test_charges_included(self):
        from notify.messages import _line
        assert _line({"title": "X", "price": 700, "charges": 50, "charges_included": 1}) == "X — 700 € CC"

    def test_query_returns_detail_columns(self, temp_db):
        from storage.sqlite import annonces_for_notification
        init_db()
        _add("https://a/1", "enac", 420, 1.0, 90)
        row = annonces_for_notification("enac", ["https://a/1"])["https://a/1"]
        assert {"charges", "charges_included", "geo_precision", "surface_m2", "dpe_rating"} <= set(row)
