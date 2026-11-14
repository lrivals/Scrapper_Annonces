# tests/test_storage.py
# =========================
# Tests unitaires pour le stockage SQLite
# =========================

import pytest
import sqlite3

from storage.sqlite import (
    init_db, insert_annonce, annonce_exists, set_annonce_status,
    find_potential_duplicates, set_duplicate_of,
)


class TestSQLiteStorage:
    """Tests pour le stockage SQLite."""
    
    def test_init_db(self, temp_db):
        """Test initialisation de la base de données."""
        init_db()
        assert temp_db.exists(), "La base de données devrait être créée"
    
    def test_insert_new_annonce(self, temp_db, sample_annonce_filtered):
        """Test insertion d'une nouvelle annonce."""
        init_db()
        
        result = insert_annonce(sample_annonce_filtered)
        assert result == "new", "L'insertion devrait réussir pour une nouvelle annonce"
        
        # Vérifier que l'annonce existe
        assert annonce_exists(sample_annonce_filtered["url"])
    
    def test_insert_duplicate_annonce(self, temp_db, sample_annonce_filtered):
        """Test insertion d'une annonce déjà existante (déduplication)."""
        init_db()
        
        # Première insertion
        insert_annonce(sample_annonce_filtered)
        
        # Tentative de ré-insertion
        result = insert_annonce(sample_annonce_filtered)
        assert result == "unchanged", "La ré-insertion ne doit pas créer de doublon"
    
    def test_annonce_exists_false(self, temp_db):
        """Test vérification d'existence pour une annonce inexistante."""
        init_db()
        
        result = annonce_exists("https://example.com/fake/12345")
        assert result is False
    
    def test_annonce_exists_true(self, temp_db, sample_annonce_filtered):
        """Test vérification d'existence pour une annonce existante."""
        init_db()
        insert_annonce(sample_annonce_filtered)
        
        result = annonce_exists(sample_annonce_filtered["url"])
        assert result is True


class TestDatabaseIntegrity:
    """Tests d'intégrité de la base de données."""
    
    def test_unique_url_constraint(self, temp_db, sample_annonce_filtered):
        """Test que la contrainte UNIQUE sur l'URL fonctionne."""
        init_db()
        
        # Première insertion
        result1 = insert_annonce(sample_annonce_filtered)
        assert result1 == "new"
        
        # Modifier légèrement l'annonce mais garder la même URL
        annonce_modified = sample_annonce_filtered.copy()
        annonce_modified["price"] = 999
        annonce_modified["title"] = "Titre différent"
        
        # Tentative d'insertion avec même URL
        result2 = insert_annonce(annonce_modified)
        assert result2 == "updated", "Même URL : mise à jour, pas de nouvelle ligne"
        with sqlite3.connect(temp_db) as con:
            assert con.execute("SELECT COUNT(*) FROM annonces").fetchone()[0] == 1


def _row(db, url):
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        return dict(con.execute("SELECT * FROM annonces WHERE url = ?", (url,)).fetchone())


