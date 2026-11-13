# tests/test_photo_duplicates.py
# =========================
# Sprint 15.8 — doublons inter-sites par empreinte de la première photo
# =========================

import io
import json
import random
import sqlite3

import pytest
from PIL import Image, ImageDraw, ImageFilter

import config
from filters.photo_duplicates import (
    compute_missing_hashes, dhash, download_image, find_photo_duplicates, first_photo, hamming,
    is_uniform, link_photo_duplicates, run_photo_dedup,
)
from storage.migrations import SCHEMA_VERSION
from storage.sqlite import init_db, insert_annonce, update_annonce_enrichment, upsert_annonce_profile


def _photo(seed: int, size=(640, 480)) -> Image.Image:
    """Photo synthétique : formes aléatoires, différente pour chaque graine."""
    rng = random.Random(seed)
    img = Image.new("RGB", size, tuple(rng.randrange(256) for _ in range(3)))
    draw = ImageDraw.Draw(img)
    for _ in range(25):
        x0, y0 = rng.randrange(size[0]), rng.randrange(size[1])
        x1, y1 = x0 + rng.randrange(40, 300), y0 + rng.randrange(40, 300)
        draw.rectangle([x0, y0, x1, y1], fill=tuple(rng.randrange(256) for _ in range(3)))
    return img


def _jpeg(img: Image.Image, quality=90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Empreinte
# ---------------------------------------------------------------------------

class TestHash:
    def test_same_photo_resized_and_recompressed(self):
        original = _photo(1)
        h1 = dhash(_jpeg(original))
        h2 = dhash(_jpeg(original.resize((320, 240)), quality=55))           # miniature d'un autre site
        h3 = dhash(_jpeg(original.filter(ImageFilter.GaussianBlur(1)), 70))  # léger flou
        assert len(h1) == 16
        assert hamming(h1, h2) <= config.PHOTO_HASH_MAX_DISTANCE
        assert hamming(h1, h3) <= config.PHOTO_HASH_MAX_DISTANCE

    def test_different_photos(self):
        hashes = [dhash(_jpeg(_photo(seed))) for seed in range(2, 8)]
        for i, a in enumerate(hashes):
            for b in hashes[i + 1:]:
                assert hamming(a, b) > config.PHOTO_HASH_MAX_DISTANCE

    def test_png_and_unreadable(self):
        buf = io.BytesIO()
        _photo(3).save(buf, "PNG")
        assert hamming(dhash(buf.getvalue()), dhash(_jpeg(_photo(3)))) <= config.PHOTO_HASH_MAX_DISTANCE
        with pytest.raises(ValueError):
            dhash(b"<html>pas une image</html>")

    def test_uniform_image(self):
        assert is_uniform(dhash(_jpeg(Image.new("RGB", (200, 200), "grey"))))
        assert not is_uniform(dhash(_jpeg(_photo(4))))

    @pytest.mark.parametrize("photos, expected", [
        ('["https://img/1.jpg", "https://img/2.jpg"]', "https://img/1.jpg"),
        (["https://img/1.jpg"], "https://img/1.jpg"),
        ("https://img/seule.jpg", "https://img/seule.jpg"),
        ('["/relative.jpg", "https://img/2.jpg"]', "https://img/2.jpg"),
        ("[]", None), ("", None), (None, None), ("[cassé", None), ("data:image/png;base64,xx", None),
    ])
    def test_first_photo(self, photos, expected):
        assert first_photo(photos) == expected


# ---------------------------------------------------------------------------
# Rapprochement (sans base)
# ---------------------------------------------------------------------------

def _row(id_, site, price, h, duplicate_of=None, root_site=None):
    return {"id": id_, "url": f"https://{site}/{id_}", "site": site, "price": price, "photo_hash": h,
            "duplicate_of": duplicate_of, "root_site": root_site}


H = "f0e1d2c3b4a59687"
NEAR = f"{int(H, 16) ^ 0b111:016x}"     # 3 bits d'écart
FAR = f"{int(H, 16) ^ 0xFFFF:016x}"     # 16 bits d'écart


class TestMatching:
    def test_same_photo_other_site(self):
        links = find_photo_duplicates([_row(1, "LeBonCoin", 600, H), _row(2, "Bien'ici", 620, NEAR)])
        assert links == [{"id": 2, "url": "https://Bien'ici/2", "original_id": 1, "distance": 3}]

    @pytest.mark.parametrize("rows", [
        [_row(1, "LeBonCoin", 600, H), _row(2, "LeBonCoin", 600, H)],          # même site
        [_row(1, "LeBonCoin", 600, H), _row(2, "Bien'ici", 600, FAR)],         # photo différente
        [_row(1, "LeBonCoin", 600, H), _row(2, "Bien'ici", 700, H)],           # prix trop éloigné
        [_row(1, "LeBonCoin", 600, H), _row(2, "Bien'ici", None, H)],          # prix inconnu
    ])
    def test_no_match(self, rows):
        assert find_photo_duplicates(rows) == []

    def test_generic_photo_ignored(self):
        """Logo d'agence réutilisé sur toutes ses annonces : pas un indice de doublon."""
        rows = [_row(i, "SeLoger", 600, H) for i in range(1, config.PHOTO_GENERIC_MAX_SAME_SITE + 2)]
        rows.append(_row(99, "Bien'ici", 600, H))
        assert find_photo_duplicates(rows) == []

    def test_uniform_photo_ignored(self):
        rows = [_row(1, "LeBonCoin", 600, "0" * 16), _row(2, "Bien'ici", 600, "0" * 16)]
        assert find_photo_duplicates(rows) == []

    def test_links_to_root_without_chain(self):
        rows = [
            _row(1, "SeLoger", 600, H),
            _row(2, "LeBonCoin", 600, H, duplicate_of=1, root_site="SeLoger"),
            _row(3, "Bien'ici", 605, NEAR),
        ]
        assert [(l["id"], l["original_id"]) for l in find_photo_duplicates(rows)] == [(3, 1)]

    def test_three_sites_in_one_pass(self):
        rows = [_row(1, "SeLoger", 600, H), _row(2, "LeBonCoin", 600, NEAR), _row(3, "Bien'ici", 600, H)]
        assert [(l["id"], l["original_id"]) for l in find_photo_duplicates(rows)] == [(2, 1), (3, 1)]

    def test_never_matches_own_root_site(self):
        """Un doublon LBC d'une annonce SeLoger ne rattache pas une autre annonce SeLoger."""
        rows = [
            _row(1, "SeLoger", 600, FAR),
            _row(2, "LeBonCoin", 600, H, duplicate_of=1, root_site="SeLoger"),
            _row(3, "SeLoger", 600, H),
        ]
        assert find_photo_duplicates(rows) == []

    def test_existing_duplicate_not_relinked(self):
        rows = [_row(1, "LeBonCoin", 600, H), _row(2, "Bien'ici", 600, H, duplicate_of=1, root_site="LeBonCoin")]
        assert find_photo_duplicates(rows) == []


# ---------------------------------------------------------------------------
# Base, téléchargement, CLI
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, body=b"", status=200, content_type="image/jpeg"):
        self.status_code, self.body = status, body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def get(self, url, **kwargs):
        self.calls.append(url)
        r = self.responses.get(url)
        if isinstance(r, Exception):
            raise r
        return r or FakeResponse(status=404)


