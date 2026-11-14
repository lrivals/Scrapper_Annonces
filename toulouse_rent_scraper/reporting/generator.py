# reporting/generator.py
# =========================
# Rapports Markdown par profil (Sprint 5), dans reports/<profil>/ :
#   top10.md               — les 10 meilleures annonces, une ligne chacune (5.6)
#   nouvelles_annonces.md  — fiches des annonces trouvées par ce run, triées par score (5.1)
#   rapport_comparatif.md  — nouvelles, retirées, baisses de prix, évolution du marché (5.3)
#   rapport_quartiers.md   — loyers et scores par commune / quartier (5.4)
#   toutes_les_annonces.md — tableau de toutes les annonces visibles
#   annonces_detaillees.md — fiches de toutes les annonces dont la page a été lue
# Option PDF (5.5) : reporting/pdf.py.
# Annonces prises en compte : actives, rattachées au profil, non exclues par ses critères,
# hors doublons d'un autre site.
# =========================

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Dict, List, Optional, Sequence

from config import SearchProfile, enabled_profiles
from geo.quartier_parser import parse_location, quartier_key
from scoring import price_per_m2, rent_cc
from utils.formatting import km_label
from utils.logger import setup_logger
import storage.sqlite

REPORTS_DIR = storage.sqlite.DB_PATH.parent.parent / "reports"
logger = setup_logger("reporting")

DESCRIPTION_CHARS = 150
TOP_N = 10
QUARTIER_MIN_ANNONCES = 2    # en dessous, le quartier est compté avec sa commune seulement

SITE_PUBLISHER = {"individual": "particulier", "agency": "agence"}


# --- Petits formats ---

def score_badge(score: Optional[float]) -> str:
    """« ⭐ 85 », « ✅ 64 », « ⚠️ 45 », « ❌ 30 », « — » si le score est inconnu."""
    if score is None:
        return "—"
    value = round(score)
    emoji = "⭐" if value >= 80 else "✅" if value >= 60 else "⚠️" if value >= 40 else "❌"
    return f"{emoji} {value}"


def _eur(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{round(value):,} €".replace(",", " ")


def _num(value: float, digits: int = 1) -> str:
    """46.73 → « 46,7 » ; 31.0 → « 31 »."""
    text = f"{round(value, digits):,.{digits}f}".replace(",", " ").replace(".", ",")
    return text.rstrip("0").rstrip(",") if "," in text else text


def _m2(value: Optional[float]) -> str:
    return f"{_num(value)} m²" if value else "—"


def _km(ad: Dict) -> str:
    return km_label(ad.get("distance_km"), ad.get("geo_precision")) or "—"


def _rent(ad: Dict) -> Optional[int]:
    return rent_cc(ad.get("price"), ad.get("charges"), ad.get("charges_included"))


def _ppm2(ad: Dict) -> Optional[float]:
    return price_per_m2(_rent(ad), ad.get("surface_m2"))


def _first_photo(ad: Dict) -> Optional[str]:
    photos = ad.get("photos")
    if isinstance(photos, str):
        try:
            photos = json.loads(photos)
        except ValueError:
            photos = [photos] if photos.startswith("http") else []
    for photo in photos or []:
        if isinstance(photo, str) and photo.startswith("http"):
            return photo
    return None


def _short(text: Optional[str], limit: int = DESCRIPTION_CHARS) -> Optional[str]:
    if not text:
        return None
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def _cell(text) -> str:
    """Texte sûr dans une cellule de tableau Markdown."""
    return str(text).replace("|", "/").replace("\n", " ").strip()


def _by_score(ads: Sequence[Dict]) -> List[Dict]:
    return sorted(ads, key=lambda a: (-(a.get("score") or 0), _rent(a) or 0))


def _date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)[:10]


def _write(path: Path, lines: List[str]) -> Path:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    logger.info(f"Rapport créé : {path}")
    return path


# --- 5.1 Fiche d'une annonce ---

