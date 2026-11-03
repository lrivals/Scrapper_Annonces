# scripts/repair_data.py
# =========================
# Réparation des données existantes après le Sprint 11
# Usage :
#   python scripts/repair_data.py            # simulation (aucune écriture)
#   python scripts/repair_data.py --apply    # sauvegarde la base puis corrige
# =========================

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DB_PATH, MAX_DISTANCE_KM  # noqa: E402
from storage.sqlite import init_db, find_potential_duplicates, set_duplicate_of  # noqa: E402

# Montant ≥ 1000 € écrit avec séparateur de milliers dans une description
_BIG_AMOUNT = re.compile(r"\b\d[   .]\d{3}\s*(?:€|euros?)", re.IGNORECASE)


def _rows(query, params=()):
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(query, params).fetchall()]


def backup_db() -> Path:
    dest = DB_PATH.with_name(f"{DB_PATH.stem}.bak-{datetime.now():%Y%m%d-%H%M%S}{DB_PATH.suffix}")
    shutil.copy2(DB_PATH, dest)
    return dest


def report_suspicious_prices():
    """Le prix brut n'est pas stocké : on signale seulement, une re-collecte est nécessaire."""
    rows = _rows("SELECT id, title, price, url, description FROM annonces WHERE description IS NOT NULL")
    suspects = [r for r in rows if _BIG_AMOUNT.search(r["description"] or "")]
    print(f"\n[1] Prix potentiellement mal parsés (montant ≥ 1000 € dans la description) : {len(suspects)}")
    for r in suspects:
        print(f"    #{r['id']} {r['price']}€ — {(r['title'] or '')[:50]} — {r['url']}")


def regeocode(apply: bool):
    """
    Re-géocode les adresses citant une commune ou un code postal (requête
    historiquement suffixée par « Toulouse ») et met à jour distance_enac_km.
    """
    from geo.distance import _mentions_commune, distance_from_enac_km

    cached = _rows("SELECT address FROM geocoding_cache")
    targets = [
        r["address"] for r in cached
        if _mentions_commune(r["address"]) and "toulouse" not in r["address"].lower()
    ]
    print(f"\n[2] Adresses à re-géocoder (commune hors Toulouse) : {len(targets)}")
    if not apply:
        for a in targets:
            print(f"    {a}")
        return

    for address in targets:
        before = _rows(
            "SELECT id, distance_enac_km FROM annonces WHERE location_raw = ?", (address,)
        )
        with sqlite3.connect(DB_PATH) as con:
            con.execute("DELETE FROM geocoding_cache WHERE address = ?", (address,))
        dist = distance_from_enac_km(address)
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                "UPDATE annonces SET distance_enac_km = ? WHERE location_raw = ?", (dist, address)
            )
        old = before[0]["distance_enac_km"] if before else None
        flag = "  ⚠ hors rayon" if dist is not None and dist > MAX_DISTANCE_KM else ""
        print(f"    {address} : {old} → {dist} km ({len(before)} annonce(s)){flag}")


def link_duplicates(apply: bool):
    rows = _rows("SELECT * FROM annonces WHERE duplicate_of IS NULL ORDER BY id ASC")
    found = 0
    print("\n[3] Doublons inter-sites")
    for r in rows:
        dups = [d for d in find_potential_duplicates(r) if d["id"] < r["id"]]
        if not dups:
            continue
        original = dups[0]
        found += 1
        print(f"    #{r['id']} {r['site']} {r['price']}€ ↔ #{original['id']} {original['site']} {original['price']}€")
        if apply:
            set_duplicate_of(r["url"], original["id"])
    print(f"    Total : {found}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Écrire les corrections (sinon simulation)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Base introuvable : {DB_PATH}")
        return

    init_db()  # migrations (colonne duplicate_of)
    if args.apply:
        print(f"Sauvegarde : {backup_db()}")
    else:
        print("Mode simulation — relancer avec --apply pour écrire.")

    report_suspicious_prices()
    regeocode(args.apply)
    link_duplicates(args.apply)


if __name__ == "__main__":
    main()
