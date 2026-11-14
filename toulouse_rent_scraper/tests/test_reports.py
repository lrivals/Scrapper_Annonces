# tests/test_reports.py
# =========================
# Sprint 5 — journal des runs, rapports Markdown (top 10, nouvelles, comparatif,
# quartiers), conversion PDF (HTML seulement) et Top 10 par notification.
# =========================

import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import config
from config import SEARCH_PROFILES
from storage.migrations import SCHEMA_VERSION
from storage.sqlite import init_db, insert_annonce, set_annonce_status, upsert_annonce_profile

BLAGNAC = SEARCH_PROFILES["blagnac"]


@pytest.fixture
def db(temp_db, tmp_path, monkeypatch):
    import reporting.generator
    init_db()
    monkeypatch.setattr(reporting.generator, "REPORTS_DIR", tmp_path / "reports")
    yield temp_db


def _add(db, n, price=650, score=60.0, location="Pinot, Blagnac (31700)", profile="blagnac",
         matched_at=None, **cols):
    url = f"https://www.seloger.com/annonce/{n}"
    insert_annonce({"site": "SeLoger", "title": f"T2 n°{n}", "price": price,
                    "location_raw": location, "url": url})
    upsert_annonce_profile(url, profile, 1.2)
    with sqlite3.connect(db) as con:
        aid = con.execute("SELECT id FROM annonces WHERE url = ?", (url,)).fetchone()[0]
        con.execute("UPDATE annonce_profiles SET score = ? WHERE annonce_id = ?", (score, aid))
        if matched_at:
            con.execute("UPDATE annonce_profiles SET matched_at = ? WHERE annonce_id = ?", (matched_at, aid))
        if cols:
            sets = ", ".join(f"{k} = ?" for k in cols)
            con.execute(f"UPDATE annonces SET {sets} WHERE id = ?", (*cols.values(), aid))
    return aid


def _read(tmp_path, name, profile="blagnac"):
    return (tmp_path / "reports" / profile / name).read_text(encoding="utf-8")


# ---- 5.0 Migration et journal des runs ----

def test_migration_11_run_stats_and_expired_at(db):
    with sqlite3.connect(db) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 11
        cols = {r[1] for r in con.execute("PRAGMA table_info(run_stats)")}
    assert {"started_at", "profile", "new_count", "active_count", "median_rent_cc"} <= cols


def test_expired_at_set_by_trigger_and_cleared_on_reactivation(db):
    aid = _add(db, 1)
    before = datetime.now().isoformat(timespec="seconds")
    set_annonce_status(aid, "expired")
    with sqlite3.connect(db) as con:
        expired_at = con.execute("SELECT expired_at FROM annonces WHERE id = ?", (aid,)).fetchone()[0]
    assert expired_at is not None and expired_at >= before[:19]
    # De nouveau vue dans une recherche : réactivée, date effacée
    insert_annonce({"site": "SeLoger", "title": "T2", "price": 650, "location_raw": "Blagnac",
                    "url": "https://www.seloger.com/annonce/1"})
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT status, expired_at FROM annonces WHERE id = ?", (aid,)).fetchone() == ("active", None)


def test_record_run_snapshot(db):
    from storage.run_stats import last_runs, record_run

    _add(db, 1, price=600, surface_m2=40)
    _add(db, 2, price=700, charges=50, surface_m2=50)          # CC = 750
    _add(db, 3, price=900, duplicate_of=1)                       # doublon : hors stats
    total = SimpleNamespace(new_by_profile={"blagnac": 2}, updated=1, reactivated=0, duplicates=1, opened=3)
    start = datetime.now() - timedelta(minutes=5)
    assert record_run(start, ["blagnac"], ["SeLoger", "PAP"], total) == 1
    run = last_runs("blagnac")[0]
    assert run["new_count"] == 2 and run["sites"] == "SeLoger,PAP"
    assert run["active_count"] == 2
    assert run["median_rent_cc"] == 675            # médiane de 600 et 750
    assert run["median_ppm2"] == 15.0              # médiane de 15 et 15


