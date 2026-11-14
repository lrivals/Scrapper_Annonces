# tests/test_enricher.py
# =========================
# Tests pour le pipeline d'enrichissement
# =========================

from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import pytest


def _fake_session(page):
    """Remplace chrome_session : aucun Chrome lancé, yield (browser, page)."""
    @contextmanager
    def session(*args, **kwargs):
        yield MagicMock(), page
    return session


class TestEnrichAnnonces:
    """Tests pour enrich_annonces() avec DB et Playwright mockés."""

    def test_enrich_empty_db(self, temp_db):
        """Aucune annonce en attente → retourne 0 enrichies."""
        from storage.sqlite import init_db
        init_db()

        with patch("scrapers.enricher.get_pending_annonces", return_value=[]):
            from scrapers.enricher import enrich_annonces
            result = enrich_annonces(limit=10)

        assert result["total"] == 0
        assert result["enriched"] == 0
        assert result["errors"] == 0

    def test_enrich_marks_done(self, temp_db):
        """Une annonce SeLoger → extracteur appelé → enrichment_status='done' en DB."""
        from storage.sqlite import init_db, insert_annonce, get_pending_annonces
        init_db()
        insert_annonce({
            "site": "SeLoger",
            "title": "Studio test",
            "price": 400,
            "location_raw": "Rangueil",
            "distance_enac_km": 1.0,
            "url": "https://seloger.com/test/enricher/1",
        })

        fake_detail = {
            "surface_m2": 28.0,
            "nb_rooms": 1,
            "dpe_rating": "C",
            "enrichment_status": "done",
        }

        mock_page = MagicMock()
        mock_page.url = "https://seloger.com/test/enricher/1"
        mock_page.goto.return_value = None

        with patch("scrapers.enricher.chrome_session", _fake_session(mock_page)), \
             patch("scrapers.enricher.is_page_blocked", return_value=False), \
             patch("scrapers.detail_extractors.seloger_detail.extract_detail", return_value=fake_detail):
            from scrapers.enricher import enrich_annonces
            result = enrich_annonces(limit=10)

        assert result["enriched"] == 1
        assert result["errors"] == 0

        # Vérifier en DB
        import sqlite3
        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT enrichment_status, surface_m2, dpe_rating FROM annonces WHERE url = ?",
            ("https://seloger.com/test/enricher/1",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "done"
        assert row[1] == 28.0
        assert row[2] == "C"

    def test_enrich_marks_error_on_exception(self, temp_db):
        """Extracteur qui lève une exception → enrichment_status='error' en DB."""
        from storage.sqlite import init_db, insert_annonce
        init_db()
        insert_annonce({
            "site": "LeBonCoin",
            "title": "Chambre test",
            "price": 350,
            "location_raw": "Ramonville",
            "distance_enac_km": 3.0,
            "url": "https://www.leboncoin.fr/ad/locations/enricher/1",
        })

        mock_page = MagicMock()
        mock_page.url = "https://www.leboncoin.fr/ad/locations/enricher/1"
        mock_page.goto.return_value = None

        with patch("scrapers.enricher.chrome_session", _fake_session(mock_page)), \
             patch("scrapers.enricher.is_page_blocked", return_value=False), \
             patch(
                 "scrapers.detail_extractors.leboncoin_detail.extract_detail",
                 side_effect=RuntimeError("Sélecteur introuvable"),
             ):
            from scrapers.enricher import enrich_annonces
            result = enrich_annonces(limit=10)

        assert result["errors"] == 1
        assert result["enriched"] == 0

    def test_site_filter_seloger(self, temp_db):
        """site_filter='SeLoger' ne récupère que les annonces SeLoger."""
        from storage.sqlite import init_db, insert_annonce
        init_db()
        insert_annonce({
            "site": "SeLoger",
            "title": "Studio SeLoger",
            "price": 400,
            "location_raw": "Rangueil",
            "distance_enac_km": 1.0,
            "url": "https://seloger.com/filter/test/1",
        })
        insert_annonce({
            "site": "LeBonCoin",
            "title": "Studio LBC",
            "price": 380,
            "location_raw": "Rangueil",
            "distance_enac_km": 1.5,
            "url": "https://www.leboncoin.fr/filter/test/1",
        })

        captured = {}

        def fake_get_pending(site_filter=None, limit=50):
            captured["site_filter"] = site_filter
            return []

        with patch("scrapers.enricher.get_pending_annonces", side_effect=fake_get_pending):
            from scrapers.enricher import enrich_annonces
            enrich_annonces(site_filter="SeLoger", limit=10)

        assert captured.get("site_filter") == "SeLoger"


# ---- Nouvel essai et annonces retirées (Sprint 13.4) ----

import sqlite3
from datetime import datetime, timedelta


def _insert(url, site="LeBonCoin"):
    from storage.sqlite import insert_annonce
    insert_annonce({"site": site, "title": "Studio", "price": 400,
                    "location_raw": "Rangueil", "url": url})


def _set(db, url, **cols):
    sets = ", ".join(f"{k} = ?" for k in cols)
    with sqlite3.connect(db) as con:
        con.execute(f"UPDATE annonces SET {sets} WHERE url = ?", (*cols.values(), url))


def _row(db, url):
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        return dict(con.execute("SELECT * FROM annonces WHERE url = ?", (url,)).fetchone())


class TestRetry:
    def test_pending_selection_rules(self, temp_db):
        from storage.sqlite import init_db, get_pending_annonces
        init_db()
        old = (datetime.now() - timedelta(hours=30)).isoformat()
        recent = (datetime.now() - timedelta(hours=2)).isoformat()
        for url in ("p", "old_err", "recent_err", "too_many", "failed", "done", "hidden"):
            _insert(f"https://lbc.fr/{url}")
        _set(temp_db, "https://lbc.fr/old_err", enrichment_status="error", enrichment_attempts=1, enriched_at=old)
        _set(temp_db, "https://lbc.fr/recent_err", enrichment_status="error", enrichment_attempts=1, enriched_at=recent)
        _set(temp_db, "https://lbc.fr/too_many", enrichment_status="error", enrichment_attempts=3, enriched_at=old)
        _set(temp_db, "https://lbc.fr/failed", enrichment_status="failed", enrichment_attempts=3, enriched_at=old)
        _set(temp_db, "https://lbc.fr/done", enrichment_status="done")
        _set(temp_db, "https://lbc.fr/hidden", status="hidden")

        urls = [a["url"] for a in get_pending_annonces(limit=10)]
        assert urls == ["https://lbc.fr/p", "https://lbc.fr/old_err"]  # pending d'abord

    def _run(self, page, extractor):
        with patch("scrapers.enricher.chrome_session", _fake_session(page)), \
             patch("scrapers.enricher.is_page_blocked", return_value=False), \
             patch("scrapers.enricher.time.sleep"), \
             patch("scrapers.detail_extractors.leboncoin_detail.extract_detail", side_effect=extractor):
            from scrapers.enricher import enrich_annonces
            return enrich_annonces(limit=10)

    def _page(self, html="<html>Studio 20 m²</html>", text=None):
        import re
        page = MagicMock()
        page.content.return_value = html
        page.inner_text.return_value = text if text is not None else re.sub(r"<[^>]+>", "", html)
        return page

    def test_failure_counts_attempts_then_failed(self, temp_db):
        from storage.sqlite import init_db
        init_db()
        _insert("https://lbc.fr/1")
        boom = RuntimeError("sélecteur introuvable")

        self._run(self._page(), boom)
        row = _row(temp_db, "https://lbc.fr/1")
        assert (row["enrichment_status"], row["enrichment_attempts"]) == ("error", 1)
        assert "sélecteur" in row["error_detail"]

        _set(temp_db, "https://lbc.fr/1", enrichment_attempts=2,
             enriched_at=(datetime.now() - timedelta(days=2)).isoformat())
        self._run(self._page(), boom)
        row = _row(temp_db, "https://lbc.fr/1")
        assert (row["enrichment_status"], row["enrichment_attempts"]) == ("failed", 3)

    def test_success_after_retry(self, temp_db):
        from storage.sqlite import init_db
        init_db()
        _insert("https://lbc.fr/1")
        _set(temp_db, "https://lbc.fr/1", enrichment_status="error", enrichment_attempts=1,
             enriched_at=(datetime.now() - timedelta(days=2)).isoformat())
        result = self._run(self._page(), lambda page, url: {"enrichment_status": "done", "surface_m2": 20})
        assert result["enriched"] == 1
        row = _row(temp_db, "https://lbc.fr/1")
        assert (row["enrichment_status"], row["enrichment_attempts"], row["surface_m2"]) == ("done", 2, 20)

    def test_removed_annonce_marked_expired_without_extraction(self, temp_db):
        from storage.sqlite import init_db
        init_db()
        _insert("https://lbc.fr/1")
        extractor = MagicMock()
        result = self._run(self._page("<p>Cette annonce n'est plus en ligne</p>"), extractor)
        extractor.assert_not_called()
        assert result["expired"] == 1
        row = _row(temp_db, "https://lbc.fr/1")
        assert (row["status"], row["enrichment_status"]) == ("expired", "skipped")

    def test_error_strings_hidden_in_scripts_do_not_expire_live_ad(self, temp_db):
        """
        Régression 2026-11-13 : une page LBC en ligne embarque « annonce introuvable »,
        « page introuvable »… dans ses scripts. Seul le texte visible doit compter.
        """
        from storage.sqlite import init_db
        init_db()
        _insert("https://lbc.fr/1")
        html = ('<html><script>{"errors":{"notFound":"Annonce introuvable","404":"Page introuvable"}}'
                '</script><p>T3 duplex 68 m²</p></html>')
        extractor = MagicMock(return_value={"enrichment_status": "done", "surface_m2": 68})
        result = self._run(self._page(html, text="T3 duplex 68 m²"), extractor)
        extractor.assert_called_once()
        assert result["expired"] == 0
        row = _row(temp_db, "https://lbc.fr/1")
        assert row["status"] != "expired"


# ---- Sprint 16.3 — ouverture des fiches : budget par site et anti-ban ----

class TestOpenAnnonces:
    def _annonces(self, temp_db, n_lbc, n_sl):
        from storage.sqlite import init_db
        init_db()
        out = []
        for i in range(n_lbc):
            _insert(f"https://lbc.fr/{i}")
            out.append(_row(temp_db, f"https://lbc.fr/{i}"))
        for i in range(n_sl):
            _insert(f"https://seloger.com/{i}", site="SeLoger")
            out.append(_row(temp_db, f"https://seloger.com/{i}"))
        return out

    def _page(self):
        page = MagicMock()
        page.content.return_value = "<html>T2 40 m²</html>"
        page.inner_text.return_value = "T2 40 m²"
        return page

    def _patches(self, page, blocked=lambda p: False, challenge=True):
        done = lambda page, url: {"enrichment_status": "done", "surface_m2": 40}  # noqa: E731
        return [
            patch("scrapers.enricher.chrome_session", _fake_session(page)),
            patch("scrapers.enricher.is_page_blocked", side_effect=blocked),
            patch("scrapers.enricher.wait_for_challenge", return_value=challenge),
            patch("scrapers.enricher.time.sleep"),
            patch("scrapers.detail_extractors.leboncoin_detail.extract_detail", side_effect=done),
            patch("scrapers.detail_extractors.seloger_detail.extract_detail", side_effect=done),
        ]

    def _open(self, annonces, page, **kwargs):
        from contextlib import ExitStack
        from scrapers.enricher import open_annonces
        blocked = kwargs.pop("blocked", lambda p: False)
        challenge = kwargs.pop("challenge", True)
        with ExitStack() as stack:
            for p in self._patches(page, blocked, challenge):
                stack.enter_context(p)
            return open_annonces(annonces, **kwargs)

    def test_budget_per_site(self, temp_db):
        page = self._page()
        stats = self._open(self._annonces(temp_db, 5, 3), page, budget={"LeBonCoin": 2, "SeLoger": 2})
        assert (stats.opened, stats.enriched) == (4, 4)
        visited = [c.args[0] for c in page.goto.call_args_list]
        assert visited == ["https://lbc.fr/0", "https://lbc.fr/1", "https://seloger.com/0", "https://seloger.com/1"]
        assert _row(temp_db, "https://lbc.fr/2")["enrichment_status"] == "pending"

    def test_unresolved_challenge_stops_only_that_site(self, temp_db):
        from scrapers.antibot import recently_blocked
        page = self._page()
        # Challenge sur toute page LeBonCoin, jamais résolu
        page_url = {"u": ""}
        page.goto.side_effect = lambda url, **kw: page_url.update(u=url)
        stats = self._open(self._annonces(temp_db, 3, 2), page,
                           blocked=lambda p: "lbc.fr" in page_url["u"], challenge=False)
        visited = [c.args[0] for c in page.goto.call_args_list]
        assert visited == ["https://lbc.fr/0", "https://seloger.com/0", "https://seloger.com/1"]
        assert stats.enriched == 2 and stats.skipped_sites == ["LeBonCoin"]
        assert recently_blocked("LeBonCoin")
        # la fiche bloquée n'est pas pénalisée : elle reste à ouvrir
        assert _row(temp_db, "https://lbc.fr/0")["enrichment_status"] == "pending"

    def test_site_blocked_during_run_not_opened(self, temp_db):
        from datetime import datetime, timedelta
        from scrapers.antibot import record_block
        annonces = self._annonces(temp_db, 2, 1)
        start = datetime.now() - timedelta(minutes=5)
        record_block("LeBonCoin")
        page = self._page()
        stats = self._open(annonces, page, blocked_since=start)
        assert [c.args[0] for c in page.goto.call_args_list] == ["https://seloger.com/0"]
        assert stats.skipped_sites == ["LeBonCoin"]

    def test_old_block_ignored_when_attended_but_skipped_unattended(self, temp_db):
        from datetime import datetime, timedelta
        from scrapers.antibot import record_block
        annonces = self._annonces(temp_db, 1, 0)
        record_block("LeBonCoin", now=datetime.now() - timedelta(hours=1))
        since = datetime.now() - timedelta(minutes=5)
        assert self._open(annonces, self._page(), blocked_since=since).opened == 1
        assert self._open(annonces, self._page(), blocked_since=since, unattended=True).opened == 0

    def test_select_respects_budget_and_global_limit(self, temp_db):
        from scrapers.enricher import select_annonces_to_open
        from storage.sqlite import upsert_annonce_profile
        for a in self._annonces(temp_db, 4, 4):
            upsert_annonce_profile(a["url"], "enac", 1.0)
        _insert("https://bienici.com/1", site="Bien'ici")
        upsert_annonce_profile("https://bienici.com/1", "enac", 1.0)
        sites = ["LeBonCoin", "SeLoger", "Bien'ici"]
        chosen = select_annonces_to_open(["https://seloger.com/3"], sites,
                                         budget={"LeBonCoin": 3, "SeLoger": 2, "Bien'ici": 5})
        by_site = [a["site"] for a in chosen]
        assert by_site.count("LeBonCoin") == 3 and by_site.count("SeLoger") == 2
        assert "Bien'ici" not in by_site                      # pas de page de détail
        limited = select_annonces_to_open(["https://seloger.com/3"], sites, limit=1,
                                          budget={"LeBonCoin": 3, "SeLoger": 2})
        assert [a["url"] for a in limited] == ["https://seloger.com/3"]   # annonce du run d'abord

    def test_enrich_annonces_still_post_processes(self, temp_db):
        self._annonces(temp_db, 1, 0)
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in self._patches(self._page()):
                stack.enter_context(p)
            rescore = stack.enter_context(patch("scoring.rescore"))
            llm = stack.enter_context(patch("analysis.llm.maybe_analyze"))
            from scrapers.enricher import enrich_annonces
            result = enrich_annonces(limit=10)
        assert result["enriched"] == 1 and "opened" not in result
        rescore.assert_called_once()
        llm.assert_called_once()