def annonce_card(ad: Dict, label: str) -> List[str]:
    """Fiche Markdown : titre + score, tableau des critères, description courte, photo, lien."""
    lines = [f"## {_cell(ad.get('title') or 'Annonce')} — {score_badge(ad.get('score'))}", ""]
    rows = []
    rent = _rent(ad)
    if rent is not None:
        detail = " CC"
        if not ad.get("charges_included") and ad.get("charges"):
            detail += f" (dont {ad['charges']} € de charges)"
        rows.append(("Loyer", _eur(rent) + detail))
    if ad.get("surface_m2"):
        surface = _m2(ad["surface_m2"])
        ppm2 = _ppm2(ad)
        if ppm2:
            surface += f" ({_num(ppm2)} €/m²)"
        rows.append(("Surface", surface))
    if ad.get("nb_rooms"):
        rooms = str(ad["nb_rooms"])
        if ad.get("nb_bedrooms"):
            rooms += f" ({ad['nb_bedrooms']} ch.)"
        rows.append(("Pièces", rooms))
    if ad.get("distance_km") is not None:
        rows.append((f"Distance {label}", _km(ad)))
    location = parse_location(ad.get("location_raw"))
    if location.commune:
        rows.append(("Lieu", location.label))
    if ad.get("furnished") is not None:
        rows.append(("Meublé", "Oui" if ad["furnished"] else "Non"))
    if ad.get("dpe_rating"):
        rows.append(("DPE", ad["dpe_rating"]))
    if ad.get("deposit"):
        rows.append(("Dépôt", _eur(ad["deposit"])))
    source = ad.get("site") or "?"
    if ad.get("publisher_type") in SITE_PUBLISHER:
        source += f" ({SITE_PUBLISHER[ad['publisher_type']]})"
    rows.append(("Source", source))
    published = _date(ad.get("published_at")) or _date(ad.get("created_at"))
    if published:
        rows.append(("Publié le" if ad.get("published_at") else "Vu le", published))

    lines += ["| Critère | Détail |", "|---|---|"]
    lines += [f"| {k} | {_cell(v)} |" for k, v in rows]
    lines.append("")
    description = _short(ad.get("description"))
    if description:
        lines += [f"> {description}", ""]
    photo = _first_photo(ad)
    if photo:
        lines += [f"![photo]({photo})", ""]
    lines += [f"[Voir l'annonce]({ad['url']})", "", "---", ""]
    return lines


def _new_ads_report(new: List[Dict], out_dir: Path, profile: SearchProfile) -> Path:
    lines = [f"# 🚀 Nouvelles annonces — {profile.label} ({datetime.now():%d/%m/%Y %H:%M})", ""]
    if not new:
        lines.append("Aucune nouvelle annonce lors de ce run.")
    else:
        lines += [f"**{len(new)}** nouvelle(s) annonce(s), meilleur score en premier.", ""]
        for ad in _by_score(new):
            lines += annonce_card(ad, profile.label)
    return _write(out_dir / "nouvelles_annonces.md", lines)


def _detailed_report(ads: List[Dict], out_dir: Path, profile: SearchProfile) -> Path:
    enriched = [a for a in ads if a.get("enrichment_status") == "done"]
    lines = [f"# 🔍 Annonces détaillées — {profile.label} ({datetime.now():%d/%m/%Y %H:%M})", ""]
    if not enriched:
        lines.append("Aucune annonce dont la fiche a été lue.")
    else:
        lines += [f"**{len(enriched)}** annonce(s) dont la fiche a été lue, meilleur score en premier.", ""]
        for ad in _by_score(enriched):
            lines += annonce_card(ad, profile.label)
    return _write(out_dir / "annonces_detaillees.md", lines)