class TestStatusLifecycle:
    """Sprint 11 — réactivation des expirées, masquage durable."""

    def _expire(self, db, url):
        with sqlite3.connect(db) as con:
            con.execute(
                "UPDATE annonces SET status = 'expired', checked_at = '2026-01-01' WHERE url = ?",
                (url,),
            )

    def test_expired_annonce_is_reactivated(self, temp_db, sample_annonce_filtered):
        init_db()
        insert_annonce(sample_annonce_filtered)
        self._expire(temp_db, sample_annonce_filtered["url"])

        assert insert_annonce(sample_annonce_filtered) == "reactivated"
        row = _row(temp_db, sample_annonce_filtered["url"])
        assert row["status"] == "active"
        assert row["checked_at"] is None

    def test_reactivation_also_updates_price(self, temp_db, sample_annonce_filtered):
        init_db()
        insert_annonce(sample_annonce_filtered)
        self._expire(temp_db, sample_annonce_filtered["url"])

        insert_annonce({**sample_annonce_filtered, "price": 399})
        assert _row(temp_db, sample_annonce_filtered["url"])["price"] == 399

    def test_hidden_annonce_stays_hidden(self, temp_db, sample_annonce_filtered):
        init_db()
        insert_annonce(sample_annonce_filtered)
        annonce_id = _row(temp_db, sample_annonce_filtered["url"])["id"]
        assert set_annonce_status(annonce_id, "hidden") == sample_annonce_filtered["title"]

        assert insert_annonce(sample_annonce_filtered) == "unchanged"
        assert _row(temp_db, sample_annonce_filtered["url"])["status"] == "hidden"

    def test_location_and_distance_updated(self, temp_db, sample_annonce_filtered):
        init_db()
        insert_annonce(sample_annonce_filtered)
        insert_annonce({**sample_annonce_filtered, "location_raw": "Saouzelong", "distance_enac_km": 2.1})
        row = _row(temp_db, sample_annonce_filtered["url"])
        assert row["location_raw"] == "Saouzelong"
        assert row["distance_enac_km"] == 2.1

    def test_missing_fields_do_not_erase_existing(self, temp_db, sample_annonce_filtered):
        init_db()
        insert_annonce(sample_annonce_filtered)
        insert_annonce({**sample_annonce_filtered, "location_raw": None, "distance_enac_km": None})
        row = _row(temp_db, sample_annonce_filtered["url"])
        assert row["location_raw"] == sample_annonce_filtered["location_raw"]
        assert row["distance_enac_km"] == sample_annonce_filtered["distance_enac_km"]

    def test_set_status_unknown_id(self, temp_db):
        init_db()
        assert set_annonce_status(9999, "hidden") is None

    def test_set_status_invalid(self, temp_db):
        init_db()
        with pytest.raises(ValueError):
            set_annonce_status(1, "deleted")


