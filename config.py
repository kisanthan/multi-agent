"""Central, reloadable application configuration.

Non-secret and secret runtime settings live in the local ``.env`` file.  The
settings page updates only keys it owns, validates the complete candidate
configuration first, and replaces the file atomically.  The singleton object
is then updated in place so modules which imported ``settings`` see the change
without an application restart.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "masterdata.db"
CHECKPOINT_PATH = DATA_DIR / "checkpoints.sqlite"
INTAKE_DIR = DATA_DIR / "inbox"
MANIFEST_PATH = DATA_DIR / "manifest.json"
ENV_PATH = PROJECT_ROOT / ".env"


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
    """Legacy deployment mode kept for existing ``.env`` files and CLI use."""

    LOCAL = "lokal"
    HYBRID = "hybrid"
    CLOUD = "cloud"


class Provider(str, Enum):
    OLLAMA = "ollama"
    GOOGLE = "google"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class AuthMethod(str, Enum):
    NONE = "keine"
    API_KEY = "api_key"
    OAUTH = "oauth"
    PROFILE = "profil"


class ProfileId(str, Enum):
    ROUTER = "router"
    PAYMENT = "payment"
    INVOICE = "invoice"


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


@dataclass(frozen=True)
class ModelProfile:
    profile_id: ProfileId
    provider: Provider
    model_id: str
    auth_method: AuthMethod

    def as_dict(self) -> dict[str, str]:
        return {k: (v.value if isinstance(v, Enum) else v)
                for k, v in asdict(self).items()}


class Settings(BaseSettings):
    # `extra="ignore"` stays: the process environment legitimately holds
    # names this class knows nothing about. Unknown keys in the *file* are a
    # different matter and are caught by check_env_file() below.
    model_config = SettingsConfigDict(
        env_file=ENV_PATH, env_file_encoding="utf-8", extra="ignore"
    )

    amount_tolerance_eur: float = 0.01
    reader_parser: ReaderParser = ReaderParser.PYMUPDF4LLM
    navision_url: str = "http://localhost:8001"
    elo_url: str = "http://localhost:8002"

    # Legacy settings. They remain readable so an existing installation does
    # not suddenly change model routing after the feature update.
    model_mode: ModelMode = ModelMode.LOCAL
    ollama_base_url: str = "http://localhost:11434"
    ollama_model_small: str = "qwen3:8b"
    ollama_model_vision: str = "qwen2.5vl:7b"
    cloud_model_frontier: str = "claude-opus-4-8"
    cloud_model_small: str = "claude-haiku-4-5"

    # Provider connections are central and reused by every model profile.
    anthropic_api_key: str = ""
    anthropic_auth_method: AuthMethod = AuthMethod.API_KEY
    anthropic_profile: str = "default"
    openai_api_key: str = ""
    google_api_key: str = ""
    google_auth_method: AuthMethod = AuthMethod.API_KEY
    google_cloud_project: str = ""
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_refresh_token: str = ""

    # Empty provider/model pairs deliberately mean "derive from MODEL_MODE".
    # That is the compatibility bridge for existing .env files.
    llm_router_provider: Provider | None = None
    llm_router_model: str = ""
    llm_payment_provider: Provider | None = None
    llm_payment_model: str = ""
    llm_invoice_provider: Provider | None = None
    llm_invoice_model: str = ""
    configuration_revision: int = 1

    @field_validator("amount_tolerance_eur")
    @classmethod
    def non_negative_tolerance(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Die Betragstoleranz darf nicht negativ sein.")
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def valid_ollama_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("Die Ollama-Adresse muss mit http:// oder https:// beginnen.")
        return value

    @model_validator(mode="after")
    def complete_profile_pairs(self) -> "Settings":
        """An explicit provider and model are one indivisible profile value."""
        for profile_id in ProfileId:
            provider = getattr(self, f"llm_{profile_id.value}_provider")
            model_id = getattr(self, f"llm_{profile_id.value}_model").strip()
            if (provider is None) != (not model_id):
                raise ValueError(
                    f"Profil {profile_id.value}: Anbieter und Modell-ID müssen "
                    "gemeinsam gesetzt oder gemeinsam leer sein."
                )
        if self.anthropic_auth_method not in {AuthMethod.API_KEY, AuthMethod.PROFILE}:
            raise ValueError("Anthropic unterstützt API-Key oder Workspace-Profil.")
        if self.google_auth_method not in {AuthMethod.API_KEY, AuthMethod.OAUTH}:
            raise ValueError("Google unterstützt API-Key oder OAuth.")
        return self

    def _legacy_profile(self, profile_id: ProfileId) -> ModelProfile:
        if self.model_mode is ModelMode.LOCAL:
            return ModelProfile(profile_id, Provider.OLLAMA,
                                self.ollama_model_vision, AuthMethod.NONE)
        # The former classifier was the only actual LLM call in cloud and
        # hybrid mode and used the frontier model. Preserve that behavior for
        # all newly split extraction profiles until the user saves them.
        return ModelProfile(profile_id, Provider.ANTHROPIC,
                            self.cloud_model_frontier, self.anthropic_auth_method)

    def profile(self, profile_id: ProfileId | str) -> ModelProfile:
        profile_id = ProfileId(profile_id)
        provider = getattr(self, f"llm_{profile_id.value}_provider")
        model_id = getattr(self, f"llm_{profile_id.value}_model").strip()
        if provider is None or not model_id:
            return self._legacy_profile(profile_id)
        auth = {
            Provider.OLLAMA: AuthMethod.NONE,
            Provider.GOOGLE: self.google_auth_method,
            Provider.ANTHROPIC: self.anthropic_auth_method,
            Provider.OPENAI: AuthMethod.API_KEY,
        }[provider]
        return ModelProfile(profile_id, provider, model_id, auth)

    def profile_snapshot(self) -> dict[str, dict[str, str]]:
        snapshot = {p.value: self.profile(p).as_dict() for p in ProfileId}
        for profile in snapshot.values():
            profile["configuration_revision"] = str(self.configuration_revision)
        return snapshot


check_env_file(PROJECT_ROOT / ".env", {f.upper() for f in Settings.model_fields})

settings = Settings()


SECRET_FIELDS = frozenset({
    "anthropic_api_key", "openai_api_key", "google_api_key",
    "google_oauth_client_secret", "google_oauth_refresh_token",
})


def masked(value: str) -> str:
    """A status indicator, never a recoverable representation of a secret."""
    if not value:
        return "Nicht hinterlegt"
    return f"Hinterlegt (endet auf …{value[-4:]})" if len(value) >= 4 else "Hinterlegt"


def _serialize_env(value: Any) -> str:
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return ""
    if isinstance(value, bool):
        value = "true" if value else "false"
    return json.dumps(str(value), ensure_ascii=False)


def _patch_env_text(original: str, values: Mapping[str, Any]) -> str:
    """Replace managed keys while preserving comments, order and unknown keys."""
    pending = {key.upper(): _serialize_env(value) for key, value in values.items()}
    output: list[str] = []
    for line in original.splitlines():
        stripped = line.lstrip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if key in pending and key and not stripped.startswith("#"):
            output.append(f"{key}={pending.pop(key)}")
        else:
            output.append(line)
    if pending:
        if output and output[-1].strip():
            output.append("")
        output.append("# ---- Managed through the settings page -----------------------------")
        output.extend(f"{key}={value}" for key, value in pending.items())
    return "\n".join(output).rstrip() + "\n"


def save_settings(updates: Mapping[str, Any]) -> Settings:
    """Validate, atomically persist, and activate a set of field updates."""
    unknown = set(updates) - set(Settings.model_fields)
    if unknown:
        raise KeyError(f"Unbekannte Einstellungen: {sorted(unknown)}")

    candidate_values = settings.model_dump()
    candidate_values.update(updates)
    candidate_values["configuration_revision"] = settings.configuration_revision + 1
    candidate = Settings(**candidate_values)

    env_updates = {name.upper(): getattr(candidate, name) for name in updates}
    env_updates["CONFIGURATION_REVISION"] = candidate.configuration_revision
    original = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    content = _patch_env_text(original, env_updates)

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=ENV_PATH.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, ENV_PATH)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    for name, value in candidate.model_dump().items():
        setattr(settings, name, value)
    return settings
