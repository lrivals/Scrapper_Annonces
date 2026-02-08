# scrapers/base.py
# =========================
# Classe abstraite pour les scrapers
# =========================

import time
import random
import subprocess
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

from playwright.sync_api import sync_playwright, TimeoutError

from config import (
    PAGE_LOAD_TIMEOUT,
    MAX_PAGES_PER_SITE,
    MIN_DELAY_BETWEEN_REQUESTS,
    MAX_DELAY_BETWEEN_REQUESTS,
    MIN_ACTION_DELAY,
    MAX_ACTION_DELAY,
    BROWSER_PROFILE_DIR,
)
from utils.logger import setup_logger


class BaseScraper(ABC):
    """Classe de base pour tous les scrapers d'annonces immobilières."""

    def __init__(self):
        self.logger = setup_logger(self.site_name().lower())
        self.results: List[Dict] = []

    # =========================
    # Méthodes abstraites
    # =========================

    @abstractmethod
    def site_name(self) -> str:
        """Nom du site (ex: 'SeLoger', 'LeBonCoin')."""

    @abstractmethod
    def base_url(self) -> str:
        """URL de base du site."""

    @abstractmethod
    def search_url(self) -> str:
        """URL de recherche avec filtres pré-appliqués."""

    def search_urls(self) -> List[str]:
        """Liste d'URLs à scraper (pour pagination par URLs directes).
        Par défaut, retourne uniquement search_url(). Surcharger pour fournir
        plusieurs pages pré-calculées (ex: SeLoger page 1, 2, 3).
        """
        return [self.search_url()]

    @abstractmethod
    def card_selector(self) -> str:
        """Sélecteur CSS principal pour les cartes d'annonces."""

    @abstractmethod
    def fallback_card_selectors(self) -> List[str]:
        """Sélecteurs CSS de secours si le principal ne fonctionne pas."""

    @abstractmethod
    def extract_annonce(self, card) -> Optional[Dict]:
        """Extrait les données d'une carte d'annonce. Retourne None si échec."""

    @abstractmethod
    def next_page_selector(self) -> str:
        """Sélecteur CSS du bouton 'page suivante'."""

    def navigation_steps(self) -> List[Dict]:
        """
        Étapes de navigation avant d'arriver à la page de résultats.
        Chaque étape est un dict avec :
          - 'url': URL à visiter
          - 'label': description pour les logs
        Par défaut : page d'accueil → page de recherche.
        Surcharger pour une navigation multi-étapes (ex: LeBonCoin).
        """
        return [
            {"url": self.base_url(), "label": "page d'accueil"},
            {"url": self.search_url(), "label": "page de recherche"},
        ]

    def blocked_domains(self) -> List[str]:
        """Domaines indiquant un blocage (DataDome, captcha, etc.)."""
        return ["captcha-delivery.com", "datadome.co", "arkoselabs.com"]

    def challenge_markers(self) -> List[str]:
        """Textes indiquant un challenge/blocage dans la page."""
        return [
            "activité suspecte",
            "comportement du navigateur",
            "vitesse surhumaine",
            "accès temporairement restreint",
            "non pas à un robot",
            "we need to make sure",
            "suspicious activity",
        ]

    # =========================
    # Simulation humaine
    # =========================

    def random_delay(self):
        """Pause aléatoire entre les pages."""
        delay = random.uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS)
        self.logger.debug(f"Pause de {delay:.1f}s entre requetes")
        time.sleep(delay)

    def action_delay(self):
        """Courte pause entre les actions sur une même page."""
        time.sleep(random.uniform(MIN_ACTION_DELAY, MAX_ACTION_DELAY))

    def human_scroll(self, page, scroll_back=True):
        """Simule un scroll humain progressif.
        Si scroll_back=False, reste en bas (utile avant scraping pour lazy-loading).
        """
        page_height = page.evaluate("document.body.scrollHeight")
        current_pos = 0
        while current_pos < page_height:
            scroll_amount = random.randint(200, 500)
            current_pos += scroll_amount
            page.evaluate(f"window.scrollTo({{top: {current_pos}, behavior: 'smooth'}})")
            time.sleep(random.uniform(0.3, 1.2))
        if scroll_back:
            page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            time.sleep(random.uniform(0.5, 1.0))

    def human_mouse_move(self, page):
        """Simule des mouvements de souris aléatoires."""
        vp = page.viewport_size
        width = vp["width"] if vp else 1920
        height = vp["height"] if vp else 1080
        for _ in range(random.randint(2, 5)):
            x = random.randint(100, width - 100)
            y = random.randint(100, height - 100)
            page.mouse.move(x, y)
            time.sleep(random.uniform(0.1, 0.4))

    # =========================
    # Détection de blocage
    # =========================

    def is_page_blocked(self, page) -> bool:
        """Détecte si la page est un challenge anti-bot."""
        current_url = page.url
        if any(domain in current_url for domain in self.blocked_domains()):
            return True

        site_domain = self.base_url().replace("https://", "").replace("http://", "").split("/")[0]
        if site_domain not in current_url and current_url != "about:blank":
            return True

        # Vérifier le texte visible (inner_text)
        try:
            page_text = page.inner_text("body").lower()
            if any(marker.lower() in page_text for marker in self.challenge_markers()):
                return True
        except Exception:
            pass

        # Fallback : vérifier le HTML brut (utile si le texte n'est pas encore rendu)
        try:
            html_content = page.content().lower()
            if any(marker.lower() in html_content for marker in self.challenge_markers()):
                return True
        except Exception:
            pass

        # Vérifier le titre de la page
        try:
            title = page.title().lower()
            block_titles = ["accès restreint", "blocked", "captcha", "restricted"]
            if any(t in title for t in block_titles):
                return True
        except Exception:
            pass

        return False

    def wait_for_challenge(self, page, timeout_seconds=180) -> bool:
        """Attend la résolution manuelle d'un challenge. Retourne True si résolu."""
        if not self.is_page_blocked(page):
            return True

        self.logger.warning("=" * 60)
        self.logger.warning("CHALLENGE ANTI-BOT DETECTE !")
        self.logger.warning("Resolvez le captcha dans la fenetre Chrome.")
        self.logger.warning(f"Vous avez {timeout_seconds}s...")
        self.logger.warning("=" * 60)

        start = time.time()
        while time.time() - start < timeout_seconds:
            time.sleep(3)
            try:
                if not self.is_page_blocked(page):
                    self.logger.info("Challenge resolu ! Reprise du scraping...")
                    time.sleep(2)
                    return True
                remaining = int(timeout_seconds - (time.time() - start))
                if remaining % 15 == 0:
                    self.logger.info(f"En attente de resolution... ({remaining}s restantes)")
            except Exception:
                continue

        self.logger.error("Timeout : challenge non resolu")
        return False

    # =========================
    # Gestion cookies
    # =========================

    def handle_cookie_consent(self, page) -> bool:
        """Gère la popup de consentement cookies."""
        self.logger.info("Gestion du consentement cookies...")

        cookie_buttons = [
            'button:has-text("Tout accepter")',
            'button:has-text("Accept all")',
            'button:has-text("Accepter")',
            'button:has-text("Continuer sans accepter")',
            '#didomi-notice-agree-button',
            '.didomi-button-highlight',
        ]

        # Chercher dans la page principale
        for selector in cookie_buttons:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    self.action_delay()
                    btn.click()
                    self.logger.info(f"Cookie popup fermee (page principale: {selector})")
                    time.sleep(1)
                    return True
            except Exception:
                continue

        # Chercher dans les iframes
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for selector in cookie_buttons:
                try:
                    btn = frame.query_selector(selector)
                    if btn and btn.is_visible():
                        self.action_delay()
                        btn.click()
                        self.logger.info(f"Cookie popup fermee (iframe: {selector})")
                        time.sleep(1)
                        return True
                except Exception:
                    continue

        # Locator avec timeout court
        try:
            locator = page.get_by_role("button", name="Tout accepter")
            locator.wait_for(state="visible", timeout=5000)
            self.action_delay()
            locator.click()
            self.logger.info("Cookie popup fermee (locator role=button)")
            time.sleep(1)
            return True
        except Exception:
            pass

        self.logger.debug("Aucune popup de cookies detectee ou deja fermee")
        return False

    # =========================
    # URL helper
    # =========================

    def build_full_url(self, relative_url: str) -> str:
        """Construit une URL absolue à partir d'une URL relative."""
        if relative_url.startswith("http"):
            return relative_url
        return self.base_url().rstrip("/") + relative_url

    # =========================
    # Helpers scraping
    # =========================

    def _find_working_selector(self, page) -> Optional[str]:
        """Teste les sélecteurs et retourne le premier qui fonctionne."""
        for selector in [self.card_selector()] + self.fallback_card_selectors():
            try:
                page.wait_for_selector(selector, timeout=10000)
                return selector
            except Exception:
                continue
        return None

    def _scrape_current_page(self, page, selector: str, page_num: int):
        """Scrape les cartes de la page courante."""
        self.logger.info(f"Scraping page {page_num}")

        # Premier scroll pour déclencher le chargement initial
        self.human_scroll(page, scroll_back=True)
        time.sleep(random.uniform(1, 2))

        cards = page.query_selector_all(selector)
        if not cards:
            self.logger.warning(f"Aucune annonce trouvee sur la page {page_num}")
            return

        self.logger.debug(f"  {len(cards)} cartes trouvees")

        if cards:
            try:
                sample_html = cards[0].evaluate("el => el.outerHTML")
                self.logger.debug(f"HTML premiere carte:\n{sample_html[:2000]}")
            except Exception:
                pass

        # Extraire chaque carte en la scrollant dans le viewport d'abord
        for idx, card in enumerate(cards, 1):
            try:
                # Scroller la carte dans le viewport pour déclencher le lazy-loading
                card.scroll_into_view_if_needed()
                time.sleep(random.uniform(0.15, 0.4))

                annonce = self.extract_annonce(card)
                if annonce:
                    self.results.append(annonce)
                    self.logger.debug(f"  Carte {idx} extraite : {annonce.get('title', '')[:50]}...")
            except Exception as e:
                self.logger.warning(f"  Erreur extraction carte {idx} : {e}")
                continue

        self.logger.info(f"  {len(cards)} cartes trouvees, total: {len(self.results)} annonces")

    # =========================
    # Scraping principal
    # =========================

    def scrape(self) -> List[Dict]:
        """Lance le scraping complet et retourne la liste des annonces."""
        self.results = []
        self.logger.info(f"Demarrage scraping {self.site_name()}")

        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        chrome_proc = None
        try:
            with sync_playwright() as p:
                chrome_cmd = [
                    "google-chrome",
                    "--remote-debugging-port=9222",
                    f"--user-data-dir={BROWSER_PROFILE_DIR}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1920,1080",
                ]

                self.logger.info("Lancement de Chrome avec port de debug...")
                chrome_proc = subprocess.Popen(
                    chrome_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(3)

                self.logger.info("Connexion a Chrome via CDP...")
                browser = p.chromium.connect_over_cdp("http://localhost:9222")

                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()

                try:
                    # Navigation progressive étape par étape
                    steps = self.navigation_steps()
                    for i, step in enumerate(steps):
                        url = step["url"]
                        label = step["label"]

                        if i > 0:
                            self.random_delay()

                        self.logger.info(f"Etape {i+1}/{len(steps)} : {label} ({url[:80]}...)")
                        try:
                            page.goto(
                                url,
                                timeout=PAGE_LOAD_TIMEOUT,
                                wait_until='domcontentloaded',
                            )
                        except Exception as nav_err:
                            err_str = str(nav_err)
                            if "ERR_BLOCKED_BY_RESPONSE" in err_str or "blocked" in err_str.lower():
                                self.logger.warning(f"Blocage HTTP detecte a l'etape {i+1}. Attente...")
                                # Tenter de naviguer quand même (la page peut afficher un challenge)
                                time.sleep(5)
                                if not self.wait_for_challenge(page, timeout_seconds=300):
                                    browser.close()
                                    return self.results
                                # Re-tenter la navigation
                                try:
                                    page.goto(url, timeout=PAGE_LOAD_TIMEOUT, wait_until='domcontentloaded')
                                except Exception:
                                    self.logger.error(f"Impossible de naviguer vers {label} apres deblocage")
                                    browser.close()
                                    return self.results
                            else:
                                raise

                        time.sleep(random.uniform(3, 5))

                        if not self.wait_for_challenge(page):
                            browser.close()
                            return self.results

                        self.human_mouse_move(page)
                        if i == 0:
                            self.handle_cookie_consent(page)
                        self.action_delay()
                        self.human_scroll(page)

                    # Détection des cartes d'annonces
                    selectors_to_try = [self.card_selector()] + self.fallback_card_selectors()
                    working_selector = None

                    for selector in selectors_to_try:
                        try:
                            self.logger.debug(f"Tentative avec selecteur: {selector}")
                            page.wait_for_selector(selector, timeout=10000)
                            working_selector = selector
                            self.logger.info(f"Page chargee avec succes (selecteur: {selector})")
                            break
                        except Exception:
                            continue

                    if not working_selector:
                        # Re-vérifier si c'est un blocage (le JS peut avoir rendu entre-temps)
                        if self.is_page_blocked(page):
                            self.logger.warning("Blocage detecte apres echec des selecteurs")
                            if self.wait_for_challenge(page):
                                # Challenge résolu, re-tenter la recherche des sélecteurs
                                page.reload(wait_until='domcontentloaded')
                                time.sleep(random.uniform(3, 5))
                                for selector in selectors_to_try:
                                    try:
                                        page.wait_for_selector(selector, timeout=10000)
                                        working_selector = selector
                                        self.logger.info(f"Page chargee apres challenge (selecteur: {selector})")
                                        break
                                    except Exception:
                                        continue

                    if not working_selector:
                        self.logger.error("Aucun selecteur d'annonce trouve")
                        page.screenshot(path=f"logs/debug_{self.site_name().lower()}_screenshot.png")
                        with open(f"logs/debug_{self.site_name().lower()}_page.html", "w", encoding="utf-8") as f:
                            f.write(page.content())
                        browser.close()
                        return self.results

                except TimeoutError:
                    self.logger.error("Timeout au chargement initial")
                    try:
                        page.screenshot(path=f"logs/debug_{self.site_name().lower()}_timeout.png")
                    except Exception:
                        pass
                    browser.close()
                    return self.results

                # Scraper la première page (déjà chargée)
                self._scrape_current_page(page, working_selector, page_num=1)

                # Pages suivantes — via URLs directes ou bouton "suivant"
                all_urls = self.search_urls()
                use_direct_urls = len(all_urls) > 1

                if use_direct_urls:
                    # Pagination par URLs directes (pages 2, 3, ...)
                    for page_num, url in enumerate(all_urls[1:], start=2):
                        if page_num > MAX_PAGES_PER_SITE:
                            break

                        self.human_mouse_move(page)
                        self.random_delay()

                        self.logger.info(f"Navigation vers page {page_num} (URL directe)")
                        try:
                            page.goto(url, timeout=PAGE_LOAD_TIMEOUT, wait_until='domcontentloaded')
                        except Exception as nav_err:
                            self.logger.warning(f"Erreur navigation page {page_num}: {nav_err}")
                            break

                        time.sleep(random.uniform(3, 5))

                        if self.is_page_blocked(page):
                            self.logger.warning(f"Blocage detecte page {page_num}, arret")
                            if not self.wait_for_challenge(page):
                                break

                        self.handle_cookie_consent(page)
                        self.human_scroll(page)

                        working_selector = self._find_working_selector(page)
                        if not working_selector:
                            self.logger.warning(f"Aucun selecteur trouve page {page_num}, arret")
                            break

                        self._scrape_current_page(page, working_selector, page_num)
                else:
                    # Pagination par bouton "suivant"
                    current_page = 1
                    while current_page < MAX_PAGES_PER_SITE:
                        try:
                            next_button = page.query_selector(self.next_page_selector())
                            if not next_button:
                                self.logger.info("Pas de page suivante, fin de la pagination")
                                break

                            self.human_mouse_move(page)
                            self.random_delay()

                            current_page += 1
                            self.logger.debug("Clic sur 'page suivante'...")
                            next_button.click()
                            page.wait_for_selector(working_selector, timeout=PAGE_LOAD_TIMEOUT)

                            if not self.wait_for_challenge(page):
                                break

                            time.sleep(random.uniform(1, 3))
                            self.human_scroll(page)

                            self._scrape_current_page(page, working_selector, current_page)

                        except TimeoutError:
                            self.logger.warning("Timeout lors de la pagination, arret")
                            break
                        except Exception as e:
                            self.logger.error(f"Erreur lors de la pagination : {e}")
                            break

                browser.close()

        except Exception as e:
            self.logger.error(f"Erreur critique lors du scraping : {e}", exc_info=True)
        finally:
            if chrome_proc:
                chrome_proc.terminate()

        self.logger.info(f"Scraping termine : {len(self.results)} annonces au total")
        return self.results