class TestDuplicates:
    """Sprint 11 — même bien sur deux sites."""

    LBC = {
        "site": "LeBonCoin",
        "title": "Studio Rangueil",
        "price": 422,
        "location_raw": "Toulouse 31400 Rangueil",
        "distance_enac_km": 1.4,
        "url": "https://www.leboncoin.fr/locations/1.htm",
    }
    SELOGER = {
        "site": "SeLoger",
        "title": "Studio meublé",
        "price": 420,
        "location_raw": "Rangueil, Toulouse 31400",
        "distance_enac_km": 1.4,
        "url": "https://www.seloger.com/annonces/2.htm",
    }

    def test_cross_site_duplicate_found_and_linked(self, temp_db):
        init_db()
        insert_annonce(self.LBC)
        insert_annonce(self.SELOGER)

        dups = find_potential_duplicates(self.SELOGER)
        assert [d["url"] for d in dups] == [self.LBC["url"]]

        assert set_duplicate_of(self.SELOGER["url"], dups[0]["id"]) is True
        assert _row(temp_db, self.SELOGER["url"])["duplicate_of"] == dups[0]["id"]
        # Déjà rattachée : pas de second rattachement
        assert set_duplicate_of(self.SELOGER["url"], dups[0]["id"]) is False

    def test_same_site_is_not_duplicate(self, temp_db):
        init_db()
        insert_annonce(self.LBC)
        other = {**self.LBC, "url": "https://www.leboncoin.fr/locations/3.htm"}
        insert_annonce(other)
        assert find_potential_duplicates(other) == []

    def test_price_outside_tolerance(self, temp_db):
        init_db()
        insert_annonce(self.LBC)
        far = {**self.SELOGER, "price": 470}
        insert_annonce(far)
        assert find_potential_duplicates(far) == []

    def test_surface_mismatch(self, temp_db):
        init_db()
        insert_annonce(self.LBC)
        with sqlite3.connect(temp_db) as con:
            con.execute("UPDATE annonces SET surface_m2 = 18 WHERE url = ?", (self.LBC["url"],))
        assert find_potential_duplicates({**self.SELOGER, "surface_m2": 30}) == []
        assert len(find_potential_duplicates({**self.SELOGER, "surface_m2": 19})) == 1

    # --- Faux doublons Bien'ici (constat réel 2026-11-13) ---

    BIENICI = {
        "site": "Bien'ici", "title": "T2", "price": 808, "location_raw": "Toulouse 31200 (Toulouse)",
        "url": "https://www.bienici.com/annonce/1",
    }
    SL_MINIMES = {
        "site": "SeLoger", "title": "Appartement à louer", "price": 811,
        "location_raw": "Minimes, Toulouse (31200)", "url": "https://www.seloger.com/annonces/9.htm",
    }

    def test_city_and_postcode_alone_are_not_enough(self, temp_db):
        init_db()
        insert_annonce(self.SL_MINIMES)
        assert find_potential_duplicates(self.BIENICI) == []

    def test_same_district_still_matches(self, temp_db):
        init_db()
        insert_annonce(self.SL_MINIMES)
        lbc = {**self.BIENICI, "site": "LeBonCoin", "location_raw": "Toulouse 31200 Minimes",
               "url": "https://www.leboncoin.fr/ad/locations/1"}
        assert len(find_potential_duplicates(lbc)) == 1

    def test_location_words_split_hyphens_and_ignore_generic(self):
        from storage.sqlite import _location_words
        assert _location_words("Toulouse 31300 (Toulouse - Saint-Martin du Touch)") == \
            _location_words("Saint-Martin-du-Touch, Toulouse (31300)") == {"toulouse", "martin", "touch"}
        # « Saint-… » et « Grand … » seuls ne font pas un quartier commun
        assert _location_words("Toulouse Saint-Cyprien") & _location_words("Toulouse Saint-Agne") == {"toulouse"}
        assert _location_words("Toulouse Grand Selve") & _location_words("Toulouse Grand Noble") == {"toulouse"}
        assert _location_words("Toulouse 31200 Croix Bénite") & _location_words("Croix-daurade, Toulouse") == {"toulouse"}

    def test_room_count_mismatch(self, temp_db):
        init_db()
        insert_annonce(self.LBC)
        with sqlite3.connect(temp_db) as con:
            con.execute("UPDATE annonces SET nb_rooms = 3 WHERE url = ?", (self.LBC["url"],))
        assert find_potential_duplicates({**self.SELOGER, "nb_rooms": 2}) == []
        assert len(find_potential_duplicates({**self.SELOGER, "nb_rooms": 3})) == 1

    def test_exact_gps_decides_location(self, temp_db):
        init_db()
        insert_annonce(self.SL_MINIMES)
        with sqlite3.connect(temp_db) as con:
            con.execute("UPDATE annonces SET lat = 43.6207, lon = 1.4490, geo_precision = 'exact' WHERE url = ?",
                        (self.SL_MINIMES["url"],))
        near = {**self.BIENICI, "lat": 43.6215, "lon": 1.4490, "geo_precision": "exact"}    # ~90 m
        far = {**self.BIENICI, "lat": 43.6379, "lon": 1.4490, "geo_precision": "exact"}     # ~1,9 km
        same_words_far = {**far, "location_raw": "Toulouse 31200 Minimes"}
        assert len(find_potential_duplicates(near)) == 1          # GPS suffit, sans mots communs
        assert find_potential_duplicates(far) == []
        assert find_potential_duplicates(same_words_far) == []    # GPS exact prime sur les mots
        approx = {**near, "geo_precision": "approx"}               # position floue : mots requis
        assert find_potential_duplicates(approx) == []

    def test_recheck_detaches_false_duplicates_but_keeps_photo_links(self, temp_db):
        from storage.sqlite import recheck_duplicates
        init_db()
        insert_annonce(self.SL_MINIMES)
        insert_annonce(self.BIENICI)
        photo_dup = {**self.BIENICI, "url": "https://www.bienici.com/annonce/2"}
        insert_annonce(photo_dup)
        with sqlite3.connect(temp_db) as con:
            root_id = con.execute("SELECT id FROM annonces WHERE url = ?", (self.SL_MINIMES["url"],)).fetchone()[0]
            con.execute("UPDATE annonces SET duplicate_of = ? WHERE site = 'Bien''ici'", (root_id,))
            con.execute("UPDATE annonces SET photo_hash = 'f0e1d2c3b4a59687' WHERE url IN (?, ?)",
                        (self.SL_MINIMES["url"], photo_dup["url"]))

        invalid = recheck_duplicates(apply=False)
        assert [r["url"] for r in invalid] == [self.BIENICI["url"]]
        assert _row(temp_db, self.BIENICI["url"])["duplicate_of"] == root_id      # simulation : rien d'écrit

        recheck_duplicates(apply=True)
        assert _row(temp_db, self.BIENICI["url"])["duplicate_of"] is None
        assert _row(temp_db, photo_dup["url"])["duplicate_of"] == root_id         # lien photo conservé

    def test_newer_annonce_cannot_be_original(self, temp_db):
        init_db()
        insert_annonce(self.LBC)
        insert_annonce(self.SELOGER)
        newer_id = _row(temp_db, self.SELOGER["url"])["id"]
        assert set_duplicate_of(self.LBC["url"], newer_id) is False