def _all_ads_report(ads: List[Dict], out_dir: Path, profile: SearchProfile) -> Path:
    lines = [f"# 📚 Toutes les annonces — {profile.label}", ""]
    if not ads:
        lines.append("Aucune annonce pour ce profil.")
        return _write(out_dir / "toutes_les_annonces.md", lines)
    lines += [
        f"**{len(ads)}** annonce(s), meilleur score en premier.", "",
        f"| Score | Loyer CC | Surface | Pièces | DPE | {profile.label} | Lieu | Titre | Vu le | Lien |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for ad in _by_score(ads):
        title = ad.get("title") or ""
        title = title[:40].strip() + "…" if len(title) > 40 else title.strip()
        surface = _m2(ad.get("surface_m2"))
        lines.append(
            f"| {score_badge(ad.get('score'))} | {_eur(_rent(ad))} "
            f"| {surface} "
            f"| {ad.get('nb_rooms') or '—'} | {ad.get('dpe_rating') or '—'} | {_km(ad)} "
            f"| {_cell(parse_location(ad.get('location_raw')).label)} | {_cell(title)} "
            f"| {_date(ad.get('created_at')) or '—'} | [lien]({ad['url']}) |"
        )
    return _write(out_dir / "toutes_les_annonces.md", lines)


# --- 5.6 Top 10 ---

def top10_lines(ads: Sequence[Dict], n: int = TOP_N) -> List[str]:
    """« 1. ⭐ 92 | 690 € CC | 38 m² | T2 | 5,2 km | Toulouse — Lalande | [lien](…) »."""
    lines = []
    for i, ad in enumerate(_by_score(ads)[:n], start=1):
        parts = [score_badge(ad.get("score")), f"{_eur(_rent(ad))} CC"]
        if ad.get("surface_m2"):
            parts.append(_m2(ad["surface_m2"]))
        if ad.get("nb_rooms"):
            parts.append(f"T{ad['nb_rooms']}")
        parts += [_km(ad), parse_location(ad.get("location_raw")).label]
        lines.append(f"{i}. " + " | ".join(_cell(p) for p in parts) + f" | [lien]({ad['url']})")
    return lines


def market_line(ads: Sequence[Dict], new_today: int) -> str:
    rents = [r for r in (_rent(a) for a in ads) if r]
    median_rent = _eur(median(rents)) if rents else "—"
    return (f"📊 {len(ads)} annonce(s) | Loyer CC médian : {median_rent} | "
            f"Nouvelles aujourd'hui : {new_today}")


def _new_today(ads: Sequence[Dict]) -> int:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return sum(1 for a in ads if (a.get("matched_at") or "") >= today)


def _top10_report(ads: List[Dict], out_dir: Path, profile: SearchProfile) -> Path:
    lines = [f"# 🏆 Top 10 — {profile.label} ({datetime.now():%d/%m/%Y})", ""]
    lines += top10_lines(ads) or ["Aucune annonce pour ce profil."]
    lines += ["", market_line(ads, _new_today(ads))]
    return _write(out_dir / "top10.md", lines)


# --- 5.3 Rapport comparatif ---

def comparison_since(profile_key: str, now: Optional[datetime] = None) -> Dict:
    """
    Période comparée : depuis la fin de l'avant-dernier run journalisé (le dernier run est
    celui qu'on vient de faire), sinon depuis le début du seul run connu, sinon 24 h.
    Retourne {"since": iso, "current": run|None, "previous": run|None}.
    """
    from storage.run_stats import last_runs

    runs = last_runs(profile_key, 2)
    current = runs[0] if runs else None
    previous = runs[1] if len(runs) > 1 else None
    if previous:
        since = previous["finished_at"]
    elif current:
        since = current["started_at"]
    else:
        since = ((now or datetime.now()) - timedelta(days=1)).isoformat()
    return {"since": since, "current": current, "previous": previous}


def _gone_since(conn, profile_key: str, since: str) -> List[Dict]:
    return [dict(r) for r in conn.execute(
        """SELECT a.*, ap.score AS score, ap.distance_km AS distance_km
           FROM annonces a JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?
           WHERE a.status = 'expired' AND a.expired_at >= ? AND a.duplicate_of IS NULL
           ORDER BY ap.score DESC""",
        (profile_key, since[:19]),
    ).fetchall()]


def price_drops(conn, ads: Sequence[Dict], since: str) -> List[Dict]:
    """Annonces dont le loyer a baissé depuis `since` : {**annonce, old_price}, plus forte baisse d'abord."""
    by_id = {a["id"]: a for a in ads}
    if not by_id:
        return []
    marks = ",".join("?" * len(by_id))
    changed = {r[0] for r in conn.execute(
        f"SELECT DISTINCT annonce_id FROM price_history WHERE seen_at >= ? AND annonce_id IN ({marks})",
        (since, *by_id),
    )}
    drops = []
    for annonce_id in changed:
        before = conn.execute(
            "SELECT price FROM price_history WHERE annonce_id = ? AND seen_at < ? "
            "ORDER BY seen_at DESC, id DESC LIMIT 1",
            (annonce_id, since),
        ).fetchone()
        ad = by_id[annonce_id]
        if before and ad.get("price") is not None and ad["price"] < before[0]:
            drops.append({**ad, "old_price": before[0]})
    return sorted(drops, key=lambda a: a["price"] - a["old_price"])


def _delta(new, old, unit: str = "", digits: int = 0) -> str:
    """« 817 € (−12 €) » par rapport au run précédent ; « — » si inconnu."""
    if new is None:
        return "—"
    text = _num(new, digits) + unit
    if old is None:
        return text
    diff = new - old
    sign = "+" if diff > 0 else "−" if diff < 0 else "±"
    return text + f" ({sign}{_num(abs(diff), digits)}{unit})"


def new_sectors(new: Sequence[Dict], older: Sequence[Dict]) -> List[str]:
    """Communes, puis quartiers, absents des annonces plus anciennes (une annonce sans quartier
    n'apporte que sa commune)."""
    def place(ad):
        loc = parse_location(ad.get("location_raw"))
        return loc, (quartier_key(loc.quartier) if loc.quartier else None)

    known_communes, known_quartiers = set(), set()
    for ad in older:
        loc, key = place(ad)
        known_communes.add(loc.commune)
        known_quartiers.add((loc.commune, key))
    found = set()
    for ad in new:
        loc, key = place(ad)
        if not loc.commune:
            continue
        if loc.commune not in known_communes:
            found.add(loc.commune)
        elif key and (loc.commune, key) not in known_quartiers:
            found.add(loc.label)
    return sorted(found)


def _comparison_report(conn, ads: List[Dict], out_dir: Path, profile: SearchProfile) -> Path:
    from storage.run_stats import snapshot

    period = comparison_since(profile.key)
    since = period["since"]
    new = [a for a in ads if (a.get("matched_at") or "") >= since[:19]]
    gone = _gone_since(conn, profile.key, since)
    drops = price_drops(conn, ads, since)
    now_snap = snapshot(ads)
    prev = period["previous"]

    lines = [
        f"# 🔄 Rapport comparatif — {profile.label} ({datetime.now():%d/%m/%Y %H:%M})", "",
        f"Depuis le {datetime.fromisoformat(since[:19]):%d/%m/%Y à %H:%M}"
        + (" (run précédent)" if prev else " (pas de run précédent journalisé)") + ".", "",
        f"- **{len(new)}** nouvelle(s), **{len(gone)}** retirée(s), **{len(drops)}** baisse(s) de prix",
        f"- Annonces visibles : {_delta(now_snap['active_count'], prev and prev['active_count'])}",
        f"- Loyer CC médian : {_delta(now_snap['median_rent_cc'], prev and prev['median_rent_cc'], ' €')}",
        f"- €/m² médian : {_delta(now_snap['median_ppm2'], prev and prev['median_ppm2'], ' €', 1)}",
    ]
    new_places = new_sectors(new, [a for a in ads if (a.get("matched_at") or "") < since[:19]])
    if new_places:
        lines.append(f"- Nouveau(x) secteur(s) : {', '.join(new_places)}")

    lines += ["", f"## ✨ Nouvelles ({len(new)})", ""]
    lines += top10_lines(new, n=len(new)) or ["Aucune."]
    lines += ["", f"## 📉 Baisses de prix ({len(drops)})", ""]
    lines += [
        f"- {score_badge(a.get('score'))} {_cell(a.get('title') or 'Annonce')} : "
        f"{_eur(a['old_price'])} → **{_eur(a['price'])}** ({a['price'] - a['old_price']} €) "
        f"— [lien]({a['url']})"
        for a in drops
    ] or ["Aucune."]
    lines += ["", f"## 🗑️ Retirées ({len(gone)})", ""]
    lines += [
        f"- {score_badge(a.get('score'))} {_cell(a.get('title') or 'Annonce')} — "
        f"{_eur(_rent(a))} CC, {_cell(parse_location(a.get('location_raw')).label)}"
        for a in gone
    ] or ["Aucune."]
    return _write(out_dir / "rapport_comparatif.md", lines)


# --- 5.4 Rapport par quartier ---

def group_by_quartier(ads: Sequence[Dict]) -> Dict[tuple, List[Dict]]:
    """{(commune, clé du quartier | None): annonces}."""
    groups = defaultdict(list)
    for ad in ads:
        loc = parse_location(ad.get("location_raw"))
        groups[(loc.commune or "Inconnu", quartier_key(loc.quartier) if loc.quartier else None)].append(ad)
    return groups


def area_stats(ads: Sequence[Dict]) -> Dict:
    rents = [r for r in (_rent(a) for a in ads) if r]
    ppm2 = [v for v in (_ppm2(a) for a in ads) if v]
    distances = [a["distance_km"] for a in ads if a.get("distance_km") is not None]
    scores = [a["score"] for a in ads if a.get("score") is not None]
    return {
        "count": len(ads),
        "median_rent": median(rents) if rents else None,
        "min_rent": min(rents) if rents else None,
        "max_rent": max(rents) if rents else None,
        "median_ppm2": median(ppm2) if ppm2 else None,
        "mean_distance": mean(distances) if distances else None,
        "median_score": median(scores) if scores else None,
    }


def _quartier_name(ads: Sequence[Dict]) -> str:
    """Écriture la plus fréquente du quartier dans le groupe."""
    names = [parse_location(a.get("location_raw")).quartier for a in ads]
    names = [n for n in names if n]
    # À égalité, ordre alphabétique : le nom affiché ne change pas d'un rapport à l'autre
    return max(sorted(set(names)), key=names.count) if names else "?"


def _stats_row(name: str, s: Dict) -> str:
    ppm2 = f"{s['median_ppm2']:.1f} €".replace(".", ",") if s["median_ppm2"] else "—"
    dist = f"{s['mean_distance']:.1f} km".replace(".", ",") if s["mean_distance"] is not None else "—"
    return (f"| {_cell(name)} | {s['count']} | {score_badge(s['median_score'])} | {_eur(s['median_rent'])} "
            f"| {_eur(s['min_rent'])} – {_eur(s['max_rent'])} | {ppm2} | {dist} |")


_STATS_HEADER = [
    "| Secteur | Annonces | Score médian | Loyer CC médian | Min – max | €/m² médian | Distance moy. |",
    "|---|---|---|---|---|---|---|",
]


def _quartiers_report(ads: List[Dict], out_dir: Path, profile: SearchProfile) -> Path:
    lines = [f"# 🗺️ Rapport par quartier — {profile.label} ({datetime.now():%d/%m/%Y})", ""]
    if not ads:
        lines.append("Aucune annonce pour ce profil.")
        return _write(out_dir / "rapport_quartiers.md", lines)

    by_commune = defaultdict(list)
    for ad in ads:
        by_commune[parse_location(ad.get("location_raw")).commune or "Inconnu"].append(ad)
    lines += ["## Par commune", "", *_STATS_HEADER]
    communes = sorted(by_commune.items(), key=lambda kv: -len(kv[1]))
    lines += [_stats_row(name, area_stats(group)) for name, group in communes]

    quartiers = [
        (commune, _quartier_name(group), group)
        for (commune, key), group in group_by_quartier(ads).items()
        if key and len(group) >= QUARTIER_MIN_ANNONCES
    ]
    # Classement qualité/prix : score médian, puis €/m² le plus bas
    quartiers.sort(key=lambda q: (
        -(area_stats(q[2])["median_score"] or 0), area_stats(q[2])["median_ppm2"] or 1e9,
    ))
    lines += [
        "", f"## Classement des quartiers (au moins {QUARTIER_MIN_ANNONCES} annonces)", "",
        "Meilleur score médian d'abord ; à égalité, €/m² le plus bas. Chaque site découpe les "
        "quartiers à sa façon : un même secteur peut apparaître sous deux noms.", "",
        *_STATS_HEADER,
    ]
    lines += [_stats_row(f"{name} ({commune})", area_stats(group)) for commune, name, group in quartiers]

    lines += ["", "## Top 3 par quartier", ""]
    for commune, name, group in quartiers:
        lines += [f"### {name} ({commune})", "", *top10_lines(group, n=3), ""]
    return _write(out_dir / "rapport_quartiers.md", lines)


# --- Point d'entrée ---

def generate_profile_reports(
    profile: SearchProfile, run_start_time: Optional[datetime] = None, pdf: bool = False,
) -> List[Path]:
    """Écrit les rapports d'un profil ; `run_start_time` délimite les « nouvelles » (défaut : 24 h)."""
    from storage.run_stats import profile_rows

    out_dir = REPORTS_DIR / profile.key
    out_dir.mkdir(parents=True, exist_ok=True)
    since = (run_start_time or datetime.now() - timedelta(days=1)).isoformat()
    with storage.sqlite.connect() as conn:
        ads = profile_rows(conn, profile.key)
        new = [a for a in ads if (a.get("matched_at") or "") >= since]
        paths = [
            _top10_report(ads, out_dir, profile),
            _new_ads_report(new, out_dir, profile),
            _comparison_report(conn, ads, out_dir, profile),
            _quartiers_report(ads, out_dir, profile),
            _all_ads_report(ads, out_dir, profile),
            _detailed_report(ads, out_dir, profile),
        ]
    if pdf:
        from reporting.pdf import markdown_files_to_pdf
        paths += markdown_files_to_pdf(paths[:4], title=f"Annonces — {profile.label}")
    return paths


def generate_summary_reports(
    run_start_time: Optional[datetime] = None,
    profiles: Optional[Sequence[SearchProfile]] = None,
    pdf: bool = False,
) -> Dict[str, List[Path]]:
    """Rapports de chaque profil (défaut : profils actifs). Retourne {profil: fichiers}."""
    written = {}
    try:
        for profile in profiles or enabled_profiles():
            written[profile.key] = generate_profile_reports(profile, run_start_time, pdf=pdf)
    except Exception as e:
        logger.error(f"Erreur lors de la génération des rapports : {e}", exc_info=True)
        raise
    return written
