# geo/quartier_parser.py
# =========================
# Sprint 5.4 — commune, code postal et quartier à partir de `location_raw`.
# Formats rencontrés :
#   SeLoger   « Croix-daurade, Toulouse (31200) », « Toulouse (31000) »
#   PAP       « Blagnac (31700) »
#   Bien'ici  « Toulouse 31200 (Toulouse - Croix Bénite) »
#   LeBonCoin « Toulouse 31200 Croix Bénite », « Toulouse 31400 »
# Chaque site découpe les quartiers à sa façon : le nom est seulement normalisé
# (casse, tirets, abréviations) pour regrouper les variantes d'écriture.
# =========================

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

_CP = r"(\d{5})"
# « Quartier, Ville (CP) » ou « Ville (CP) »
_PAREN_CP = re.compile(rf"^(?:(?P<quartier>.+?),\s*)?(?P<commune>[^,()]+?)\s*\({_CP}\)\s*$")
# « Ville CP (Ville - Quartier) »
_BIENICI = re.compile(rf"^(?P<commune>.+?)\s+{_CP}\s*\((?P<inner>.+)\)\s*$")
# « Ville CP Quartier » ou « Ville CP »
_CP_THEN = re.compile(rf"^(?P<commune>.+?)\s+{_CP}(?:\s+(?P<quartier>.+))?$")

# Abréviations des libellés de quartiers (LeBonCoin surtout)
_ABBREVIATIONS = {"cx": "croix", "st": "saint", "ste": "sainte", "pale": "palé"}
_SMALL_WORDS = {"de", "du", "des", "la", "le", "les", "d", "l", "et", "sur", "en"}


@dataclass(frozen=True)
class Location:
    commune: Optional[str]
    postal_code: Optional[str]
    quartier: Optional[str]

    @property
    def label(self) -> str:
        """« Toulouse — Croix Daurade », « Blagnac », « Inconnu »."""
        if not self.commune:
            return "Inconnu"
        return f"{self.commune} — {self.quartier}" if self.quartier else self.commune


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def quartier_key(name: str) -> str:
    """Clé de regroupement : minuscules, sans accents, tirets → espaces, abréviations dépliées."""
    words = re.split(r"[\s\-–'’.]+", _strip_accents(name.lower()))
    words = [_strip_accents(_ABBREVIATIONS.get(w, w)) for w in words if w]
    # « Les Minimes » = « Minimes »
    if len(words) > 1 and words[0] in ("les", "le", "la"):
        words = words[1:]
    return " ".join(words)


def _title(text: str) -> str:
    """« croix-daurade » → « Croix-Daurade » ; petits mots en minuscules sauf en tête."""
    def fix(word: str, first: bool) -> str:
        parts = word.split("-")
        out = []
        for i, part in enumerate(parts):
            low = part.lower()
            if low in _ABBREVIATIONS:
                low = _ABBREVIATIONS[low]
            if low in _SMALL_WORDS and not (first and i == 0):
                out.append(low)
            elif low[:2] in ("d'", "l'"):
                out.append(low[:2] + low[2:].capitalize())
            else:
                out.append(low[:1].upper() + low[1:])
        return "-".join(out)

    words = text.split()
    return " ".join(fix(w, i == 0) for i, w in enumerate(words))


def _clean_quartier(quartier: Optional[str], commune: str) -> Optional[str]:
    if not quartier:
        return None
    q = quartier.strip(" -,.")
    # « 3 Cocus » = Trois Cocus ; ailleurs, un numéro en tête est celui du secteur LeBonCoin
    q = re.sub(r"^3\s+(?=cocus)", "Trois ", q, flags=re.IGNORECASE)
    q = re.sub(r"^\d+\s+", "", q)
    if not q or quartier_key(q) == quartier_key(commune):
        return None
    return _title(q)


def parse_location(raw: Optional[str]) -> Location:
    """Découpe une adresse d'annonce ; champs inconnus à None."""
    if not raw or not raw.strip():
        return Location(None, None, None)
    text = re.sub(r"\s+", " ", raw.strip())

    m = _BIENICI.match(text)
    if m:
        commune = _title(m.group("commune"))
        inner = m.group("inner")
        # « Toulouse - Croix Bénite » : la partie après la commune
        prefix = re.match(rf"^{re.escape(m.group('commune'))}\s*-\s*(.+)$", inner, re.IGNORECASE)
        quartier = prefix.group(1) if prefix else inner
        return Location(commune, m.group(2), _clean_quartier(quartier, commune))

    m = _PAREN_CP.match(text)
    if m:
        commune = _title(m.group("commune").strip())
        return Location(commune, m.group(3), _clean_quartier(m.group("quartier"), commune))

    m = _CP_THEN.match(text)
    if m:
        commune = _title(m.group("commune").strip())
        return Location(commune, m.group(2), _clean_quartier(m.group("quartier"), commune))

    # Pas de code postal : « Blagnac », « Toulouse Centre »
    return Location(_title(text), None, None)