def test_snapshot_empty():
    from storage.run_stats import snapshot
    assert snapshot([]) == {"active_count": 0, "median_rent_cc": None, "median_ppm2": None}


# ---- Petits formats ----

@pytest.mark.parametrize("score,badge", [(85, "⭐ 85"), (80, "⭐ 80"), (64.6, "✅ 65"), (45, "⚠️ 45"),
                                         (12, "❌ 12"), (None, "—")])
def test_score_badge(score, badge):
    from reporting.generator import score_badge
    assert score_badge(score) == badge


def test_short_description_cut_on_word():
    from reporting.generator import _short
    text = "Bel appartement lumineux " * 20
    short = _short(text)
    assert len(short) <= 151 and short.endswith("…") and not short.endswith(" …")
    assert _short("Court.") == "Court."
    assert _short(None) is None


# ---- 5.1 / 5.6 Rapports ----

def test_reports_written_and_sorted_by_score(db, tmp_path):
    from reporting.generator import generate_profile_reports

    _add(db, 1, price=600, score=50)
    _add(db, 2, price=650, score=82, surface_m2=46.73, nb_rooms=2, dpe_rating="C", furnished=1,
         publisher_type="individual", description="Très beau T2 " * 30,
         photos='["https://cdn.example/p1.jpg", "https://cdn.example/p2.jpg"]')
    excluded = _add(db, 3, price=500, score=99)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE annonce_profiles SET excluded_reasons = '[\"DPE G\"]' WHERE annonce_id = ?",
                    (excluded,))

    paths = generate_profile_reports(BLAGNAC, datetime.now() - timedelta(hours=1))
    names = [p.name for p in paths]
    assert names == ["top10.md", "nouvelles_annonces.md", "rapport_comparatif.md",
                     "rapport_quartiers.md", "toutes_les_annonces.md", "annonces_detaillees.md"]

    top = _read(tmp_path, "top10.md")
    assert top.index("⭐ 82") < top.index("⚠️ 50")
    assert "n°3" not in top and "/annonce/3" not in top         # exclue par les critères
    assert "46,7 m²" in top and "T2" in top and "Blagnac — Pinot" in top
    assert "📊 2 annonce(s)" in top

    new = _read(tmp_path, "nouvelles_annonces.md")
    assert new.index("T2 n°2") < new.index("T2 n°1")
    assert "| DPE | C |" in new and "| Meublé | Oui |" in new
    assert "SeLoger (particulier)" in new
    assert "![photo](https://cdn.example/p1.jpg)" in new and "p2.jpg" not in new
    quote = next(line for line in new.splitlines() if line.startswith("> "))
    assert len(quote) <= 2 + 151


def test_new_report_only_lists_this_run(db, tmp_path):
    from reporting.generator import generate_profile_reports

    _add(db, 1, matched_at=(datetime.now() - timedelta(days=3)).isoformat())
    _add(db, 2)
    generate_profile_reports(BLAGNAC, datetime.now() - timedelta(minutes=10))
    new = _read(tmp_path, "nouvelles_annonces.md")
    assert "T2 n°2" in new and "T2 n°1" not in new


def test_empty_profile_reports(db, tmp_path):
    from reporting.generator import generate_profile_reports
    generate_profile_reports(BLAGNAC)
    assert "Aucune annonce" in _read(tmp_path, "top10.md")
    assert "Aucune nouvelle annonce" in _read(tmp_path, "nouvelles_annonces.md")


# ---- 5.3 Comparatif ----

def test_comparison_since_previous_run(db):
    from reporting.generator import comparison_since
    from storage.run_stats import record_run

    total = SimpleNamespace(new_by_profile={}, updated=0, reactivated=0, duplicates=0, opened=0)
    assert comparison_since("blagnac")["previous"] is None       # aucun run : 24 h
    t1 = datetime(2026, 11, 13, 8, 0)
    record_run(t1, ["blagnac"], ["SeLoger"], total, finished_at=t1 + timedelta(minutes=20))
    assert comparison_since("blagnac")["since"] == t1.isoformat()
    t2 = datetime(2026, 11, 14, 8, 0)
    record_run(t2, ["blagnac"], ["SeLoger"], total, finished_at=t2 + timedelta(minutes=20))
    period = comparison_since("blagnac")
    assert period["since"] == (t1 + timedelta(minutes=20)).isoformat()
    assert period["previous"]["started_at"] == t1.isoformat()


