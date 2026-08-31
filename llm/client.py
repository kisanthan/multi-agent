"""Provider-neutral access to local and cloud language models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping

from pydantic import BaseModel

from agent_registry import ModelClass, get_config
from config import (AuthMethod, ModelMode, ModelProfile, ProfileId, Provider,
                    settings)


class LLMUnreachable(Exception):
    """Authentication, transport, quota, refusal, or provider availability error."""


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model_id: str
    risk_class: str
    profile_id: str = "legacy"
    configuration_revision: int = 1


def choose_profile(
    profile_id: ProfileId | str,
    snapshot: Mapping[str, Mapping[str, str]] | None = None,
) -> ModelChoice:
    """Resolve an effective profile, optionally from a case-start snapshot."""
    profile_id = ProfileId(profile_id)
    if snapshot and profile_id.value in snapshot:
        raw = snapshot[profile_id.value]
        profile = ModelProfile(
            profile_id=profile_id,
            provider=Provider(raw["provider"]),
            model_id=raw["model_id"],
            auth_method=AuthMethod(raw.get("auth_method", "keine")),
        )
    else:
        profile = settings.profile(profile_id)
    return ModelChoice(
        provider=profile.provider.value,
        model_id=profile.model_id,
        risk_class="prozessprofil",
        profile_id=profile_id.value,
        configuration_revision=(
            int(snapshot[profile_id.value].get("configuration_revision",
                                               settings.configuration_revision))
            if snapshot and profile_id.value in snapshot
            else settings.configuration_revision
        ),
    )


def choose_model(agent_id: str) -> ModelChoice:
    """Legacy risk-class resolver plus mappings for the split agents.

    New runtime code uses :func:`choose_profile`.  Keeping this function
    avoids breaking the CLI, older checkpoints, and the architectural tests
    which deliberately exercise the former deployment-mode behavior.
    """
    profile_agents = {
        "klassifikation": ProfileId.ROUTER,
        "extraktion_zahlung": ProfileId.PAYMENT,
        "extraktion_rechnung": ProfileId.INVOICE,
    }
    if agent_id in profile_agents and (
        getattr(settings, f"llm_{profile_agents[agent_id].value}_provider") is not None
    ):
        return choose_profile(profile_agents[agent_id])

    cfg = get_config(agent_id)
    cls = cfg.model_class
    mode = settings.model_mode
    if cls is ModelClass.NO_MODEL:
        # Deterministic components (reader, policy, audit) AND domain agents
        # that work deterministically (reconciliation, cost-center -- exact
        # lookup, Thesis §7.4) never call a language model.
        raise ValueError(
            f"{cfg.name} ruft kein Sprachmodell auf (Modellklasse KEINE)."
        )

    if mode is ModelMode.LOCAL:
        model = settings.ollama_model_vision if cls is ModelClass.VISION else settings.ollama_model_small
        return ModelChoice("ollama", model, cls.value)
    if mode is ModelMode.CLOUD:
        model = settings.cloud_model_small if cls is ModelClass.LOCAL_SMALL else settings.cloud_model_frontier
        return ModelChoice("anthropic", model, cls.value)
    if cls is ModelClass.LOCAL_SMALL:
        return ModelChoice("ollama", settings.ollama_model_small, cls.value)
    return ModelChoice("anthropic", settings.cloud_model_frontier, cls.value)


class LLMClient(ABC):
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    @abstractmethod
    def ask_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        """Return raw JSON; deterministic validation remains in extraction.py."""


class OllamaClient(LLMClient):
    def ask_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        import httpx

        try:
            response = httpx.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": self.model_id,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    # Ollama enforces the schema via a GBNF grammar. We
                    # cannot rely on that -- see R1 in docs/limitations.md and
                    # the validation in llm/extraction.py.
                    "format": schema.model_json_schema(),
                    "stream": False,
                    "options": {"temperature": 0},
                },
                timeout=180.0,
            )
        except httpx.ConnectError as e:
            raise LLMUnreachable(
                f"Keine Verbindung zu Ollama unter {settings.ollama_base_url}. "
                "Läuft der Dienst? Start: `ollama serve`."
            ) from e
        except httpx.HTTPError as e:
            raise LLMUnreachable(f"Ollama-Transportfehler ({type(e).__name__}).") from e
        if response.status_code == 404:
            raise LLMUnreachable(
                f"Modell {self.model_id!r} ist nicht geladen. Laden mit: "
                f"`ollama pull {self.model_id}`."
            )
        if response.status_code != 200:
            raise LLMUnreachable(f"Ollama antwortete mit HTTP {response.status_code}.")
        return response.json()["message"]["content"]


class AnthropicClient(LLMClient):
    def ask_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise LLMUnreachable("Paket 'anthropic' ist nicht installiert.") from e

        try:
            if settings.anthropic_auth_method is AuthMethod.PROFILE:
                client = anthropic.Anthropic(profile=settings.anthropic_profile)
            else:
                if not settings.anthropic_api_key:
                    raise LLMUnreachable("ANTHROPIC_API_KEY ist nicht hinterlegt.")
                client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.parse(
                model=self.model_id,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except LLMUnreachable:
            raise
        except anthropic.APIError as e:
            raise LLMUnreachable(f"Anthropic-API-Fehler ({type(e).__name__}).") from e
        if response.stop_reason == "refusal":
            raise LLMUnreachable("Das Modell hat die Anfrage aus Sicherheitsgruenden abgelehnt.")
        if response.parsed_output is not None:
            return response.parsed_output.model_dump_json()
        return next((b.text for b in response.content if b.type == "text"), "")


def _google_credentials():
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as e:
        raise LLMUnreachable("Google-OAuth-Pakete sind nicht installiert.") from e
    required = [settings.google_oauth_client_id, settings.google_oauth_client_secret,
                settings.google_oauth_refresh_token, settings.google_cloud_project]
    if not all(required):
        raise LLMUnreachable("Die Google-OAuth-Verbindung ist unvollständig.")
    return Credentials(
        token=None,
        refresh_token=settings.google_oauth_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        quota_project_id=settings.google_cloud_project,
    )


class GoogleClient(LLMClient):
    def _client(self):
        try:
            from google import genai
        except ImportError as e:
            raise LLMUnreachable("Paket 'google-genai' ist nicht installiert.") from e
        if settings.google_auth_method is AuthMethod.OAUTH:
            return genai.Client(credentials=_google_credentials())
        if not settings.google_api_key:
            raise LLMUnreachable("Für Google ist kein API-Key hinterlegt.")
        return genai.Client(api_key=settings.google_api_key)

    def ask_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        try:
            from google.genai import types
            response = self._client().models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0,
                ),
            )
            return response.text or ""
        except LLMUnreachable:
            raise
        except Exception as e:  # provider SDK has several transport subclasses
            raise LLMUnreachable(f"Google-API-Fehler ({type(e).__name__}).") from e


class OpenAIClient(LLMClient):
    def ask_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        try:
            import openai
        except ImportError as e:
            raise LLMUnreachable("Paket 'openai' ist nicht installiert.") from e
        if not settings.openai_api_key:
            raise LLMUnreachable("Für OpenAI ist kein API-Key hinterlegt.")
        try:
            client = openai.OpenAI(api_key=settings.openai_api_key)
            response = client.responses.parse(
                model=self.model_id,
                instructions=system,
                input=prompt,
                text_format=schema,
                store=False,
            )
            if getattr(response, "error", None) is not None:
                raise LLMUnreachable("OpenAI konnte die Anfrage nicht ausführen.")
            for item in getattr(response, "output", ()):
                for content in getattr(item, "content", ()):
                    if getattr(content, "type", None) == "refusal":
                        raise LLMUnreachable(
                            "Das OpenAI-Modell hat die Anfrage abgelehnt."
                        )
            if response.output_parsed is not None:
                return response.output_parsed.model_dump_json()
            return response.output_text or ""
        except LLMUnreachable:
            raise
        except openai.APIError as e:
            raise LLMUnreachable(f"OpenAI-API-Fehler ({type(e).__name__}).") from e


CLIENTS = {
    Provider.OLLAMA.value: OllamaClient,
    Provider.GOOGLE.value: GoogleClient,
    Provider.ANTHROPIC.value: AnthropicClient,
    Provider.OPENAI.value: OpenAIClient,
}


def client_for(
    agent_id: str,
    *,
    profile_id: ProfileId | str | None = None,
    snapshot: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[LLMClient, ModelChoice]:
    choice = choose_profile(profile_id, snapshot) if profile_id else choose_model(agent_id)
    return CLIENTS[choice.provider](choice.model_id), choice


def list_models(provider: Provider | str) -> list[str]:
    """Authenticated model discovery used by the settings page/preflight."""
    provider = Provider(provider)
    try:
        if provider is Provider.OLLAMA:
            import httpx
            response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5.0)
            response.raise_for_status()
            return sorted(m["name"] for m in response.json().get("models", []))
        if provider is Provider.ANTHROPIC:
            import anthropic
            client = (anthropic.Anthropic(profile=settings.anthropic_profile)
                      if settings.anthropic_auth_method is AuthMethod.PROFILE
                      else anthropic.Anthropic(api_key=settings.anthropic_api_key))
            return sorted(m.id for m in client.models.list().data)
        if provider is Provider.OPENAI:
            import openai
            return sorted(m.id for m in openai.OpenAI(api_key=settings.openai_api_key).models.list().data)
        client = GoogleClient("")._client()
        return sorted(m.name.removeprefix("models/") for m in client.models.list())
    except Exception as e:
        if isinstance(e, LLMUnreachable):
            raise
        raise LLMUnreachable(f"{provider.value}-Verbindung fehlgeschlagen ({type(e).__name__}).") from e
