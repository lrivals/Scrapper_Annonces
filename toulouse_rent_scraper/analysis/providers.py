# analysis/providers.py
# =========================
# Fournisseurs de LLM (Sprint 15.4-bis) — chacun branche SON modèle et SA clé.
#
# Réglages, du plus prioritaire au moins prioritaire :
#   1. data/llm_settings.json — écrit par la page « Connexion LLM » de l'interface
#      (dossier data/ ignoré par git, fichier lisible par son seul propriétaire) ;
#   2. variables LLM_PROVIDER / LLM_MODEL / LLM_API_KEY / LLM_BASE_URL du fichier .env.
#
# Aucune clé n'est cherchée ailleurs : le SDK Anthropic ne lit PAS ANTHROPIC_API_KEY ni
# un profil `ant` de la machine (la clé est toujours passée explicitement). Sans fournisseur
# configuré, l'analyse ne tourne pas — elle ne consomme jamais les jetons de quelqu'un d'autre.
#
# Deux familles d'API :
#   - Anthropic (SDK officiel `anthropic`, sortie JSON imposée) ;
#   - compatibles OpenAI (`/chat/completions`) : OpenAI, Mistral, OpenRouter, Groq, Ollama et
#     LM Studio en local, ou toute autre URL compatible — appelées en HTTP (requests).
# =========================

import json
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from config import DATA_DIR, LLM_EFFORT, LLM_MAX_TOKENS

SETTINGS_FILE = DATA_DIR / "llm_settings.json"
TIMEOUT_SECONDS = 120          # un modèle local (Ollama) peut être lent


class LlmUnavailable(Exception):
    """Le service ne peut pas être appelé pour ce run (non configuré, clé, quota, panne) : arrêt, rien de facturé."""


class LlmCallError(ValueError):
    """Erreur propre à une annonce (requête rejetée, réponse tronquée ou illisible)."""

    def __init__(self, message: str, tokens=(0, 0)):
        super().__init__(message)
        self.tokens = tokens          # jetons facturés malgré l'erreur (0 si rejet avant génération)


class LlmRefused(LlmCallError):
    """Le modèle a refusé de répondre."""


# Fournisseurs proposés. Le modèle est à choisir par l'utilisateur, sauf pour Claude
# (défaut documenté) : les catalogues des autres fournisseurs changent trop vite.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "anthropic": {"label": "Claude (Anthropic)", "kind": "anthropic", "needs_key": True,
                  "default_model": "claude-opus-5-5"},
    "openai": {"label": "OpenAI", "kind": "openai", "needs_key": True,
               "base_url": "https://api.openai.com/v1"},
    "mistral": {"label": "Mistral AI", "kind": "openai", "needs_key": True,
                "base_url": "https://api.mistral.ai/v1"},
    "openrouter": {"label": "OpenRouter", "kind": "openai", "needs_key": True,
                   "base_url": "https://openrouter.ai/api/v1"},
    "groq": {"label": "Groq", "kind": "openai", "needs_key": True,
             "base_url": "https://api.groq.com/openai/v1"},
    "ollama": {"label": "Ollama (local, gratuit)", "kind": "openai", "needs_key": False,
               "base_url": "http://localhost:11434/v1"},
    "lmstudio": {"label": "LM Studio (local, gratuit)", "kind": "openai", "needs_key": False,
                 "base_url": "http://localhost:1234/v1"},
    "openai_compatible": {"label": "Autre API compatible OpenAI", "kind": "openai", "needs_key": False,
                          "base_url": ""},
}