def test_comparison_report_new_gone_drops_and_median(db, tmp_path):
    from reporting.generator import generate_profile_reports
    from storage.run_stats import record_run

    long_ago = (datetime.now() - timedelta(days=5)).isoformat()
    old = _add(db, 1, price=700, matched_at=long_ago)
    gone = _add(db, 2, price=800, matched_at=long_ago)
    total = SimpleNamespace(new_by_profile={}, updated=0, reactivated=0, duplicates=0, opened=0)
    t1 = datetime.now() - timedelta(days=1)
    record_run(t1, ["blagnac"], ["SeLoger"], total, finished_at=t1 + timedelta(minutes=10))
    with sqlite3.connect(db) as con:     # le prix connu avant le run précédent
        con.execute("UPDATE price_history SET seen_at = ? WHERE annonce_id IN (?, ?)", (long_ago, old, gone))

    # Run du jour : baisse de 700 → 640, une retirée, une nouvelle dans un nouveau quartier
    insert_annonce({"site": "SeLoger", "title": "T2 n°1", "price": 640, "location_raw": "Pinot, Blagnac (31700)",
                    "url": "https://www.seloger.com/annonce/1"})
    set_annonce_status(gone, "expired")
    _add(db, 3, price=690, location="Toulouse 31300 Purpan")
    t2 = datetime.now() - timedelta(minutes=1)
    record_run(t2, ["blagnac"], ["SeLoger"], total)

    generate_profile_reports(BLAGNAC, t2)
    report = _read(tmp_path, "rapport_comparatif.md")
    assert "**1** nouvelle(s), **1** retirée(s), **1** baisse(s) de prix" in report
    assert "700 € → **640 €** (-60 €)" in report
    assert "T2 n°2" in report.split("Retirées")[1]
    assert "Nouveau(x) secteur(s) : Toulouse" in report
    assert "(run précédent)" in report


def test_new_sectors_ignores_bare_commune_already_known():
    from reporting.generator import new_sectors
    older = [{"location_raw": "Pinot, Blagnac (31700)"}]
    new = [{"location_raw": "Blagnac (31700)"}, {"location_raw": "Grand Noble, Blagnac (31700)"},
           {"location_raw": "Colomiers (31770)"}]
    assert new_sectors(new, older) == ["Blagnac — Grand Noble", "Colomiers"]


# ---- 5.4 Quartiers ----

def test_quartiers_report_groups_variants(db, tmp_path):
    from reporting.generator import generate_profile_reports

    _add(db, 1, price=700, score=70, location="Croix-daurade, Toulouse (31200)", surface_m2=50)
    _add(db, 2, price=800, score=50, location="Toulouse 31200 Croix Daurade", surface_m2=40)
    _add(db, 3, price=600, score=80, location="Pinot, Blagnac (31700)")
    _add(db, 4, price=650, score=75, location="Pinot, Blagnac (31700)")
    _add(db, 5, price=900, score=20, location="Toulouse 31500 Bonnefoy")       # seul : commune seulement
    generate_profile_reports(BLAGNAC)
    report = _read(tmp_path, "rapport_quartiers.md")
    commune = report.split("## Classement")[0]
    assert "| Toulouse | 3 |" in commune and "| Blagnac | 2 |" in commune
    ranking = report.split("## Classement")[1].split("## Top 3")[0]
    # « Croix-daurade » (SeLoger) et « Croix Daurade » (LBC) : un seul quartier
    assert ranking.index("Pinot (Blagnac)") < ranking.index("Croix Daurade (Toulouse)")
    assert "| Croix Daurade (Toulouse) | 2 |" in ranking
    assert "Bonnefoy" not in ranking
    assert "| 750 € |" in ranking                 # médiane 700 / 800
    assert "17,0 €" in ranking                    # €/m² médian de 14 et 20


