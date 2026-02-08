# utils/logger.py
# =========================
# Système de logging avec rotation
# =========================

import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from config import LOG_DIR, LOG_LEVEL


def setup_logger(name: str) -> logging.Logger:
    """
    Configure un logger avec rotation de fichiers.
    
    Args:
        name: Nom du logger (ex: 'scraper', 'main')
    
    Returns:
        Logger configuré
    """
    LOG_DIR.mkdir(exist_ok=True, parents=True)
    
    logger = logging.getLogger(name)
    
    # Éviter les doublons de handlers
    if logger.handlers:
        return logger
    
    logger.setLevel(LOG_LEVEL)
    
    # Handler fichier avec rotation (10MB max, 5 fichiers)
    file_handler = RotatingFileHandler(
        LOG_DIR / f"{name}.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    # Handler console (plus concis)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(logging.Formatter(
        '%(levelname)s - %(message)s'
    ))
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
