# filters/photo_duplicates.py
# =========================
# Sprint 15.8 — doublons inter-sites par empreinte de la première photo.
#
# Le même bien publié sur LeBonCoin, SeLoger et Bien'ici a presque toujours les mêmes
# photos, redimensionnées et recompressées différemment. Une empreinte perceptuelle
# (dHash 64 bits : l'image réduite à 9×8 en niveaux de gris, 1 bit par comparaison de
# pixels voisins) y est insensible ; deux empreintes à ≤ PHOTO_HASH_MAX_DISTANCE bits
# d'écart = même photo. Avec un prix proche et des sites différents → `duplicate_of`.
#
# Complète la détection par prix + mots de la localisation, qui échoue quand les sites
# ne décrivent pas l'adresse de la même façon (« Toulouse » vs « Toulouse 31400 Rangueil »).
# Pillow suffit (pas de numpy/scipy) ; sans Pillow, l'étape est simplement sautée.
# =========================

import io
import json
import time
from collections import Counter
from typing import Dict, List, Optional

import config
from utils.logger import setup_logger

logger = setup_logger("photo_dedup")

HASH_SIZE = 8


# ---------------------------------------------------------------------------
# Empreinte
# ---------------------------------------------------------------------------

def pillow_available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def dhash(image_bytes: bytes) -> str:
    """Empreinte dHash 64 bits (16 caractères hexa). ValueError si l'image est illisible."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.draft("L", (HASH_SIZE * 4, HASH_SIZE * 4))   # décodage JPEG réduit : rapide
            small = img.convert("L").resize((HASH_SIZE + 1, HASH_SIZE), Image.LANCZOS)
            pixels = small.tobytes()   # mode « L » : un octet par pixel
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"image illisible : {e}") from e
    bits = 0
    for row in range(HASH_SIZE):
        offset = row * (HASH_SIZE + 1)
        for col in range(HASH_SIZE):
            bits = (bits << 1) | (pixels[offset + col] > pixels[offset + col + 1])
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def is_uniform(photo_hash: str) -> bool:
    """Image unie ou presque (placeholder gris, image vide) : empreinte sans valeur."""
    ones = bin(int(photo_hash, 16)).count("1")
    return ones <= 2 or ones >= 62


def first_photo(photos) -> Optional[str]:
    """Première URL de la colonne `photos` (JSON [url, …] ou URL seule)."""
    if not photos:
        return None
    if isinstance(photos, str):
        text = photos.strip()
        if text.startswith("["):
            try:
                photos = json.loads(text)
            except ValueError:
                return None
        else:
            return text if text.startswith(("http://", "https://")) else None
    if isinstance(photos, list):
        for url in photos:
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                return url
    return None


# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------

def _session():
    import requests

    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
    return session


def download_image(url: str, session) -> bytes:
    """Télécharge une image (taille plafonnée). ValueError si ce n'est pas une image exploitable."""
    with session.get(url, timeout=15, stream=True) as resp:
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        content_type = resp.headers.get("Content-Type", "")
        if content_type and not content_type.startswith("image/"):
            raise ValueError(f"pas une image ({content_type})")
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            size += len(chunk)
            if size > config.PHOTO_MAX_BYTES:
                raise ValueError("image trop lourde")
            chunks.append(chunk)
    return b"".join(chunks)


def compute_missing_hashes(limit: Optional[int] = None, session=None, sleep=time.sleep) -> Dict[str, int]:
    """
    Calcule l'empreinte de la 1ʳᵉ photo des annonces actives qui n'en ont pas encore
    (des plus récentes aux plus anciennes). Un échec est retenté au run suivant, jusqu'à
    PHOTO_HASH_MAX_ATTEMPTS fois.
    """
    from storage.sqlite import annonces_without_photo_hash, save_photo_hash

    limit = config.PHOTO_HASH_MAX_PER_RUN if limit is None else limit
    rows = annonces_without_photo_hash(config.PHOTO_HASH_MAX_ATTEMPTS, limit)
    stats = {"hashed": 0, "failed": 0}
    if not rows:
        return stats
    session = session or _session()
    for idx, row in enumerate(rows):
        url = first_photo(row.get("photos"))
        if not url:
            continue
        if idx:
            sleep(config.PHOTO_HASH_DELAY)
        try:
            save_photo_hash(row["id"], dhash(download_image(url, session)))
            stats["hashed"] += 1
        except Exception as e:   # réseau, image illisible… : jamais bloquant
            save_photo_hash(row["id"], None)
            stats["failed"] += 1
            logger.debug(f"Empreinte impossible pour l'annonce {row['id']} ({url[:80]}) : {e}")
    return stats