def _add(url, site, price, photos, location="Toulouse"):
    insert_annonce({"site": site, "title": f"Appartement {site}", "price": price,
                    "location_raw": location, "url": url})
    upsert_annonce_profile(url, "blagnac", 3.0)
    update_annonce_enrichment(url, {"photos": photos})


def _db(temp_db, sql, *args):
    with sqlite3.connect(temp_db) as con:
        return con.execute(sql, args).fetchall()


def test_migration(temp_db):
    init_db()
    cols = {r[1] for r in _db(temp_db, "PRAGMA table_info(annonces)")}
    assert {"photo_hash", "photo_hash_attempts"} <= cols
    assert _db(temp_db, "PRAGMA user_version")[0][0] == SCHEMA_VERSION


def test_download_limits():
    session = FakeSession({
        "https://ok": FakeResponse(b"x" * 10),
        "https://html": FakeResponse(b"<html>", content_type="text/html"),
        "https://big": FakeResponse(b"x" * (config.PHOTO_MAX_BYTES + 1)),
    })
    assert download_image("https://ok", session) == b"x" * 10
    for url in ("https://html", "https://big", "https://absent"):
        with pytest.raises(ValueError):
            download_image(url, session)


def test_end_to_end_links_lbc_and_bienici(temp_db):
    """Même bien, adresse décrite différemment : la détection texte échoue, la photo le trouve."""
    init_db()
    photo = _photo(10)
    _add("https://lbc/1", "LeBonCoin", 650, ["https://img.lbc/1.jpg"], "Blagnac 31700 Centre")
    _add("https://bienici/1", "Bien'ici", 640, ["https://img.bienici/1.jpg"], "Blagnac")
    _add("https://bienici/2", "Bien'ici", 650, ["https://img.bienici/2.jpg"], "Blagnac")
    session = FakeSession({
        "https://img.lbc/1.jpg": FakeResponse(_jpeg(photo)),
        "https://img.bienici/1.jpg": FakeResponse(_jpeg(photo.resize((400, 300)), 60)),
        "https://img.bienici/2.jpg": FakeResponse(_jpeg(_photo(11))),
    })
    stats = compute_missing_hashes(session=session, sleep=lambda s: None)
    assert stats == {"hashed": 3, "failed": 0}
    assert link_photo_duplicates() == 1
    dups = dict(_db(temp_db, "SELECT url, duplicate_of FROM annonces"))
    assert dups == {"https://lbc/1": None, "https://bienici/1": 1, "https://bienici/2": None}
    # Second passage : rien à recalculer ni à rattacher
    assert compute_missing_hashes(session=session, sleep=lambda s: None) == {"hashed": 0, "failed": 0}
    assert link_photo_duplicates() == 0


