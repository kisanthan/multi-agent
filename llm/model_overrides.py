"""Per-agent model overrides, set live from the UI.

`agent_registry.py`'s risk class and `.env`'s `MODEL_MODE` (see
`llm/client.py::choose_model`) decide a *default* -- the thesis's role- and
risk-based claim stays intact. This module adds one more layer on top: an
operator can point one specific agent (orchestrator, classification,
booking, archiving) at a specific local or cloud model, live, without
touching `.env` or restarting. An override always wins over the default.

Pure configuration I/O, no Streamlit import, no LLM dependency -- same
layering as `agent_registry.py`/`process_registry.py`, so it can be read
from the UI, `demo.py`, and tests alike.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from agent_registry import REGISTRY, ModelClass
from config import MODEL_OVERRIDES_PATH

OVERRIDABLE_PROVIDERS = ("ollama", "anthropic")


@dataclass(frozen=True)
class ModelOverride:
    provider: str
    model_id: str


def load_overrides() -> dict[str, ModelOverride]:
    """Reads the override file. Missing file = no overrides, not an error."""
    if not MODEL_OVERRIDES_PATH.is_file():
        return {}
    raw = json.loads(MODEL_OVERRIDES_PATH.read_text(encoding="utf-8"))
    return {agent_id: ModelOverride(**fields) for agent_id, fields in raw.items()}


def _write(overrides: dict[str, ModelOverride]) -> None:
    MODEL_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_OVERRIDES_PATH.write_text(
        json.dumps({k: asdict(v) for k, v in overrides.items()},
                  indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_override(agent_id: str, provider: str, model_id: str) -> None:
    """Sets or replaces one agent's override.

    Rejects what would silently do nothing at call time: an unknown agent, a
    model-less agent (reader/policy/audit/abgleich/kostenstelle never call a
    model at all -- see `agent_registry.ModelClass.NO_MODEL`), an unsupported
    provider, or an empty model id.
    """
    if agent_id not in REGISTRY:
        raise KeyError(f"Unknown agent {agent_id!r}. Known: {sorted(REGISTRY)}")
    if REGISTRY[agent_id].model_class is ModelClass.NO_MODEL:
        raise ValueError(
            f"{REGISTRY[agent_id].name} ruft kein Sprachmodell auf -- "
            "kein Modell zum Ueberschreiben."
        )
    if provider not in OVERRIDABLE_PROVIDERS:
        raise ValueError(f"Unbekannter Anbieter {provider!r}. "
                         f"Erlaubt: {OVERRIDABLE_PROVIDERS}")
    if not model_id.strip():
        raise ValueError("Modell-ID darf nicht leer sein.")

    overrides = load_overrides()
    overrides[agent_id] = ModelOverride(provider, model_id.strip())
    _write(overrides)


def clear_override(agent_id: str) -> None:
    """Removes an agent's override, if any -- falls back to the default."""
    overrides = load_overrides()
    if agent_id in overrides:
        del overrides[agent_id]
        _write(overrides)