@dataclass
class LlmSettings:
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    auto: bool = False             # analyse automatique après scraping / enrichissement
    source: str = field(default="", compare=False)   # « interface » | « .env »

    @property
    def preset(self) -> Dict[str, Any]:
        return PROVIDERS.get(self.provider, {})

    @property
    def effective_model(self) -> str:
        return self.model or self.preset.get("default_model", "")

    @property
    def effective_base_url(self) -> str:
        return (self.base_url or self.preset.get("base_url", "")).rstrip("/")

    def problems(self) -> list:
        """Ce qui empêche d'appeler le fournisseur (vide = prêt)."""
        if not self.provider:
            return ["aucun fournisseur de LLM configuré"]
        if self.provider not in PROVIDERS:
            return [f"fournisseur inconnu : {self.provider}"]
        issues = []
        if not self.effective_model:
            issues.append("modèle à renseigner")
        if self.preset.get("needs_key") and not self.api_key:
            issues.append("clé d'API à renseigner")
        if self.preset["kind"] == "openai" and not self.effective_base_url:
            issues.append("URL de l'API à renseigner")
        return issues

    @property
    def ready(self) -> bool:
        return not self.problems()

    def masked_key(self) -> str:
        if not self.api_key:
            return ""
        return "••••" + self.api_key[-4:] if len(self.api_key) > 8 else "••••"

    def label(self) -> str:
        return f"{self.preset.get('label', self.provider)} — {self.effective_model or '?'}"


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "oui", "yes")


def load_settings(path: Path = SETTINGS_FILE) -> LlmSettings:
    """Réglages de l'interface s'ils existent, sinon ceux du .env. Jamais d'autre source de clé."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("provider"):
            known = {k: data[k] for k in ("provider", "model", "api_key", "base_url", "auto") if k in data}
            return LlmSettings(**known, source="interface")
    except (OSError, ValueError, TypeError):
        pass
    provider = os.environ.get("LLM_PROVIDER", "").strip()
    return LlmSettings(
        provider=provider,
        model=os.environ.get("LLM_MODEL", "").strip(),
        api_key=os.environ.get("LLM_API_KEY", "").strip(),
        base_url=os.environ.get("LLM_BASE_URL", "").strip(),
        auto=_truthy(os.environ.get("LLM_ANALYSIS")),
        source=".env" if provider else "",
    )


def save_settings(settings: LlmSettings, path: Path = SETTINGS_FILE) -> None:
    """Écrit les réglages (clé comprise) dans un fichier lisible par son seul propriétaire."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in asdict(settings).items() if k != "source"}
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def delete_settings(path: Path = SETTINGS_FILE) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Résultat commun
# ---------------------------------------------------------------------------

@dataclass
class LlmResult:
    data: Dict[str, Any]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------------------
# Anthropic (SDK officiel)
# ---------------------------------------------------------------------------

