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
from config import ModelMode, ProfileId, Provider, settings
from llm.client import LLMUnreachable, choose_model, choose_profile, list_models


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


def check_profile(profile_id: ProfileId | str) -> Readiness:
    """Check one effective profile without making a billable model request."""
    choice = choose_profile(profile_id)
    try:
        available = list_models(choice.provider)
    except LLMUnreachable as e:
        return Readiness(False, [str(e)], required_models=[choice.model_id])
    normalized = {n.split(":")[0] if n.endswith(":latest") else n for n in available}
    present = choice.model_id in available or choice.model_id in normalized
    if not present:
        return Readiness(
            False,
            [f"Verbindung steht, Modell {choice.model_id!r} wurde aber nicht gefunden."],
            required_models=[choice.model_id], available_models=available,
        )
    return Readiness(
        True, [f"{choice.provider}: {choice.model_id} ist verfügbar."],
        required_models=[choice.model_id], available_models=available,
    )


def check_profiles() -> dict[ProfileId, Readiness]:
    return {profile_id: check_profile(profile_id) for profile_id in ProfileId}


def check() -> Readiness:
    """Checks reachability and loaded models. Loads nothing itself."""
    if any(getattr(settings, f"llm_{p.value}_provider") is not None for p in ProfileId):
        checks = check_profiles()
        return Readiness(
            all(result.ready for result in checks.values()),
            [f"{profile.value}: {message}"
             for profile, result in checks.items() for message in result.messages],
            required_models=[m for result in checks.values() for m in result.required_models],
            available_models=sorted({m for result in checks.values()
                                     for m in result.available_models}),
        )
    mode = settings.model_mode

    if mode is ModelMode.CLOUD:
        if not settings.anthropic_api_key:
            return Readiness(False, ["MODEL_MODE=cloud, aber ANTHROPIC_API_KEY ist leer."])
        return Readiness(True, ["Cloud-Modus, API-Key vorhanden."])

    needed = required_models()
    if not needed:
        if mode is ModelMode.HYBRID:
            if not settings.anthropic_api_key:
                return Readiness(False, ["MODEL_MODE=hybrid, aber ANTHROPIC_API_KEY ist leer."])
            return Readiness(True, ["Hybrid-Modus: alle aktiven Modellprofile laufen in der Cloud."])
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
