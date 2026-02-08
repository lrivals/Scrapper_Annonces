# utils/validation.py
# =========================
# Validation des données scrapées
# =========================

from typing import Dict, Optional


def validate_annonce(annonce: Dict) -> Optional[str]:
    """
    Valide qu'une annonce contient tous les champs requis.
    
    Args:
        annonce: Dictionnaire représentant une annonce
    
    Returns:
        Message d'erreur si invalide, None si valide
    """
    required_fields = ["site", "title", "price", "location_raw", "url"]
    
    for field in required_fields:
        if field not in annonce:
            return f"Champ manquant: {field}"
        
        # Vérifier que le champ n'est pas vide
        value = annonce[field]
        if value is None or (isinstance(value, str) and not value.strip()):
            return f"Champ vide: {field}"
    
    # Validation spécifique de l'URL
    url = annonce.get("url", "")
    if not url.startswith("http"):
        return f"URL invalide: {url}"
    
    return None  # Validation OK
