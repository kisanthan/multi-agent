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
DB_PATH = DATA_DIR / "stammdaten.db"
CHECKPOINT_PATH = DATA_DIR / "checkpoints.sqlite"
INTAKE_DIR = DATA_DIR / "eingang"
MANIFEST_PATH = DATA_DIR / "manifest.json"


class ModelMode(str, Enum):
    LOCAL = "lokal"
    HYBRID = "hybrid"
    CLOUD = "cloud"


class ReaderParser(str, Enum):
    PYMUPDF4LLM = "pymupdf4llm"
    DOCLING = "docling"


class Settings(BaseSettings):
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
    # docs/grenzen.md.
    ollama_model_vision: str = "qwen2.5vl:7b"

    anthropic_api_key: str = ""
    # Model IDs as of 2026-07-17 (change quarterly -- see docs/grenzen.md).
    cloud_model_frontier: str = "claude-opus-4-8"
    cloud_model_small: str = "claude-haiku-4-5"

    reader_parser: ReaderParser = ReaderParser.PYMUPDF4LLM

    navision_url: str = "http://localhost:8001"
    elo_url: str = "http://localhost:8002"


settings = Settings()