def test_delete_expired_annonces(temp_db):
    """Annonces retirées des sites : supprimées avec leurs lignes liées ; masquées et actives gardées."""
    import sqlite3
    from storage.sqlite import delete_expired_annonces, init_db, insert_annonce, upsert_annonce_profile

    init_db()
    for i in range(1, 5):
        url = f"https://www.seloger.com/annonce/{i}"
        insert_annonce({"site": "SeLoger", "title": f"A{i}", "price": 600, "location_raw": "Toulouse", "url": url})
        upsert_annonce_profile(url, "blagnac", 3.0)
    con = sqlite3.connect(temp_db)
    con.execute("UPDATE annonces SET status = 'expired' WHERE id IN (1, 2)")
    con.execute("UPDATE annonces SET status = 'hidden' WHERE id = 3")
    con.execute("UPDATE annonces SET duplicate_of = 1 WHERE id = 4")      # doublon d'une retirée
    con.execute("INSERT INTO annonce_feedback (annonce_id, profile, feedback) VALUES (1, 'blagnac', 'favorite')")
    con.commit()

    assert delete_expired_annonces() == 2
    assert [r[0] for r in con.execute("SELECT id FROM annonces ORDER BY id")] == [3, 4]
    assert con.execute("SELECT duplicate_of FROM annonces WHERE id = 4").fetchone() == (None,)
    for table in ("annonce_profiles", "price_history", "annonce_feedback"):
        assert con.execute(f"SELECT COUNT(*) FROM {table} WHERE annonce_id IN (1, 2)").fetchone() == (0,)
    assert delete_expired_annonces() == 0
    con.close()


# ---- Sprint 16.2 — annonces dont la fiche est ouverte pendant le scraping ----

