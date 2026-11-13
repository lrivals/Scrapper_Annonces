# storage/feedback.py
# =========================
# Sprint 15.6 — retours de l'utilisateur (⭐ favori, 📞 contacté, 👎 pas intéressé),
# par annonce et par profil. Servent à apprendre les poids du score et à suivre
# les favoris (baisse de prix, disparition).
# =========================

import json
from typing import Dict, List, Optional

from storage.sqlite import connect

FEEDBACK_VALUES = ("favorite", "contacted", "dislike")
POSITIVE = ("favorite", "contacted")
LABELS = {"favorite": "favori", "contacted": "contacté", "dislike": "pas intéressé"}


def set_feedback(annonce_id: int, profile: str, value: Optional[str]) -> Optional[Dict]:
    """
    Enregistre le retour (None ou "" = l'efface). Retourne {"title", "feedback"} ou None si
    l'annonce n'existe pas. Le prix du moment est gardé (suivi des favoris).
    """
    if value and value not in FEEDBACK_VALUES:
        raise ValueError(f"Retour inconnu : {value}")
    with connect() as conn:
        row = conn.execute("SELECT title, price FROM annonces WHERE id = ?", (annonce_id,)).fetchone()
        if row is None:
            return None
        if value:
            conn.execute(
                "INSERT INTO annonce_feedback (annonce_id, profile, feedback, price, updated_at) "
                "VALUES (?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(annonce_id, profile) DO UPDATE SET feedback = excluded.feedback, "
                "price = excluded.price, updated_at = excluded.updated_at",
                (annonce_id, profile, value, row["price"]),
            )
        else:
            conn.execute("DELETE FROM annonce_feedback WHERE annonce_id = ? AND profile = ?",
                         (annonce_id, profile))
    return {"title": row["title"] or "Annonce", "feedback": value or None}


def get_feedback(annonce_id: int, profile: str) -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT feedback FROM annonce_feedback WHERE annonce_id = ? AND profile = ?",
                           (annonce_id, profile)).fetchone()
    return row[0] if row else None


def training_rows() -> List[Dict]:
    """
    Retours exploitables pour l'apprentissage : critères du score (0–1) du profil concerné
    et étiquette (1 = ⭐ ou 📞, 0 = 👎). Les annonces sans score sont ignorées.
    """
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT f.feedback, ap.score_detail, f.profile
            FROM annonce_feedback f
            JOIN annonce_profiles ap ON ap.annonce_id = f.annonce_id AND ap.profile = f.profile
            WHERE ap.score_detail IS NOT NULL
            """
        ).fetchall()
    out = []
    for feedback, detail, profile in rows:
        try:
            criteria = json.loads(detail)
        except (TypeError, ValueError):
            continue
        if isinstance(criteria, dict):
            out.append({"label": 1 if feedback in POSITIVE else 0, "criteria": criteria, "profile": profile})
    return out


def feedback_counts() -> Dict[str, int]:
    with connect() as conn:
        rows = conn.execute("SELECT feedback, COUNT(*) FROM annonce_feedback GROUP BY feedback").fetchall()
    counts = {v: 0 for v in FEEDBACK_VALUES}
    counts.update({k: n for k, n in rows})
    return counts


def favorites_by_annonce(annonce_ids: List[int]) -> Dict[int, List[str]]:
    """Profils où chaque annonce est en favori (⭐) — suivi des disparitions."""
    if not annonce_ids:
        return {}
    placeholders = ",".join("?" * len(annonce_ids))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT annonce_id, profile FROM annonce_feedback "
            f"WHERE feedback = 'favorite' AND annonce_id IN ({placeholders})",
            list(annonce_ids),
        ).fetchall()
    out: Dict[int, List[str]] = {}
    for annonce_id, profile in rows:
        out.setdefault(annonce_id, []).append(profile)
    return out
