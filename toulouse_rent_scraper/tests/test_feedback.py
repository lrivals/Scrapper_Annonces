# tests/test_feedback.py
# =========================
# Sprint 15.6 — retours ⭐ / 📞 / 👎 et poids appris
# =========================

import json
import random
import sqlite3

import pytest

import config
from analysis.weights import (
    current_weights, fit_logistic, format_proposal, propose_weights, reset_weights, save_weights,
)
from scoring import compute_score, rescore
from storage.feedback import (
    favorites_by_annonce, feedback_counts, get_feedback, set_feedback, training_rows,
)
from storage.migrations import SCHEMA_VERSION
from storage.sqlite import (
    annonces_for_notification, clear_db, init_db, insert_annonce, update_annonce_enrichment,
    upsert_annonce_profile,
)

KEYS = list(config.SCORE_WEIGHTS)


def _add(url, price=400, distance=2.0, profile="enac", **details):
    insert_annonce({"site": "LeBonCoin", "title": f"Studio {url[-3:]}", "price": price,
                    "location_raw": "Rangueil", "url": url})
    upsert_annonce_profile(url, profile, distance)
    if details:
        update_annonce_enrichment(url, details)
    import storage.sqlite
    with sqlite3.connect(storage.sqlite.DB_PATH) as con:
        return con.execute("SELECT id FROM annonces WHERE url = ?", (url,)).fetchone()[0]


