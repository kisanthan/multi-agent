"""Central configuration, loaded from .env.

Lives at the top level and imports nothing from the project: both the
governance layer (amount thresholds) and the LLM layer (model selection)
read from here without creating a dependency between the two.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "masterdata.db"
CHECKPOINT_PATH = DATA_DIR / "checkpoints.sqlite"
INTAKE_DIR = DATA_DIR / "inbox"
MANIFEST_PATH = DATA_DIR / "manifest.json"
# Per-agent model overrides set live from the UI (ui/pages/models.py) --
# takes precedence over MODEL_MODE below. See llm/model_overrides.py.
MODEL_OVERRIDES_PATH = DATA_DIR / "model_overrides.json"


class UnknownSettingError(Exception):
    """A key in `.env` that no setting reads.

    Its own exception rather than pydantic's `extra="forbid"`: the useful
    thing to say here is not "extra input not permitted" but *which* name
    was meant instead.
    """


# The rename from German to English identifiers. A `.env` written before it
# is not partially valid -- it is inert: every key falls back to the default
# below while looking, from the outside, like a working configuration. The
# old names are kept here purely so the error can say "you meant X".
RENAMED_KEYS = {
    "BETRAG_TOLERANZ_EUR": "AMOUNT_TOLERANCE_EUR",
    "MODELL_MODUS": "MODEL_MODE",
    "OLLAMA_MODELL_KLEIN": "OLLAMA_MODEL_SMALL",
    "OLLAMA_MODELL_VISION": "OLLAMA_MODEL_VISION",
    "CLOUD_MODELL_FRONTIER": "CLOUD_MODEL_FRONTIER",
    "CLOUD_MODELL_KLEIN": "CLOUD_MODEL_SMALL",
}


class ModelMode(str, Enum):
    LOCAL = "lokal"
    HYBRID = "hybrid"
    CLOUD = "cloud"


class ReaderParser(str, Enum):
    PYMUPDF4LLM = "pymupdf4llm"
    DOCLING = "docling"


def _env_file_keys(path: Path) -> list[str]:
    """The assignment names in a `.env` file, in file order.

    A deliberately small parser: all this needs to know is what stands left
    of an `=`. Reading the file through pydantic-settings instead would mean
    asking the very layer that is being checked.
    """
    keys = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if key:
            keys.append(key)
    return keys


def check_env_file(path: Path, known: set[str]) -> None:
    """Refuses a `.env` carrying keys that no setting reads.

    Raises instead of warning, and checks the file rather than the process
    environment. Both follow from the failure this exists to prevent: an
    ignored key is indistinguishable from a correct one at runtime, and the
    place it hurts most is the Streamlit UI, where a warning on stderr is
    invisible. The OS environment is deliberately not checked -- it is full
    of names that have nothing to do with this project, and only the file is
    something a person wrote *for* it.
    """
    if not path.is_file():
        return

    unknown = [k for k in _env_file_keys(path) if k.upper() not in known]
    if not unknown:
        return

    lines = [f"{path.name}: Schluessel, die keine Einstellung liest -- "
             "sie wirken nicht, es greift jeweils der Standardwert."]
    for key in unknown:
        renamed = RENAMED_KEYS.get(key.upper())
        lines.append(f"  - {key}" + (f"   heisst jetzt: {renamed}" if renamed else ""))
    lines.append("")
    lines.append("Gueltige Namen stehen vollstaendig in .env.example.")
    raise UnknownSettingError("\n".join(lines))


class Settings(BaseSettings):
    # `extra="ignore"` stays: the process environment legitimately holds
    # names this class knows nothing about. Unknown keys in the *file* are a
    # different matter and are caught by check_env_file() below.
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Allowed deviation between the paid amount and the master-data amount
    # before an exception case is raised. The booking agent is always
    # human-in-the-loop regardless of the amount (Thesis §7.4) -- there is
    # deliberately no threshold for it.
    amount_tolerance_eur: float = 0.01

    model_mode: ModelMode = ModelMode.LOCAL
    ollama_base_url: str = "http://localhost:11434"
    ollama_model_small: str = "qwen3:8b"
    # llama3.2-vision:11b (the model named in the original functional
    # concept) failed to load in this project's own testing ("unknown model
    # architecture: mllama"); qwen2.5vl:7b is confirmed working -- see
    # docs/limitations.md.
    ollama_model_vision: str = "qwen2.5vl:7b"

    anthropic_api_key: str = ""
    # Model IDs as of 2026-07-17 (change quarterly -- see docs/limitations.md).
    cloud_model_frontier: str = "claude-opus-4-8"
    cloud_model_small: str = "claude-haiku-4-5"

    reader_parser: ReaderParser = ReaderParser.PYMUPDF4LLM

    navision_url: str = "http://localhost:8001"
    elo_url: str = "http://localhost:8002"


check_env_file(PROJECT_ROOT / ".env", {f.upper() for f in Settings.model_fields})

settings = Settings()
