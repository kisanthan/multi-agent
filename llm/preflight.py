"""Preflight: checks model availability before a case starts.

The prototype does not load models and does not start services -- it
connects to an Ollama instance whose address is in .env. This separation is
deliberate: model provisioning is operations, not application. But then the
application must be able to say precisely *what* is missing, instead of
dying on a connection error.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_registry import REGISTRY, ModelClass
from config import ModelMode, settings
from llm.client import choose_model


@dataclass
class Readiness:
    ready: bool
    messages: list[str] = field(default_factory=list)
    required_models: list[str] = field(default_factory=list)
    available_models: list[str] = field(default_factory=list)

    def report(self) -> str:
        head = "Modell-Bereitstellung: OK" if self.ready else "Modell-Bereitstellung: NICHT BEREIT"
        return "\n".join([head, *(f"  - {m}" for m in self.messages)])


def required_models() -> list[str]:
    """Which models does the current configuration need?

    Derived from the registry: only agents with model_class != NO_MODEL
    call a model at all.
    """
    ids = set()
    for agent_id, cfg in REGISTRY.items():
        if cfg.model_class is ModelClass.NO_MODEL:
            continue
        choice = choose_model(agent_id)
        if choice.provider == "ollama":
            ids.add(choice.model_id)
    return sorted(ids)


def check() -> Readiness:
    """Checks reachability and loaded models. Loads nothing itself."""
    mode = settings.model_mode

    if mode is ModelMode.CLOUD:
        if not settings.anthropic_api_key:
            return Readiness(False, ["MODEL_MODE=cloud, aber ANTHROPIC_API_KEY ist leer."])
        return Readiness(True, ["Cloud-Modus, API-Key vorhanden."])

    needed = required_models()
    if not needed:
        return Readiness(True, ["Keine lokalen Modelle noetig."])

    import httpx

    url = settings.ollama_base_url
    try:
        response = httpx.get(f"{url}/api/tags", timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as e:
        return Readiness(
            False,
            [f"Ollama unter {url} nicht erreichbar ({type(e).__name__}).",
             "Dienst starten: `ollama serve`",
             "Andere Adresse: OLLAMA_BASE_URL in .env setzen.",
             f"Benoetigte Modelle: {', '.join(needed)}"],
            required_models=needed,
        )

    available = [m["name"] for m in response.json().get("models", [])]
    # Ollama lists tags as 'name:tag'; an entry without a tag means ':latest'.
    normalized = {n.split(":")[0] if n.endswith(":latest") else n for n in available}

    missing = [m for m in needed if m not in available and m not in normalized]
    if missing:
        return Readiness(
            False,
            [f"Ollama unter {url} erreichbar.",
             f"Nicht geladen: {', '.join(missing)}",
             *[f"Laden mit: `ollama pull {m}`" for m in missing],
             f"Verfuegbar waeren: {', '.join(available) or '(keine)'}",
             "Alternativ in .env ein vorhandenes Modell eintragen "
             "(OLLAMA_MODEL_SMALL / OLLAMA_MODEL_VISION)."],
            required_models=needed, available_models=available,
        )

    if mode is ModelMode.HYBRID and not settings.anthropic_api_key:
        return Readiness(
            False,
            [f"Ollama unter {url} bereit ({', '.join(needed)}).",
             "MODEL_MODE=hybrid verlangt zusaetzlich ANTHROPIC_API_KEY fuer die "
             "risikobehafteten Agenten (Buchung, Navision, Klassifikation).",
             "Fuer reinen Offline-Betrieb: MODEL_MODE=lokal setzen."],
            required_models=needed, available_models=available,
        )

    return Readiness(
        True,
        [f"Ollama unter {url} erreichbar.",
         f"Modelle geladen: {', '.join(needed)}"],
        required_models=needed, available_models=available,
    )
