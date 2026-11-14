"""Debug script (Sprint 4.1) : capture la recherche PAP.fr et une fiche pour repérer la structure.

Usage : python scripts/debug/capture_cards_pap.py [URL de recherche]
        python scripts/debug/capture_cards_pap.py --detail URL_DE_FICHE
  défaut : locations à Blagnac (identifiants de lieu PAP g19307g43612)

PAP est derrière Cloudflare (403 « Just a moment… » sans navigateur) : on passe par le
vrai Chrome au profil persistant. Si la vérification Cloudflare s'affiche, la résoudre à
la main dans la fenêtre (le script attend jusqu'à 3 min).

Sorties dans logs/ :
  debug_pap_search.html     page de recherche complète
  debug_pap_search.png      capture d'écran
  debug_pap_scripts.txt     scripts JSON embarqués (ld+json, état d'application…)
  debug_pap_cards.txt       HTML + texte des 5 premières cartes candidates
  debug_pap_detail.html     première fiche ouverte (+ .png)
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import LOG_DIR  # noqa: E402
from scrapers.browser import chrome_session  # noqa: E402

BASE_URL = "https://www.pap.fr"
DETAIL_ONLY = len(sys.argv) > 2 and sys.argv[1] == "--detail"
SEARCH_URL = sys.argv[1] if len(sys.argv) > 1 and not DETAIL_ONLY else (
    "https://www.pap.fr/annonce/locations-blagnac-31700-g19307g43612"
)
CHALLENGE_MARKERS = ("just a moment", "un instant", "vérifiez que vous êtes humain",
                     "verify you are human", "checking your browser")

# Sélecteurs candidats des cartes de résultat (le bon sera noté dans docs/pap_selectors.md)
CARD_SELECTORS = [
    "div.search-list-item-alt",
    "div.search-list-item",
    "[class*='search-list-item']",
    "article",
    "div:has(> a[href*='/annonces/'])",
]


def is_challenged(page) -> bool:
    try:
        text = (page.title() + " " + page.inner_text("body")[:2000]).lower()
    except Exception:
        return False
    return any(m in text for m in CHALLENGE_MARKERS)


def wait_challenge(page, timeout=180):
    if not is_challenged(page):
        return True
    print(f"⚠️  Vérification Cloudflare : la résoudre dans Chrome (≤ {timeout}s)…")
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(3)
        if not is_challenged(page):
            print("✅ Vérification passée")
            time.sleep(3)
            return True
    print("❌ Toujours bloqué")
    return False


def accept_cookies(page):
    for sel in ['#didomi-notice-agree-button', 'button:has-text("Tout accepter")',
                'button:has-text("Accepter")', 'button:has-text("J\'accepte")']:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                print(f"Cookies acceptés ({sel})")
                time.sleep(1)
                return
        except Exception:
            continue


def screenshot(page, path: Path):
    """Capture non bloquante (la page pleine hauteur de PAP dépasse parfois le délai)."""
    try:
        page.screenshot(path=str(path), timeout=10000)
    except Exception as e:
        print(f"(capture d'écran ignorée : {e.__class__.__name__})")


def capture_detail(page, url: str):
    print(f"Fiche : {url}")
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    time.sleep(5)
    if not wait_challenge(page):
        return
    (LOG_DIR / "debug_pap_detail.html").write_text(page.content(), encoding="utf-8")
    screenshot(page, LOG_DIR / "debug_pap_detail.png")
    dump_scripts(page, LOG_DIR / "debug_pap_detail_scripts.txt")
    print(f"Fiche enregistrée → {LOG_DIR}/debug_pap_detail.html")


def dump_scripts(page, path: Path):
    scripts = page.evaluate("""() => [...document.querySelectorAll('script')].map(s => ({
        type: s.type || '', id: s.id || '', len: s.textContent.length,
        head: s.textContent.slice(0, 3000)
    })).filter(s => s.len > 200 && (s.type.includes('json') || /[{\\[]/.test(s.head.slice(0, 50))))""")
    with open(path, "w", encoding="utf-8") as f:
        for s in scripts:
            f.write(f"\n{'=' * 80}\ntype={s['type']} id={s['id']} len={s['len']}\n{'=' * 80}\n{s['head']}\n")
    print(f"{len(scripts)} script(s) JSON candidats → {path}")


with chrome_session() as (browser, page):
    print("Étape 1 : accueil PAP…")
    page.goto(BASE_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(4)
    if not wait_challenge(page):
        sys.exit(1)
    accept_cookies(page)

    if DETAIL_ONLY:
        time.sleep(5)
        capture_detail(page, sys.argv[2])
        sys.exit(0)

    print(f"Étape 2 : recherche {SEARCH_URL}")
    time.sleep(5)
    page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(5)
    if not wait_challenge(page):
        sys.exit(1)
    accept_cookies(page)
    print(f"URL finale : {page.url}\nTitre : {page.title()}")

    # Pas de pagination sur PAP : défilement infini. On défile jusqu'à ce que le nombre
    # de liens d'annonce n'augmente plus, en notant les requêtes qui chargent la suite.
    xhr_log = []

    def on_response(resp):
        req = resp.request
        if req.resource_type in ("xhr", "fetch") and "pap.fr" in resp.url:
            try:
                body = resp.text()[:3000]
            except Exception:
                body = "(illisible)"
            xhr_log.append(f"{req.method} {resp.status} {resp.url}\n"
                           f"content-type={resp.headers.get('content-type')}\n"
                           f"post={(req.post_data or '')[:500]}\n{body}\n")

    page.on("response", on_response)
    count_js = """() => new Set([...document.querySelectorAll('a[href]')].map(a => a.href)
        .filter(h => /\\/annonces?\\/.*-r\\d+/.test(h))).size"""
    previous, stable = -1, 0
    for step in range(40):
        page.mouse.wheel(0, 900)
        time.sleep(1.5)
        n = page.evaluate(count_js)
        if n == previous:
            stable += 1
            if stable >= 4:
                break
        else:
            stable = 0
            previous = n
        print(f"  défilement {step + 1} : {n} annonce(s)")
    page.remove_listener("response", on_response)
    (LOG_DIR / "debug_pap_xhr.txt").write_text(
        f"\n{'=' * 80}\n".join(xhr_log), encoding="utf-8")
    print(f"{len(xhr_log)} requête(s) XHR pap.fr → {LOG_DIR}/debug_pap_xhr.txt")

    (LOG_DIR / "debug_pap_search.html").write_text(page.content(), encoding="utf-8")
    screenshot(page, LOG_DIR / "debug_pap_search.png")
    dump_scripts(page, LOG_DIR / "debug_pap_scripts.txt")

    links = page.evaluate("""() => [...new Set([...document.querySelectorAll('a[href]')]
        .map(a => a.href).filter(h => /\\/annonces?\\/.*-r\\d+/.test(h)))]""")
    print(f"{len(links)} lien(s) d'annonce, ex. : {links[:3]}")
    pagination = []  # défilement infini (pas de pages)


    with open(LOG_DIR / "debug_pap_cards.txt", "w", encoding="utf-8") as f:
        for sel in CARD_SELECTORS:
            cards = page.query_selector_all(sel)
            f.write(f"\n### {sel} → {len(cards)} carte(s)\n")
            print(f"{sel!r} → {len(cards)}")
            for i, card in enumerate(cards[:5]):
                f.write(f"\n{'=' * 80}\nCARTE {i + 1}\n--- TEXTE ---\n{card.inner_text()}\n"
                        f"--- HTML ---\n{card.evaluate('el => el.outerHTML')[:6000]}\n")
            if cards:
                break

    apartments = [u for u in links if "/annonces/appartement-" in u] or links
    if apartments:
        time.sleep(8)
        capture_detail(page, apartments[0])

    print(f"\nCaptures dans {LOG_DIR}/debug_pap_*")