def _synthetic_rows(n=60, seed=1):
    """L'utilisateur ne regarde que la distance : ⭐ si proche, 👎 si loin."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        criteria = {k: rng.random() for k in KEYS}
        rows.append({"label": 1 if criteria["distance"] > 0.5 else 0, "criteria": criteria, "profile": "enac"})
    return rows


# ---------------------------------------------------------------------------
# Stockage
# ---------------------------------------------------------------------------

class TestStorage:
    def test_migration(self, temp_db):
        init_db()
        with sqlite3.connect(temp_db) as con:
            assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            con.execute("SELECT annonce_id, profile, feedback, price, updated_at FROM annonce_feedback")

    def test_set_replace_clear(self, temp_db):
        init_db()
        aid = _add("https://a/001")
        assert set_feedback(aid, "enac", "favorite") == {"title": "Studio 001", "feedback": "favorite"}
        assert get_feedback(aid, "enac") == "favorite"
        assert get_feedback(aid, "blagnac") is None          # par profil
        set_feedback(aid, "enac", "dislike")
        assert get_feedback(aid, "enac") == "dislike"
        set_feedback(aid, "enac", None)
        assert get_feedback(aid, "enac") is None

    def test_unknown_annonce_or_value(self, temp_db):
        init_db()
        assert set_feedback(999, "enac", "favorite") is None
        with pytest.raises(ValueError):
            set_feedback(1, "enac", "love")

    def test_price_is_recorded(self, temp_db):
        init_db()
        aid = _add("https://a/001", price=420)
        set_feedback(aid, "enac", "favorite")
        with sqlite3.connect(temp_db) as con:
            assert con.execute("SELECT price FROM annonce_feedback").fetchone()[0] == 420

    def test_training_rows_and_counts(self, temp_db):
        init_db()
        a, b, c = _add("https://a/001"), _add("https://a/002"), _add("https://a/003")
        rescore(["enac"])
        set_feedback(a, "enac", "favorite")
        set_feedback(b, "enac", "contacted")
        set_feedback(c, "enac", "dislike")
        rows = training_rows()
        assert sorted(r["label"] for r in rows) == [0, 1, 1]
        assert set(rows[0]["criteria"]) >= {"loyer", "distance"}
        assert feedback_counts() == {"favorite": 1, "contacted": 1, "dislike": 1}
        assert favorites_by_annonce([a, b, c]) == {a: ["enac"]}

    def test_clear_db_removes_feedback(self, temp_db):
        init_db()
        set_feedback(_add("https://a/001"), "enac", "favorite")
        clear_db()
        assert feedback_counts()["favorite"] == 0


# ---------------------------------------------------------------------------
# Apprentissage
# ---------------------------------------------------------------------------

class TestLearning:
    def test_fit_finds_the_signal(self):
        rows = _synthetic_rows()
        w, _ = fit_logistic([[r["criteria"][k] for k in KEYS] for r in rows], [r["label"] for r in rows])
        coef = dict(zip(KEYS, w))
        assert coef["distance"] == max(coef.values())
        assert all(abs(coef[k]) < coef["distance"] / 2 for k in KEYS if k != "distance")

    def test_proposal(self):
        p = propose_weights(_synthetic_rows())
        assert p.ready
        assert p.proposed["distance"] == max(p.proposed.values())
        assert sum(p.proposed.values()) == pytest.approx(sum(config.SCORE_WEIGHTS.values()), abs=len(KEYS))
        assert all(v >= 0 for v in p.proposed.values())
        assert p.accuracy > p.baseline
        text = "\n".join(format_proposal(p))
        assert "Distance" in text and "Concordance" in text

    def test_not_enough_feedback(self):
        p = propose_weights(_synthetic_rows(n=config.FEEDBACK_MIN_SAMPLES - 1))
        assert not p.ready and f"sur {config.FEEDBACK_MIN_SAMPLES}" in p.message
        assert format_proposal(p) == [p.message]

    def test_one_sided_feedback(self):
        rows = [{"label": 1, "criteria": {k: 0.5 for k in KEYS}} for _ in range(40)]
        rows += [{"label": 0, "criteria": {k: 0.5 for k in KEYS}} for _ in range(2)]
        p = propose_weights(rows)
        assert not p.ready and "👎" in p.message

    def test_no_explaining_criterion(self):
        """Retours contraires à tous les critères : pas de poids proposés."""
        rng = random.Random(3)
        rows = []
        for _ in range(60):
            v = rng.random()
            rows.append({"label": 1 if v < 0.5 else 0, "criteria": {k: v for k in KEYS}})
        p = propose_weights(rows)
        assert not p.ready and "conservés" in p.message


class TestWeightsFile:
    def test_default_is_config(self):
        assert current_weights() == config.SCORE_WEIGHTS

    def test_save_and_reset(self):
        learned = {k: 10 for k in KEYS} | {"distance": 60}
        save_weights(learned, 42)
        assert current_weights() == {k: float(v) for k, v in learned.items()}
        data = json.loads(config.SCORE_WEIGHTS_FILE.read_text())
        assert data["samples"] == 42
        assert reset_weights() is True
        assert reset_weights() is False
        assert current_weights() == config.SCORE_WEIGHTS

    @pytest.mark.parametrize("content", [
        "pas du json", '{"weights": {"loyer": 50}}', '{"weights": {"loyer": -1, "distance": 1}}', "[]",
    ])
    def test_invalid_file_falls_back(self, content):
        config.SCORE_WEIGHTS_FILE.write_text(content)
        assert current_weights() == config.SCORE_WEIGHTS

    def test_learned_weights_drive_score(self):
        annonce = {"price": 350, "surface_m2": 20, "furnished": True, "dpe_rating": "B"}
        near = compute_score(annonce, 0.5, config.SEARCH_PROFILES["enac"], 20)[0]
        far = compute_score(annonce, 9.5, config.SEARCH_PROFILES["enac"], 20)[0]
        save_weights({k: 0 for k in KEYS} | {"distance": 100}, 30)
        assert compute_score(annonce, 0.5, config.SEARCH_PROFILES["enac"], 20)[0] == pytest.approx(95)
        assert compute_score(annonce, 9.5, config.SEARCH_PROFILES["enac"], 20)[0] == pytest.approx(5)
        assert near - far < 90   # avec les poids par défaut, l'écart était bien moindre


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class TestNotifications:
    def test_dislike_never_notified_favorite_always(self, temp_db, monkeypatch):
        from notify.messages import build_messages
        monkeypatch.setattr(config, "NOTIFY_MIN_SCORE", 99)   # rien ne passe… sauf un favori
        init_db()
        fav, bad = _add("https://a/fav"), _add("https://a/bad")
        rescore(["enac"])
        set_feedback(fav, "enac", "favorite")
        set_feedback(bad, "enac", "dislike")
        assert set(annonces_for_notification("enac", ["https://a/fav", "https://a/bad"])) == {"https://a/fav"}
        messages = build_messages([
            {"kind": "price_drop", "profile": "enac", "url": "https://a/fav", "old_price": 450},
            {"kind": "price_drop", "profile": "enac", "url": "https://a/bad", "old_price": 450},
        ])
        assert len(messages) == 1
        assert messages[0]["title"].startswith("⭐ Baisse de 50 €")
        assert messages[0]["priority"] == "high"

    def test_favorite_survives_requirements(self, temp_db, monkeypatch):
        import dataclasses
        profile = dataclasses.replace(config.SEARCH_PROFILES["enac"],
                                      requirements=config.Requirements(no_ground_floor=True))
        monkeypatch.setitem(config.SEARCH_PROFILES, "enac", profile)
        init_db()
        aid = _add("https://a/rdc", floor=0)
        rescore(["enac"])
        assert annonces_for_notification("enac", ["https://a/rdc"]) == {}
        set_feedback(aid, "enac", "favorite")
        assert set(annonces_for_notification("enac", ["https://a/rdc"])) == {"https://a/rdc"}

    def test_favorite_gone(self, temp_db, monkeypatch):
        import notify
        init_db()
        fav, other = _add("https://a/fav", price=380), _add("https://a/oth")
        set_feedback(fav, "enac", "favorite")
        sent = []
        monkeypatch.setattr(notify, "send", lambda **m: sent.append(m) or True)
        n = notify.notify_favorites_gone([
            {"id": fav, "title": "Studio fav", "price": 380, "url": "https://a/fav"},
            {"id": other, "title": "Autre", "price": 400, "url": "https://a/oth"},
        ])
        assert n == 1
        assert sent[0]["title"] == "⭐ Favori retiré — ENAC"
        assert "380 €" in sent[0]["body"] and sent[0]["url"] == "https://a/fav"

    def test_check_expired_notifies_favorites(self, temp_db, monkeypatch):
        import notify
        import storage.cleaner as cleaner
        init_db()
        fav = _add("https://a/fav")
        set_feedback(fav, "enac", "favorite")
        monkeypatch.setattr(cleaner, "_check_url_alive", lambda url: False)
        monkeypatch.setattr(cleaner, "RATE_LIMIT_DELAY", 0)
        sent = []
        monkeypatch.setattr(notify, "send", lambda **m: sent.append(m) or True)
        assert cleaner.check_expired_annonces()["expired"] == 1
        assert [m["url"] for m in sent] == ["https://a/fav"]


# ---------------------------------------------------------------------------
# Interface et CLI
# ---------------------------------------------------------------------------

@pytest.fixture
def client(temp_db):
    init_db()
    from ui import app
    app.config["TESTING"] = True
    c = app.test_client()
    c.get("/")
    with c.session_transaction() as sess:
        token = sess["csrf_token"]
    return c, token


def _post_fb(client, aid, value, profile="enac"):
    c, token = client
    return c.post("/feedback", data={"id": str(aid), "value": value, "profile": profile, "csrf_token": token},
                  headers={"X-Requested-With": "XMLHttpRequest"})


class TestUi:
    def test_buttons_and_toggle(self, client):
        aid = _add("https://a/001")
        html = client[0].get("/?profile=enac").get_data(as_text=True)
        assert 'data-value="favorite"' in html and 'data-value="dislike"' in html

        res = _post_fb(client, aid, "favorite").get_json()
        assert res == {"ok": True, "feedback": "favorite", "msg": "« Studio 001 » : favori."}
        html = client[0].get("/?profile=enac").get_data(as_text=True)
        assert 'class="btn-fb is-on"' in html

        res = _post_fb(client, aid, "favorite").get_json()   # re-clic : effacé
        assert res["feedback"] is None and get_feedback(aid, "enac") is None

    @pytest.mark.parametrize("aid, value, profile, status", [
        ("x", "favorite", "enac", 400), ("1", "love", "enac", 400), ("1", "favorite", "nope", 400),
        ("999", "favorite", "enac", 404),
    ])
    def test_invalid_requests(self, client, aid, value, profile, status):
        _add("https://a/001")
        assert _post_fb(client, aid, value, profile).status_code == status

    def test_csrf_required(self, client):
        aid = _add("https://a/001")
        resp = client[0].post("/feedback", data={"id": str(aid), "value": "favorite", "profile": "enac"})
        assert resp.status_code in (400, 403)
        assert get_feedback(aid, "enac") is None

    def test_filters(self, client):
        fav, bad, _ = _add("https://a/fav"), _add("https://a/bad"), _add("https://a/neu")
        _post_fb(client, fav, "favorite")
        _post_fb(client, bad, "dislike")
        get = lambda q: client[0].get("/?profile=enac" + q).get_data(as_text=True)  # noqa: E731
        default = get("")
        assert "https://a/fav" in default and "https://a/neu" in default and "https://a/bad" not in default
        only_fav = get("&fb=favorite")
        assert "https://a/fav" in only_fav and "https://a/neu" not in only_fav
        assert "https://a/bad" in get("&fb=dislike") and "https://a/neu" not in get("&fb=dislike")
        assert all(u in get("&fb=any") for u in ("https://a/fav", "https://a/bad", "https://a/neu"))
        # Le retour est propre au profil
        assert "https://a/bad" not in default
        upsert_annonce_profile("https://a/bad", "blagnac", 3.0)
        assert "https://a/bad" in client[0].get("/?profile=blagnac").get_data(as_text=True)

    def test_weights_page_not_ready(self, client):
        html = client[0].get("/settings/weights").get_data(as_text=True)
        assert "Poids du score" in html and "retour(s) sur" in html
        assert 'value="apply"' not in html

    def test_weights_apply_and_reset(self, client, monkeypatch):
        import analysis.weights as w
        rows = _synthetic_rows()
        monkeypatch.setattr(w, "propose_weights", lambda rows_=None: _real_propose(rows))
        c, token = client
        html = c.get("/settings/weights").get_data(as_text=True)
        assert 'value="apply"' in html and "Concordance" in html
        resp = c.post("/settings/weights", data={"action": "apply", "csrf_token": token})
        assert resp.status_code == 302 and "Poids+appliqu" in resp.headers["Location"]
        assert current_weights()["distance"] == max(current_weights().values())
        assert "Revenir aux poids" in c.get("/settings/weights").get_data(as_text=True)
        c.post("/settings/weights", data={"action": "reset", "csrf_token": token})
        assert current_weights() == config.SCORE_WEIGHTS

    def test_weights_apply_refused_when_not_ready(self, client):
        c, token = client
        resp = c.post("/settings/weights", data={"action": "apply", "csrf_token": token})
        assert resp.status_code == 302 and "flash=err" in resp.headers["Location"]
        assert not config.SCORE_WEIGHTS_FILE.exists()


_real_propose = propose_weights


class TestCli:
    def test_weights_command(self, temp_db, monkeypatch, capsys):
        import analysis.weights as w
        from main import cmd_weights, main
        init_db()
        assert cmd_weights() is False
        assert "retour(s) sur" in capsys.readouterr().out

        rows = _synthetic_rows()
        monkeypatch.setattr(w, "propose_weights", lambda rows_=None: _real_propose(rows))
        assert cmd_weights() is True
        out = capsys.readouterr().out
        assert "--apply" in out and not config.SCORE_WEIGHTS_FILE.exists()
        main(["weights", "--apply"])
        assert config.SCORE_WEIGHTS_FILE.exists()
        main(["weights", "--reset"])
        assert not config.SCORE_WEIGHTS_FILE.exists()