# ---------------------------------------------------------------------------
# Rapprochement
# ---------------------------------------------------------------------------

def find_photo_duplicates(rows: List[Dict]) -> List[Dict]:
    """
    Couples (annonce récente → annonce d'origine) à rattacher. `rows` : annonces avec
    id, url, site, price, photo_hash, duplicate_of, root_site (site de l'origine si
    l'annonce est déjà un doublon). Règles :
      - sites différents, empreintes à ≤ PHOTO_HASH_MAX_DISTANCE bits, prix à
        ±PHOTO_DUP_PRICE_TOLERANCE € ;
      - photo générique ignorée (même empreinte sur > PHOTO_GENERIC_MAX_SAME_SITE annonces
        d'un même site, ou image unie) ;
      - l'annonce rattachée n'est pas déjà un doublon ; elle est rattachée à la RACINE de
        l'annonce qui lui ressemble (jamais de chaîne de doublons), plus ancienne qu'elle.
    """
    per_site = Counter((r["site"], r["photo_hash"]) for r in rows)
    generic = {h for (_, h), n in per_site.items() if n > config.PHOTO_GENERIC_MAX_SAME_SITE}
    usable = sorted(
        (r for r in rows if r["photo_hash"] not in generic and not is_uniform(r["photo_hash"])
         and r.get("price") is not None),
        key=lambda r: r["id"],
    )
    # Racine de chaque annonce : en base, ou rattachement décidé plus tôt dans cette passe
    roots = {r["id"]: (r["duplicate_of"], r.get("root_site") or r["site"]) if r.get("duplicate_of")
             else (r["id"], r["site"]) for r in usable}

    links = []
    for i, newer in enumerate(usable):
        if newer.get("duplicate_of") is not None:
            continue
        for older in usable[:i]:
            origin_id, origin_site = roots[older["id"]]
            if newer["site"] in (older["site"], origin_site) or origin_id >= newer["id"]:
                continue
            if abs(older["price"] - newer["price"]) > config.PHOTO_DUP_PRICE_TOLERANCE:
                continue
            distance = hamming(older["photo_hash"], newer["photo_hash"])
            if distance > config.PHOTO_HASH_MAX_DISTANCE:
                continue
            links.append({"id": newer["id"], "url": newer["url"], "original_id": origin_id,
                          "distance": distance})
            roots[newer["id"]] = (origin_id, origin_site)
            break
    return links


def link_photo_duplicates() -> int:
    """Rattache les doublons trouvés par la photo. Retourne le nombre d'annonces rattachées."""
    from storage.sqlite import photo_hash_rows, set_duplicate_of

    linked = 0
    for link in find_photo_duplicates(photo_hash_rows()):
        if set_duplicate_of(link["url"], link["original_id"]):
            linked += 1
            logger.info(
                f"📷 Doublon par photo : annonce {link['id']} → {link['original_id']} "
                f"({link['distance']} bit(s) d'écart)"
            )
    return linked


def run_photo_dedup(limit: Optional[int] = None) -> Dict[str, int]:
    """Empreintes manquantes puis rapprochement. Ne lève jamais : un échec n'arrête pas un run."""
    stats = {"hashed": 0, "failed": 0, "linked": 0}
    if not config.PHOTO_DEDUP_ENABLED:
        return stats
    if not pillow_available():
        logger.info("Pillow absent : doublons par photo désactivés (pip install Pillow)")
        return stats
    try:
        stats.update(compute_missing_hashes(limit))
        stats["linked"] = link_photo_duplicates()
    except Exception as e:
        logger.warning(f"Doublons par photo : étape interrompue ({e})")
        return stats
    if any(stats.values()):
        logger.info(
            f"📷 Empreintes photo : {stats['hashed']} calculée(s), {stats['failed']} échec(s), "
            f"{stats['linked']} doublon(s) rattaché(s)"
        )
    return stats