# Modèles qui acceptent le repli serveur en cas de refus (paramètre `fallbacks`)
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5-2", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicBackend:
    def __init__(self, settings: LlmSettings, client=None):
        self.settings = settings
        self.model = settings.effective_model
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic
            # Clé passée explicitement : le SDK ne va pas chercher une clé de la machine
            self._client = anthropic.Anthropic(api_key=self.settings.api_key, max_retries=2)
        return self._client

    def build_request(self, system: str, user: str, schema: Dict) -> Dict[str, Any]:
        request: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": LLM_MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": LLM_EFFORT, "format": {"type": "json_schema", "schema": schema}},
            # Prompt système et schéma identiques pour toutes les annonces
            "cache_control": {"type": "ephemeral"},
        }
        if self.model in _FALLBACK_MODELS:
            # Refus à tort des filtres de sécurité : repli automatique côté serveur
            request["betas"] = [_FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    def complete(self, system: str, user: str, schema: Dict) -> LlmResult:
        import anthropic

        try:
            response = self.client.beta.messages.create(**self.build_request(system, user, schema))
        except anthropic.AuthenticationError as e:
            raise LlmUnavailable("clé d'API Anthropic invalide") from e
        except anthropic.PermissionDeniedError as e:
            raise LlmUnavailable(f"accès refusé : {e.message}") from e
        except anthropic.NotFoundError as e:
            raise LlmUnavailable(f"modèle introuvable : {self.model}") from e
        except anthropic.RateLimitError as e:
            raise LlmUnavailable("limite de débit atteinte, reprise au prochain run") from e
        except anthropic.BadRequestError as e:
            raise LlmCallError(f"requête refusée : {e.message}") from e
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise LlmUnavailable(f"erreur serveur {e.status_code}") from e
            raise LlmCallError(f"erreur API {e.status_code} : {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LlmUnavailable("service injoignable") from e

        usage = getattr(response, "usage", None)
        tokens = (getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise LlmRefused(f"refus du modèle ({category or 'sans catégorie'})", tokens)
        if response.stop_reason == "max_tokens":
            raise LlmCallError("réponse tronquée (max_tokens)", tokens)
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        return LlmResult(_parse_json(text, tokens), getattr(response, "model", None) or self.model, *tokens)


# ---------------------------------------------------------------------------
# API compatibles OpenAI (OpenAI, Mistral, OpenRouter, Groq, Ollama, LM Studio…)
# ---------------------------------------------------------------------------

class OpenAICompatibleBackend:
    def __init__(self, settings: LlmSettings, session: Optional[requests.Session] = None):
        self.settings = settings
        self.model = settings.effective_model
        self.url = settings.effective_base_url + "/chat/completions"
        self.session = session or requests.Session()
        # Certains serveurs ne gèrent pas json_schema : on passe alors en json_object
        self._json_schema_ok = True

    def _payload(self, system: str, user: str, schema: Dict) -> Dict[str, Any]:
        if self._json_schema_ok:
            response_format = {"type": "json_schema",
                               "json_schema": {"name": "analyse_annonce", "strict": True, "schema": schema}}
        else:
            response_format = {"type": "json_object"}
            system = (system + "\n\nRéponds uniquement par un objet JSON conforme à ce schéma :\n"
                      + json.dumps(schema, ensure_ascii=False))
        return {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": response_format,
            "max_tokens": LLM_MAX_TOKENS,
        }

    def _post(self, payload: Dict) -> requests.Response:
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        try:
            return self.session.post(self.url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise LlmUnavailable(f"service injoignable ({self.settings.effective_base_url})") from e

    def complete(self, system: str, user: str, schema: Dict) -> LlmResult:
        resp = self._post(self._payload(system, user, schema))
        if resp.status_code == 400 and self._json_schema_ok and "response_format" in resp.text:
            # Format json_schema non géré par ce serveur (requête rejetée, rien de facturé)
            self._json_schema_ok = False
            resp = self._post(self._payload(system, user, schema))

        if resp.status_code in (401, 403):
            raise LlmUnavailable("clé d'API invalide ou accès refusé")
        if resp.status_code == 404:
            raise LlmUnavailable(f"modèle ou URL introuvable : {self.model} @ {self.settings.effective_base_url}")
        if resp.status_code == 429:
            raise LlmUnavailable("limite de débit ou crédit épuisé, reprise au prochain run")
        if resp.status_code >= 500:
            raise LlmUnavailable(f"erreur serveur {resp.status_code}")
        if resp.status_code >= 400:
            raise LlmCallError(f"requête refusée ({resp.status_code}) : {resp.text[:150]}")

        try:
            body = resp.json()
            choice = body["choices"][0]
            message = choice.get("message") or {}
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LlmCallError("réponse inattendue du fournisseur") from e
        usage = body.get("usage") or {}
        tokens = (int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise LlmRefused(f"refus du modèle : {message.get('refusal') or 'filtre de contenu'}", tokens)
        if choice.get("finish_reason") == "length":
            raise LlmCallError("réponse tronquée (max_tokens)", tokens)
        return LlmResult(_parse_json(message.get("content"), tokens), body.get("model") or self.model, *tokens)


def _parse_json(text: Optional[str], tokens) -> Dict:
    if not text:
        raise LlmCallError("réponse vide", tokens)
    text = text.strip()
    if text.startswith("```"):          # certains modèles locaux entourent le JSON de ```json
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except ValueError as e:
        raise LlmCallError(f"JSON illisible : {e}", tokens) from e
    if not isinstance(data, dict):
        raise LlmCallError("JSON inattendu", tokens)
    return data


def make_backend(settings: Optional[LlmSettings] = None):
    """Backend du fournisseur configuré. LlmUnavailable s'il n'est pas prêt."""
    settings = settings or load_settings()
    problems = settings.problems()
    if problems:
        raise LlmUnavailable("; ".join(problems) + " (page « Connexion LLM » de l'interface ou .env)")
    if settings.preset["kind"] == "anthropic":
        return AnthropicBackend(settings)
    return OpenAICompatibleBackend(settings)
