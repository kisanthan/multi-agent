"""Zentrale Konfiguration aus .env.

Liegt auf oberster Ebene und importiert nichts aus dem Projekt: sowohl die
Governance-Schicht (Betragsschwellen) als auch die LLM-Schicht (Modellwahl)
lesen daraus, ohne dass dadurch eine Abhaengigkeit zwischen beiden entsteht.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJEKT_WURZEL = Path(__file__).parent
DATA_DIR = PROJEKT_WURZEL / "data"
DB_PFAD = DATA_DIR / "stammdaten.db"
CHECKPOINT_PFAD = DATA_DIR / "checkpoints.sqlite"
EINGANG_DIR = DATA_DIR / "eingang"
MANIFEST_PFAD = DATA_DIR / "manifest.json"


class ModellModus(str, Enum):
    LOKAL = "lokal"
    HYBRID = "hybrid"
    CLOUD = "cloud"


class ReaderParser(str, Enum):
    PYMUPDF4LLM = "pymupdf4llm"
    DOCLING = "docling"


class Einstellungen(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJEKT_WURZEL / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Offene fachliche Festlegung (Buchungs-Agent, Prozess A): unterhalb der
    # Schwelle Human-on-the-loop, oberhalb Human-in-the-loop. Konfigurierbar,
    # damit die Arbeit beide Varianten demonstrieren kann statt eine zu setzen.
    buchung_schwelle_eur: float = 10_000.0
    betrag_toleranz_eur: float = 0.01

    modell_modus: ModellModus = ModellModus.LOKAL
    ollama_base_url: str = "http://localhost:11434"
    ollama_modell_klein: str = "qwen3:8b"
    ollama_modell_vision: str = "llama3.2-vision:11b"

    anthropic_api_key: str = ""
    # Modell-IDs Stand 17.07.2026 (wechseln quartalsweise -- siehe docs/grenzen.md).
    cloud_modell_frontier: str = "claude-opus-4-8"
    cloud_modell_klein: str = "claude-haiku-4-5"

    reader_parser: ReaderParser = ReaderParser.PYMUPDF4LLM

    navision_url: str = "http://localhost:8001"
    elo_url: str = "http://localhost:8002"


einstellungen = Einstellungen()