def test_failed_downloads_are_retried_then_abandoned(temp_db):
    init_db()
    _add("https://lbc/1", "LeBonCoin", 600, ["https://img/broken.jpg"])
    session = FakeSession({"https://img/broken.jpg": ConnectionError("réseau")})
    for _ in range(config.PHOTO_HASH_MAX_ATTEMPTS):
        assert compute_missing_hashes(session=session, sleep=lambda s: None)["failed"] == 1
    assert compute_missing_hashes(session=session, sleep=lambda s: None) == {"hashed": 0, "failed": 0}
    assert len(session.calls) == config.PHOTO_HASH_MAX_ATTEMPTS


def test_limit_and_inactive(temp_db):
    init_db()
    for i in range(4):
        _add(f"https://lbc/{i}", "LeBonCoin", 600, [f"https://img/{i}.jpg"])
    _db(temp_db, "UPDATE annonces SET status = 'expired' WHERE url = 'https://lbc/3'")
    session = FakeSession({f"https://img/{i}.jpg": FakeResponse(_jpeg(_photo(i))) for i in range(4)})
    assert compute_missing_hashes(limit=2, session=session, sleep=lambda s: None)["hashed"] == 2
    assert session.calls == ["https://img/2.jpg", "https://img/1.jpg"]   # plus récentes d'abord, actives


def test_run_photo_dedup_switches(temp_db, monkeypatch):
    import filters.photo_duplicates as pd
    init_db()
    assert run_photo_dedup() == {"hashed": 0, "failed": 0, "linked": 0}   # désactivé (conftest)
    monkeypatch.setattr(config, "PHOTO_DEDUP_ENABLED", True)
    monkeypatch.setattr(pd, "pillow_available", lambda: False)
    assert run_photo_dedup()["hashed"] == 0
    monkeypatch.setattr(pd, "pillow_available", lambda: True)

    def boom(limit=None):
        raise RuntimeError("panne")
    monkeypatch.setattr(pd, "compute_missing_hashes", boom)
    assert run_photo_dedup() == {"hashed": 0, "failed": 0, "linked": 0}   # jamais d'exception


def test_duplicate_not_notified_as_new(temp_db, monkeypatch):
    from notify.messages import build_messages
    from scoring import rescore
    from storage.sqlite import set_duplicate_of
    monkeypatch.setattr(config, "NOTIFY_MIN_SCORE", 0)
    init_db()
    _add("https://lbc/1", "LeBonCoin", 600, ["https://img/1.jpg"])
    _add("https://bienici/1", "Bien'ici", 600, ["https://img/2.jpg"])
    set_duplicate_of("https://bienici/1", 1)
    rescore()
    messages = build_messages([{"kind": "new", "profile": "blagnac", "url": u}
                               for u in ("https://lbc/1", "https://bienici/1")])
    assert [m["url"] for m in messages] == ["https://lbc/1"]
    # Une baisse de prix sur le doublon reste signalée
    drop = build_messages([{"kind": "price_drop", "profile": "blagnac", "url": "https://bienici/1",
                            "old_price": 650}])
    assert len(drop) == 1


def test_cli_dedupe(temp_db, monkeypatch):
    import filters.photo_duplicates as pd
    from main import main
    calls = []
    monkeypatch.setattr(pd, "run_photo_dedup", lambda limit=None: calls.append(limit) or
                        {"hashed": 0, "failed": 0, "linked": 0})
    main(["dedupe", "--limit", "7"])
    assert calls == [7]


def test_photos_json_is_stored_as_expected(temp_db):
    """La colonne `photos` écrite par l'enrichissement est bien lue par first_photo."""
    init_db()
    _add("https://lbc/1", "LeBonCoin", 600, ["https://img/a.jpg", "https://img/b.jpg"])
    stored = _db(temp_db, "SELECT photos FROM annonces")[0][0]
    assert json.loads(stored)[0] == "https://img/a.jpg"
    assert first_photo(stored) == "https://img/a.jpg"
