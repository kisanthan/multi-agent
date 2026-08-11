"""Abstraction layer over the language models.

Wraps every LLM call behind an interface, so that each agent can be switched
between cloud and local per config. This is the technical counterpart to the
risk-class-based model assignment from the concept diagram
`teil2_ki_modelle.png` and the basis for the thesis's sub-question 2 (data
sovereignty vs. performance).

Which concrete model an agent gets follows from two inputs: its risk class
(agent_registry.py) and the deployment mode (.env). No agent knows its provider --
that is the point.

Model IDs and prices as of 2026-07-17 (change quarterly).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel

from agent_registry import ModelClass, get_config
from config import ModelMode, settings


class LLMUnreachable(Exception):
    """Transport error -- not a content problem.

    Kept separate from a schema violation, because the reaction differs: an
    unreachable model is an operational problem, a schema violation is a
    case for the approval queue.
    """


@dataclass(frozen=True)
class ModelChoice:
    provider: str   # 'ollama' | 'anthropic'
    model_id: str
    risk_class: str


def choose_model(agent_id: str) -> ModelChoice:
    """Derives the model choice from the risk class (registry) and mode (.env)."""
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
        model = (settings.ollama_model_vision if cls is ModelClass.VISION
                 else settings.ollama_model_small)
        return ModelChoice("ollama", model, cls.value)

    if mode is ModelMode.CLOUD:
        model = (settings.cloud_model_small if cls is ModelClass.LOCAL_SMALL
                 else settings.cloud_model_frontier)
        return ModelChoice("anthropic", model, cls.value)

    # HYBRID -- the thesis's core claim: reading/uncritical roles stay local
    # (data sovereignty), risk-bearing roles get a frontier model.
    if cls is ModelClass.LOCAL_SMALL:
        return ModelChoice("ollama", settings.ollama_model_small, cls.value)
    return ModelChoice("anthropic", settings.cloud_model_frontier, cls.value)


class LLMClient(ABC):
    """The interface every agent sees. Provider-neutral."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    @abstractmethod
    def ask_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        """Returns the raw response as a JSON string.

        Deliberately *not* validated: validation belongs in
        `llm.extraction`, because the reaction to a schema violation is a
        business decision (retry, then escalate), not a transport concern.
        """


class OllamaClient(LLMClient):
    """Local model. No key, no cloud -- the data-sovereignty path.

    The prototype does not load models itself. It talks to an Ollama
    instance whose address is in .env (OLLAMA_BASE_URL) -- local or on the
    network. Which model is available there is decided outside this code
    (`ollama pull ...`). This keeps model provisioning out of the prototype,
    where it would not belong in a real deployment either.
    """

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
                    # cannot rely on that -- see R1 in docs/grenzen.md and
                    # the validation in llm/extraction.py.
                    "format": schema.model_json_schema(),
                    "stream": False,
                    # temperature 0: schema adherence over creativity.
                    "options": {"temperature": 0},
                },
                timeout=180.0,
            )
        except httpx.ConnectError as e:
            raise LLMUnreachable(
                f"Keine Verbindung zu Ollama unter {settings.ollama_base_url}. "
                "Laeuft der Dienst? Start: `ollama serve`. Adresse aendern: "
                "OLLAMA_BASE_URL in .env."
            ) from e
        except httpx.HTTPError as e:
            raise LLMUnreachable(f"Ollama-Transportfehler: {e}") from e

        # Ollama reports a missing model as a 404 -- that is a setup problem
        # and deserves an actionable message instead of a generic HTTP
        # error.
        if response.status_code == 404:
            raise LLMUnreachable(
                f"Modell {self.model_id!r} ist auf {settings.ollama_base_url} "
                f"nicht geladen. Laden mit: `ollama pull {self.model_id}` -- oder "
                "in .env ein anderes Modell eintragen "
                "(OLLAMA_MODEL_SMALL / OLLAMA_MODEL_VISION)."
            )
        if response.status_code != 200:
            raise LLMUnreachable(
                f"Ollama antwortete mit HTTP {response.status_code}: {response.text[:200]}"
            )

        return response.json()["message"]["content"]


class AnthropicClient(LLMClient):
    """Cloud frontier model for the risk-bearing roles."""

    def ask_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise LLMUnreachable("Paket 'anthropic' ist nicht installiert.") from e

        if not settings.anthropic_api_key:
            raise LLMUnreachable(
                "ANTHROPIC_API_KEY ist nicht gesetzt. Fuer den Offline-Betrieb "
                "MODEL_MODE=lokal in .env setzen."
            )

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        try:
            response = client.messages.parse(
                model=self.model_id,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except anthropic.APIError as e:
            raise LLMUnreachable(f"Anthropic-API-Fehler: {e}") from e

        if response.stop_reason == "refusal":
            raise LLMUnreachable(
                "Das Modell hat die Anfrage aus Sicherheitsgruenden abgelehnt."
            )

        # parsed_output is already validated; we still return JSON so that
        # both providers fulfill the same contract, and validation happens
        # in exactly one place.
        if response.parsed_output is not None:
            return response.parsed_output.model_dump_json()
        return next((b.text for b in response.content if b.type == "text"), "")


def client_for(agent_id: str) -> tuple[LLMClient, ModelChoice]:
    """Factory: returns the matching client for an agent."""
    choice = choose_model(agent_id)
    client_class = OllamaClient if choice.provider == "ollama" else AnthropicClient
    return client_class(choice.model_id), choice
