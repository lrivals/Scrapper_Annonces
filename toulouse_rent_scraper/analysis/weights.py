# analysis/weights.py
# =========================
# Sprint 15.6 — poids du score appris des retours ⭐ / 📞 / 👎.
#
# Régression logistique (pur Python, pas de dépendance) sur les critères 0–1 du score
# (`score_detail`) : P(retour positif) = σ(b + Σ wₖ·xₖ). Les critères étant tous sur la
# même échelle, un coefficient plus grand = un critère qui compte plus pour l'utilisateur.
# Coefficients négatifs ramenés à 0, puis normalisés pour que les poids proposés aient
# la même somme que les poids actuels. Rien n'est appliqué sans confirmation.
# =========================

import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config
from utils.logger import setup_logger

logger = setup_logger("weights")

L2 = 0.05            # régularisation : évite des coefficients extrêmes avec peu de retours
LEARNING_RATE = 0.5
ITERATIONS = 4000


@dataclass
class Proposal:
    ready: bool                         # assez de retours pour proposer des poids
    message: str
    samples: int = 0
    positives: int = 0
    negatives: int = 0
    current: Dict[str, float] = field(default_factory=dict)
    proposed: Dict[str, int] = field(default_factory=dict)
    coefficients: Dict[str, float] = field(default_factory=dict)
    accuracy: Optional[float] = None    # sur les retours eux-mêmes (indicatif)
    baseline: Optional[float] = None    # en répondant toujours la classe majoritaire


# ---------------------------------------------------------------------------
# Poids effectifs (fichier confirmé, sinon config)
# ---------------------------------------------------------------------------

def current_weights() -> Dict[str, float]:
    """Poids confirmés (`data/score_weights.json`) s'ils sont valides, sinon `SCORE_WEIGHTS`."""
    path = config.SCORE_WEIGHTS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(config.SCORE_WEIGHTS)
    except (OSError, ValueError) as e:
        logger.warning(f"Poids appris illisibles ({path.name}) : {e} — poids par défaut utilisés")
        return dict(config.SCORE_WEIGHTS)
    weights = data.get("weights") if isinstance(data, dict) else None
    if not isinstance(weights, dict):
        return dict(config.SCORE_WEIGHTS)
    clean = {k: float(weights[k]) for k in config.SCORE_WEIGHTS
             if isinstance(weights.get(k), (int, float)) and weights[k] >= 0}
    if set(clean) != set(config.SCORE_WEIGHTS) or not sum(clean.values()):
        logger.warning(f"Poids appris incomplets ({path.name}) — poids par défaut utilisés")
        return dict(config.SCORE_WEIGHTS)
    return clean


def weights_source() -> str:
    return "appris (confirmés)" if config.SCORE_WEIGHTS_FILE.exists() else "config.py"


def save_weights(weights: Dict[str, float], samples: int) -> None:
    path = config.SCORE_WEIGHTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    path.write_text(json.dumps({
        "weights": weights,
        "samples": samples,
        "applied_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2), encoding="utf-8")
    logger.info(f"Poids appliqués : {weights} ({samples} retours)")


def reset_weights() -> bool:
    """Revient aux poids de config.py. True si des poids appris existaient."""
    try:
        config.SCORE_WEIGHTS_FILE.unlink()
    except FileNotFoundError:
        return False
    logger.info("Poids appris supprimés : retour aux poids de config.py")
    return True


# ---------------------------------------------------------------------------
# Régression logistique
# ---------------------------------------------------------------------------

def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def fit_logistic(xs: List[List[float]], ys: List[int]) -> (List[float], float):
    """Descente de gradient (log-loss moyenne + L2 sur les coefficients). Retourne (w, b)."""
    n, k = len(xs), len(xs[0])
    w, b = [0.0] * k, 0.0
    for _ in range(ITERATIONS):
        grad_w, grad_b = [0.0] * k, 0.0
        for x, y in zip(xs, ys):
            err = _sigmoid(b + sum(wi * xi for wi, xi in zip(w, x))) - y
            grad_b += err
            for j in range(k):
                grad_w[j] += err * x[j]
        b -= LEARNING_RATE * grad_b / n
        for j in range(k):
            w[j] -= LEARNING_RATE * (grad_w[j] / n + L2 * w[j])
    return w, b


def propose_weights(rows: Optional[List[Dict]] = None) -> Proposal:
    """Poids proposés à partir des retours (lus en base si `rows` est None)."""
    if rows is None:
        from storage.feedback import training_rows
        rows = training_rows()
    current = current_weights()
    keys = list(config.SCORE_WEIGHTS)
    positives = sum(r["label"] for r in rows)
    negatives = len(rows) - positives
    base = Proposal(ready=False, message="", samples=len(rows), positives=positives,
                    negatives=negatives, current=current)

    if len(rows) < config.FEEDBACK_MIN_SAMPLES:
        base.message = (f"{len(rows)} retour(s) sur {config.FEEDBACK_MIN_SAMPLES} nécessaires "
                        f"(⭐ / 📞 = intéressant, 👎 = pas intéressé)")
        return base
    if min(positives, negatives) < config.FEEDBACK_MIN_PER_CLASS:
        missing = "👎" if negatives < positives else "⭐ / 📞"
        base.message = (f"Pas assez de retours {missing} : il en faut au moins "
                        f"{config.FEEDBACK_MIN_PER_CLASS} de chaque sorte "
                        f"({positives} positifs, {negatives} négatifs)")
        return base

    xs = [[float(r["criteria"].get(k, 0.5)) for k in keys] for r in rows]
    ys = [r["label"] for r in rows]
    w, b = fit_logistic(xs, ys)
    base.coefficients = {k: round(v, 3) for k, v in zip(keys, w)}

    predictions = [_sigmoid(b + sum(wi * xi for wi, xi in zip(w, x))) >= 0.5 for x in xs]
    base.accuracy = round(sum(p == bool(y) for p, y in zip(predictions, ys)) / len(ys), 2)
    base.baseline = round(max(positives, negatives) / len(ys), 2)

    clipped = {k: max(v, 0.0) for k, v in zip(keys, w)}
    total = sum(clipped.values())
    if total <= 0:
        base.message = "Aucun critère du score n'explique vos retours : poids actuels conservés"
        return base
    budget = sum(current.values()) or 100
    base.proposed = {k: round(v / total * budget) for k, v in clipped.items()}
    base.ready = True
    base.message = (f"Poids proposés d'après {len(rows)} retours "
                    f"({positives} positifs, {negatives} négatifs)")
    return base


def format_proposal(p: Proposal) -> List[str]:
    """Tableau texte : critère, poids actuel, poids proposé (CLI)."""
    from scoring import LABELS
    lines = [p.message]
    if not p.ready:
        return lines
    lines.append("")
    lines.append(f"{'critère':<18} {'actuel':>7} {'proposé':>8} {'coef.':>7}")
    for k in config.SCORE_WEIGHTS:
        lines.append(f"{LABELS.get(k, k):<18} {p.current.get(k, 0):>7g} {p.proposed.get(k, 0):>8} "
                     f"{p.coefficients.get(k, 0):>7.2f}")
    lines.append("")
    lines.append(f"Concordance avec vos retours : {p.accuracy:.0%} "
                 f"(référence en répondant toujours pareil : {p.baseline:.0%})")
    return lines
