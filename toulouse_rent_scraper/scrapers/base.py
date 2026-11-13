# scrapers/base.py
# =========================
# Classe abstraite pour les scrapers
# =========================

import time
import random
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from urllib.parse import urlparse

from config import (
    PAGE_LOAD_TIMEOUT,
    MAX_PAGES_PER_SITE,
    MIN_DELAY_BETWEEN_REQUESTS,
    MAX_DELAY_BETWEEN_REQUESTS,
    WARMUP_PAGE_MAX_DELAY,
    WARMUP_PAGE_MIN_DELAY,
    WARMUP_STEP_MAX_DELAY,
    WARMUP_STEP_MIN_DELAY,
    MIN_ACTION_DELAY,
    MAX_ACTION_DELAY,
    LOG_DIR,
    CHALLENGE_TIMEOUT_SECONDS,
    UNATTENDED_CHALLENGE_TIMEOUT_SECONDS,
    SEARCH_PROFILES,
    DEFAULT_PROFILE,
    SearchProfile,
)
from scrapers import antibot
from scrapers.browser import chrome_session, BrowserError, PlaywrightTimeoutError
from utils.logger import setup_logger


class BaseScraper(ABC):
    """Classe de base pour tous les scrapers d'annonces immobilières."""

    def __init__(self, profile: Optional[SearchProfile] = None, unattended: bool = False):
        self.profile = profile or SEARCH_PROFILES[DEFAULT_PROFILE]
        # Mode planifié : attente de captcha plus longue (le temps de voir la notification)
        self.unattended = unattended
        self.challenge_timeout = (
            UNATTENDED_CHALLENGE_TIMEOUT_SECONDS if unattended else CHALLENGE_TIMEOUT_SECONDS
        )
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
    def search_url(self) -> Optional[str]:
        """URL de recherche avec filtres pré-appliqués (None si le profil n'est pas configuré pour ce site)."""

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
        Par défaut : page d'accueil → recherches de warm-up éventuelles → recherche scannée.
        """
        warmups = self.warmup_urls()
        steps = [{"url": self.base_url(), "label": "page d'accueil"}]
        steps += [
            {"url": url, "label": f"warm-up {i}/{len(warmups)}"}
            for i, url in enumerate(warmups, start=1)
        ]
        steps.append({"url": self.search_url(), "label": f"recherche ({self.profile.label})"})
        return steps

    def warmup_urls(self) -> List[str]:
        """Recherches visitées avant la recherche scannée (cooldown entre chaque). Défaut : aucune."""
        return []

    # --- Données structurées de la page de résultats (Sprint 15.2) ---

    def page_json_annonces(self, page) -> List[Dict]:
        """
        Annonces lues dans les données structurées de la page de résultats (JSON embarqué),
        plus complètes que les cartes. Défaut : aucune (extraction par cartes seulement).
        """
        return []

    def annonce_key(self, url: Optional[str]) -> Optional[str]:
        """Identifiant stable d'une annonce à partir de son URL (jointure JSON ↔ cartes)."""
        return url

    def card_url(self, card) -> Optional[str]:
        """URL d'une carte sans l'extraire entièrement (lien vers l'annonce)."""
        try:
            href = card.get_attribute("href")
            if not href:
                link = card.query_selector("a[href]")
                href = link.get_attribute("href") if link else None
            return self.build_full_url(href) if href else None
        except Exception:
            return None

    def blocked_domains(self) -> List[str]:
        """Domaines indiquant un blocage (DataDome, captcha, etc.)."""
        return antibot.BLOCKED_DOMAINS

    def challenge_markers(self) -> List[str]:
        """Textes indiquant un challenge/blocage dans la page."""
        return antibot.CHALLENGE_MARKERS

    # =========================
    # Simulation humaine
    # =========================

    def random_delay(self):
        """Pause aléatoire entre les pages."""
        delay = random.uniform(MIN_DELAY_BETWEEN_REQUESTS, MAX_DELAY_BETWEEN_REQUESTS)
        self.logger.debug(f"Pause de {delay:.1f}s entre requetes")
        time.sleep(delay)

    def step_delay(self):
        """Pause entre deux étapes de navigation ; cooldown long si parcours avec warm-up."""
        if not self.warmup_urls():
            return self.random_delay()
        self._cooldown(WARMUP_STEP_MIN_DELAY, WARMUP_STEP_MAX_DELAY, "l'etape suivante")

    def page_delay(self):
        """Pause entre deux pages de résultats ; cooldown long si parcours avec warm-up."""
        if not self.warmup_urls():
            return self.random_delay()
        self._cooldown(WARMUP_PAGE_MIN_DELAY, WARMUP_PAGE_MAX_DELAY, "la page suivante")

    def _cooldown(self, low: float, high: float, what: str):
        delay = random.uniform(low, high)
        self.logger.info(f"Cooldown {delay:.0f}s avant {what}")
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
        """Détecte si la page est un challenge anti-bot (ou une redirection hors du site)."""
        return antibot.is_page_blocked(
            page,
            site_domain=urlparse(self.base_url()).netloc,
            blocked_domains=self.blocked_domains(),
            markers=self.challenge_markers(),
        )

    def wait_for_challenge(self, page, timeout_seconds: Optional[int] = None) -> bool:
        """
        Attend la résolution manuelle d'un challenge (notification envoyée au début).
        Un blocage non résolu est mémorisé : les runs planifiés sauteront ce site un moment.
        """
        from notify import notify_captcha

        timeout = max(timeout_seconds or 0, self.challenge_timeout)
        resolved = antibot.wait_for_challenge(
            page,
            timeout,
            is_blocked=self.is_page_blocked,
            on_challenge=lambda: notify_captcha(self.site_name(), timeout),
        )
        if not resolved:
            antibot.record_block(self.site_name())
        return resolved

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
                self.logger.debug(f"Tentative avec selecteur: {selector}")
                page.wait_for_selector(selector, timeout=10000)
                return selector
            except Exception:
                continue
        return None

    def _best_selector_cards(self, page, preferred: str):
        """
        Cartes de la page courante avec le sélecteur qui en trouve le plus.
        LBC mélange parfois les attributs (quelques cartes en data-qa-id, le reste
        en data-test-id) : s'en tenir au premier sélecteur qui matche en rate la plupart.
        """
        best_selector, best_cards = preferred, []
        candidates = [preferred] + [
            s for s in [self.card_selector()] + self.fallback_card_selectors() if s != preferred
        ]
        for candidate in candidates:
            try:
                cards = page.query_selector_all(candidate)
            except Exception:
                continue
            if len(cards) > len(best_cards):
                best_selector, best_cards = candidate, cards
        if best_selector != preferred:
            self.logger.info(f"  Selecteur {best_selector} retenu ({len(best_cards)} cartes)")
        return best_selector, best_cards

    # Part minimale des cartes affichées présentes dans le JSON : en dessous, le JSON
    # est périmé (pagination côté client) ou ne décrit pas la liste affichée
    JSON_MIN_CARD_OVERLAP = 0.5

    def _json_annonces_for_cards(self, page, cards) -> List[Dict]:
        """JSON de la page, s'il correspond bien aux cartes affichées ; sinon liste vide."""
        try:
            json_annonces = self.page_json_annonces(page)
        except Exception as e:
            self.logger.warning(f"  Données JSON de la page illisibles : {e}")
            return []
        if not json_annonces:
            return []
        if not cards:
            return json_annonces
        json_keys = {self.annonce_key(a.get("url")) for a in json_annonces}
        card_keys = [k for k in (self.annonce_key(self.card_url(c)) for c in cards) if k]
        if card_keys:
            overlap = sum(k in json_keys for k in card_keys) / len(card_keys)
            if overlap < self.JSON_MIN_CARD_OVERLAP:
                self.logger.info(
                    f"  JSON ignoré : {overlap:.0%} des cartes affichées y figurent (page périmée ?)"
                )
                return []
        return json_annonces

    def _scrape_current_page(self, page, selector: str, page_num: int):
        """
        Scrape la page courante : annonces du JSON embarqué si disponible et cohérent avec
        les cartes affichées, puis cartes DOM pour les annonces absentes du JSON.
        """
        self.logger.info(f"Scraping page {page_num}")

        # Premier scroll pour déclencher le chargement initial
        self.human_scroll(page, scroll_back=True)
        time.sleep(random.uniform(1, 2))

        selector, cards = self._best_selector_cards(page, selector)
        json_annonces = self._json_annonces_for_cards(page, cards)
        if not cards and not json_annonces:
            self.logger.warning(f"Aucune annonce trouvee sur la page {page_num}")
            return

        json_keys = set()
        for annonce in json_annonces:
            self.results.append(annonce)
            json_keys.add(self.annonce_key(annonce.get("url")))
        if json_annonces:
            self.logger.info(f"  {len(json_annonces)} annonces lues depuis le JSON de la page")

        self.logger.debug(f"  {len(cards)} cartes trouvees")

        if cards and not json_annonces:
            try:
                sample_html = cards[0].evaluate("el => el.outerHTML")
                self.logger.debug(f"HTML premiere carte:\n{sample_html[:2000]}")
            except Exception:
                pass

        # Extraire chaque carte absente du JSON, en la scrollant dans le viewport d'abord
        from_cards = 0
        for idx, card in enumerate(cards, 1):
            if json_keys and self.annonce_key(self.card_url(card)) in json_keys:
                continue
            try:
                # Scroller la carte dans le viewport pour déclencher le lazy-loading
                card.scroll_into_view_if_needed()
                time.sleep(random.uniform(0.15, 0.4))

                annonce = self.extract_annonce(card)
                if annonce:
                    self.results.append(annonce)
                    from_cards += 1
                    self.logger.debug(f"  Carte {idx} extraite : {annonce.get('title', '')[:50]}...")
            except Exception as e:
                self.logger.warning(f"  Erreur extraction carte {idx} : {e}")
                continue

        if json_annonces and from_cards:
            self.logger.info(f"  {from_cards} carte(s) absente(s) du JSON extraite(s) depuis le DOM")
        self.logger.info(f"  {len(cards)} cartes trouvees, total: {len(self.results)} annonces")

    # =========================
    # Scraping principal
    # =========================

    def scrape(self) -> List[Dict]:
        """Lance le scraping complet et retourne la liste des annonces."""
        self.results = []
        if not self.search_url():
            self.logger.warning(
                f"Profil '{self.profile.key}' non configuré pour {self.site_name()} "
                f"(URL de recherche manquante), site ignoré"
            )
            return self.results
        self.logger.info(f"Demarrage scraping {self.site_name()} — profil {self.profile.label}")

        try:
            with chrome_session() as (_browser, page):
                selector = self._open_search(page)
                if selector:
                    self._scrape_current_page(page, selector, page_num=1)
                    self._paginate(page, selector)
        except BrowserError as e:
            self.logger.error(f"Navigateur indisponible : {e}")
        except Exception as e:
            self.logger.error(f"Erreur critique lors du scraping : {e}", exc_info=True)

        self.logger.info(f"Scraping termine : {len(self.results)} annonces au total")
        return self.results

    def _open_search(self, page) -> Optional[str]:
        """Navigation jusqu'aux résultats. Retourne le sélecteur de cartes, ou None si échec."""
        try:
            if not self._navigate_steps(page):
                return None
            selector = self._find_working_selector(page) or self._retry_after_challenge(page)
            if not selector:
                self.logger.error("Aucun selecteur d'annonce trouve")
                self._dump_debug(page, "page")
                return None
            self.logger.info(f"Page chargee avec succes (selecteur: {selector})")
            return selector
        except PlaywrightTimeoutError:
            self.logger.error("Timeout au chargement initial")
            self._dump_debug(page, "timeout", html=False)
            return None

    def _navigate_steps(self, page) -> bool:
        """Navigation progressive (accueil → recherche). False si bloqué sans résolution."""
        steps = self.navigation_steps()
        for i, step in enumerate(steps):
            url, label = step["url"], step["label"]
            if i > 0:
                self.step_delay()

            self.logger.info(f"Etape {i+1}/{len(steps)} : {label} ({url[:80]}...)")
            if not self._goto_with_block_handling(page, url, label):
                return False

            time.sleep(random.uniform(3, 5))
            if not self.wait_for_challenge(page):
                return False

            self.human_mouse_move(page)
            if i == 0:
                self.handle_cookie_consent(page)
            self.action_delay()
            self.human_scroll(page)
        return True

    def _goto_with_block_handling(self, page, url: str, label: str) -> bool:
        try:
            page.goto(url, timeout=PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            return True
        except Exception as nav_err:
            err_str = str(nav_err)
            if "ERR_BLOCKED_BY_RESPONSE" not in err_str and "blocked" not in err_str.lower():
                raise
        # Blocage HTTP : la page peut afficher un challenge à résoudre à la main
        self.logger.warning(f"Blocage HTTP detecte ({label}). Attente...")
        time.sleep(5)
        if not self.wait_for_challenge(page, timeout_seconds=300):
            return False
        try:
            page.goto(url, timeout=PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            return True
        except Exception:
            self.logger.error(f"Impossible de naviguer vers {label} apres deblocage")
            return False

    def _retry_after_challenge(self, page) -> Optional[str]:
        """Les sélecteurs ont échoué : si c'est un challenge (rendu tardif), attendre puis réessayer."""
        if not self.is_page_blocked(page):
            return None
        self.logger.warning("Blocage detecte apres echec des selecteurs")
        if not self.wait_for_challenge(page):
            return None
        page.reload(wait_until="domcontentloaded")
        time.sleep(random.uniform(3, 5))
        return self._find_working_selector(page)

    def _dump_debug(self, page, suffix: str, html: bool = True):
        """Capture écran (+ HTML) dans LOG_DIR pour diagnostiquer un changement de page."""
        base = LOG_DIR / f"debug_{self.site_name().lower()}_{suffix}"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(base.with_suffix(".png")))
            if html:
                base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
            self.logger.info(f"Capture de debug : {base}.*")
        except Exception as e:
            self.logger.debug(f"Capture de debug impossible : {e}")

    def _paginate(self, page, selector: str):
        """Pages suivantes : URLs directes si fournies, sinon bouton « suivant »."""
        urls = self.search_urls()
        if len(urls) > 1:
            self._paginate_by_urls(page, urls[1:])
        else:
            self._paginate_by_button(page, selector)

    def _paginate_by_urls(self, page, urls: List[str]):
        for page_num, url in enumerate(urls, start=2):
            if page_num > MAX_PAGES_PER_SITE:
                break

            self.human_mouse_move(page)
            self.page_delay()

            self.logger.info(f"Navigation vers page {page_num} (URL directe)")
            try:
                page.goto(url, timeout=PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
            except Exception as nav_err:
                self.logger.warning(f"Erreur navigation page {page_num}: {nav_err}")
                break

            time.sleep(random.uniform(3, 5))

            if self.is_page_blocked(page):
                self.logger.warning(f"Blocage detecte page {page_num}")
                if not self.wait_for_challenge(page):
                    break

            self.handle_cookie_consent(page)
            self.human_scroll(page)

            selector = self._find_working_selector(page)
            if not selector:
                self.logger.warning(f"Aucun selecteur trouve page {page_num}, arret")
                break

            self._scrape_current_page(page, selector, page_num)

    def _paginate_by_button(self, page, selector: str):
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
                page.wait_for_selector(selector, timeout=PAGE_LOAD_TIMEOUT)

                if not self.wait_for_challenge(page):
                    break

                time.sleep(random.uniform(1, 3))
                self.human_scroll(page)

                self._scrape_current_page(page, selector, current_page)

            except PlaywrightTimeoutError:
                self.logger.warning("Timeout lors de la pagination, arret")
                break
            except Exception as e:
                self.logger.error(f"Erreur lors de la pagination : {e}")
                break