# ---- 5.5 PDF (conversion HTML, sans navigateur) ----

def test_markdown_to_html_subset():
    from reporting.pdf import markdown_to_html
    md = "\n".join([
        "# Titre", "", "**3** annonces", "", "| A | B |", "|---|---|", "| 1 | [lien](https://x.fr/?a=1&b=2) |",
        "", "1. un", "2. deux", "", "- puce", "", "> citation <b>", "", "![photo](https://x.fr/p.jpg)", "---",
    ])
    html = markdown_to_html(md)
    assert "<h1>Titre</h1>" in html and "<strong>3</strong>" in html
    assert "<th>A</th>" in html and "<td>1</td>" in html
    assert 'href="https://x.fr/?a=1&amp;b=2"' in html            # échappé une seule fois
    assert "<ol><li>un</li><li>deux</li></ol>" in html.replace("\n", "")
    assert "<ul><li>puce</li></ul>" in html.replace("\n", "")
    assert "&lt;b&gt;" in html                                       # pas de HTML brut
    assert '<img alt="photo" src="https://x.fr/p.jpg">' in html and "<hr>" in html
    assert "<img" not in markdown_to_html(md, images=False)


def test_pdf_failure_does_not_raise(tmp_path, monkeypatch):
    from reporting import pdf
    md = tmp_path / "top10.md"
    md.write_text("# Top", encoding="utf-8")
    monkeypatch.setattr(pdf, "_launch", lambda p: (_ for _ in ()).throw(RuntimeError("pas de navigateur")))
    assert pdf.markdown_files_to_pdf([md], title="Test") == []
    assert pdf.markdown_files_to_pdf([tmp_path / "absent.md"], title="Test") == []


# ---- 5.6 Top 10 par notification ----

def test_top10_message_plain_text(db):
    from notify.messages import top10_message
    from storage.run_stats import profile_rows
    from storage.sqlite import connect

    for n in range(12):
        _add(db, n, price=600 + n, score=50 + n)
    with connect() as conn:
        message = top10_message("blagnac", profile_rows(conn, "blagnac"))
    assert message["title"].startswith("🏆 Top 10")
    lines = message["body"].splitlines()
    assert lines[0].startswith("1. ⚠️ 61") or lines[0].startswith("1. ✅ 61")
    assert lines[1] == "https://www.seloger.com/annonce/11"
    assert "[lien]" not in message["body"] and " · " in lines[0]
    assert "📊 12 annonce(s)" in message["body"]
    assert top10_message("blagnac", []) is None


@pytest.fixture
def sent(monkeypatch):
    import notify
    calls = []
    monkeypatch.setattr(config, "NOTIFY_BACKEND", "ntfy")
    monkeypatch.setattr(notify, "send", lambda **kw: calls.append(kw) or True)
    return calls


def test_top10_daily_sent_once_per_day(db, sent, monkeypatch):
    from notify import notify_top10
    _add(db, 1)
    monkeypatch.setattr(config, "NOTIFY_TOP10", "daily")
    day = datetime(2026, 11, 14, 9)
    assert notify_top10(["blagnac"], now=day) == 1
    assert notify_top10(["blagnac"], now=day + timedelta(hours=6)) == 0
    assert notify_top10(["blagnac"], now=day + timedelta(days=1)) == 1
    assert len(sent) == 2


def test_top10_off_by_default_and_run_mode(db, sent, monkeypatch):
    from notify import notify_top10
    _add(db, 1)
    assert notify_top10(["blagnac"]) == 0                 # conftest : NOTIFY_TOP10 = "off"
    monkeypatch.setattr(config, "NOTIFY_TOP10", "run")
    assert notify_top10(["blagnac"]) == notify_top10(["blagnac"]) == 1
