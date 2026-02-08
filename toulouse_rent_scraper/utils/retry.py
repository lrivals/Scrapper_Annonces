# utils/retry.py
# =========================
# Retry avec backoff exponentiel
# =========================

import time
from functools import wraps
from typing import Callable, TypeVar, Tuple, Type

T = TypeVar('T')


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Décorateur pour retry automatique avec backoff exponentiel.
    
    Args:
        max_attempts: Nombre maximum de tentatives
        base_delay: Délai de base en secondes
        exceptions: Tuple des exceptions à intercepter
    
    Example:
        @retry_with_backoff(max_attempts=3, exceptions=(TimeoutError,))
        def fetch_data():
            # code qui peut timeout
            pass
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_attempts - 1:
                        # Dernière tentative échouée, on relance
                        raise
                    
                    # Calcul du délai avec backoff exponentiel
                    delay = base_delay * (2 ** attempt)
                    
                    # Log optionnel (nécessite import logging)
                    try:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(
                            f"Tentative {attempt + 1}/{max_attempts} échouée "
                            f"pour {func.__name__}: {e}. Retry dans {delay}s"
                        )
                    except:
                        pass
                    
                    time.sleep(delay)
            
            # Ne devrait jamais arriver, mais pour la sécurité du typage
            if last_exception:
                raise last_exception
            
        return wrapper
    return decorator