class TestAnnoncesToOpen:
    SITES = ["LeBonCoin", "SeLoger"]

    def _add(self, db, url, site="LeBonCoin", score=50, profile="enac", **cols):
        import sqlite3
        from storage.sqlite import insert_annonce, upsert_annonce_profile
        insert_annonce({"site": site, "title": "Studio", "price": 450, "location_raw": "Rangueil", "url": url})
        upsert_annonce_profile(url, profile, 1.0)
        with sqlite3.connect(db) as con:
            con.execute("UPDATE annonce_profiles SET score = ? WHERE annonce_id = "
                        "(SELECT id FROM annonces WHERE url = ?)", (score, url))
            if cols:
                sets = ", ".join(f"{k} = ?" for k in cols)
                con.execute(f"UPDATE annonces SET {sets} WHERE url = ?", (*cols.values(), url))

    def _exclude(self, db, url, profile="enac"):
        import sqlite3
        with sqlite3.connect(db) as con:
            con.execute("UPDATE annonce_profiles SET excluded_reasons = '[\"DPE G\"]' WHERE profile = ? "
                        "AND annonce_id = (SELECT id FROM annonces WHERE url = ?)", (profile, url))

    def _id(self, db, url):
        import sqlite3
        with sqlite3.connect(db) as con:
            return con.execute("SELECT id FROM annonces WHERE url = ?", (url,)).fetchone()[0]

    def test_exclusion_rules(self, temp_db):
        from datetime import datetime, timedelta
        from storage.feedback import set_feedback
        from storage.sqlite import get_annonces_to_open, init_db, set_duplicate_of
        init_db()
        old = (datetime.now() - timedelta(hours=30)).isoformat()
        self._add(temp_db, "https://x/ok")
        self._add(temp_db, "https://x/orig")
        self._add(temp_db, "https://x/dup")
        set_duplicate_of("https://x/dup", self._id(temp_db, "https://x/orig"))
        self._add(temp_db, "https://x/hidden", status="hidden")
        self._add(temp_db, "https://x/expired", status="expired")
        self._add(temp_db, "https://x/done", enrichment_status="done")
        self._add(temp_db, "https://x/err", enrichment_status="error", enrichment_attempts=1, enriched_at=old)
        self._add(temp_db, "https://x/err_recent", enrichment_status="error", enrichment_attempts=1,
                  enriched_at=datetime.now().isoformat())
        self._add(temp_db, "https://x/bienici", site="Bien'ici")
        self._add(temp_db, "https://x/excluded")
        self._exclude(temp_db, "https://x/excluded")
        # exclue d'un profil seulement : toujours utile pour l'autre
        self._add(temp_db, "https://x/half")
        self._add(temp_db, "https://x/half", profile="blagnac")
        self._exclude(temp_db, "https://x/half")
        # exclue mais favorite ⭐ : ouverte quand même
        self._add(temp_db, "https://x/fav")
        self._exclude(temp_db, "https://x/fav")
        set_feedback(self._id(temp_db, "https://x/fav"), "enac", "favorite")

        urls = {a["url"] for a in get_annonces_to_open([], 50, self.SITES)}
        assert urls == {"https://x/ok", "https://x/orig", "https://x/err", "https://x/half", "https://x/fav"}

    def test_order_run_first_then_score_then_stock(self, temp_db):
        from storage.sqlite import get_annonces_to_open, init_db
        init_db()
        self._add(temp_db, "https://x/stock_high", score=95)
        self._add(temp_db, "https://x/run_low", score=40)
        self._add(temp_db, "https://x/run_high", score=80)
        self._add(temp_db, "https://x/stock_low", score=20)
        run = ["https://x/run_low", "https://x/run_high"]
        rows = get_annonces_to_open(run, 10, self.SITES)
        assert [a["url"] for a in rows] == [
            "https://x/run_high", "https://x/run_low", "https://x/stock_high", "https://x/stock_low"]
        assert [a["in_run"] for a in rows] == [1, 1, 0, 0]
        assert [a["url"] for a in get_annonces_to_open(run, 1, self.SITES)] == ["https://x/run_high"]

    def test_site_filter(self, temp_db):
        from storage.sqlite import get_annonces_to_open, init_db
        init_db()
        self._add(temp_db, "https://x/lbc")
        self._add(temp_db, "https://x/sl", site="SeLoger")
        assert [a["url"] for a in get_annonces_to_open([], 10, ["SeLoger"])] == ["https://x/sl"]
        assert get_annonces_to_open([], 10, []) == []
