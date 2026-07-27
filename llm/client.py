"""Abstraktionsschicht ueber die Sprachmodelle.

Kapselt alle LLM-Aufrufe hinter einem Interface, damit pro Agent per Config
zwischen Cloud und lokal umgeschaltet werden kann. Das ist die technische
Entsprechung der Modellzuordnung nach Risikoklasse aus dem Konzeptdiagramm
`teil2_ki_modelle.png` und Grundlage fuer Unterfrage 2 der Arbeit (Datenhoheit
vs. Leistung).

Welches konkrete Modell ein Agent bekommt, ergibt sich aus zwei Angaben:
seiner Risikoklasse (registry.py) und dem Bereitstellungsmodus (.env). Kein
Agent kennt seinen Anbieter -- das ist der Punkt.

Modell-IDs und Preise Stand 17.07.2026 (wechseln quartalsweise).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel

from config import ModellModus, einstellungen
from registry import Modellklasse, konfiguration


class LLMNichtErreichbar(Exception):
    """Transportfehler -- kein inhaltliches Problem.

    Getrennt von einer Schemaverletzung, weil die Reaktion eine andere ist:
    ein nicht erreichbares Modell ist ein Betriebsproblem, eine Schemaverletzung
    ein Fall fuer die Freigabe-Queue.
    """


@dataclass(frozen=True)
class Modellwahl:
    anbieter: str   # 'ollama' | 'anthropic'
    modell_id: str
    risikoklasse: str


def waehle_modell(agent_id: str) -> Modellwahl:
    """Leitet die Modellwahl aus Risikoklasse (Registry) und Modus (.env) ab."""
    cfg = konfiguration(agent_id)
    klasse = cfg.modellklasse
    modus = einstellungen.modell_modus

    if klasse is Modellklasse.KEINE:
        raise ValueError(
            f"{cfg.name} ist kein KI-Agent (Typ {cfg.typ.value}) und darf kein "
            "Modell aufrufen."
        )

    if modus is ModellModus.LOKAL:
        modell = (einstellungen.ollama_modell_vision if klasse is Modellklasse.VISION
                  else einstellungen.ollama_modell_klein)
        return Modellwahl("ollama", modell, klasse.value)

    if modus is ModellModus.CLOUD:
        modell = (einstellungen.cloud_modell_klein if klasse is Modellklasse.LOKAL_KLEIN
                  else einstellungen.cloud_modell_frontier)
        return Modellwahl("anthropic", modell, klasse.value)

    # HYBRID -- die Kernaussage der Arbeit: lesende/unkritische Rollen bleiben
    # lokal (Datenhoheit), risikobehaftete Rollen bekommen ein Frontier-Modell.
    if klasse is Modellklasse.LOKAL_KLEIN:
        return Modellwahl("ollama", einstellungen.ollama_modell_klein, klasse.value)
    return Modellwahl("anthropic", einstellungen.cloud_modell_frontier, klasse.value)


class LLMClient(ABC):
    """Das Interface, das jeder Agent sieht. Anbieterneutral."""

    def __init__(self, modell_id: str) -> None:
        self.modell_id = modell_id

    @abstractmethod
    def frage_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        """Liefert die Rohantwort als JSON-String.

        Bewusst *nicht* validiert: die Validierung gehoert in
        `llm.extraktion`, weil die Reaktion auf eine Schemaverletzung eine
        fachliche Entscheidung ist (Retry, dann Eskalation) und keine des
        Transports.
        """


class OllamaClient(LLMClient):
    """Lokales Modell. Kein Key, keine Cloud -- der Datenhoheits-Pfad.

    Der Prototyp laedt keine Modelle. Er spricht eine Ollama-Instanz an, deren
    Adresse in .env steht (OLLAMA_BASE_URL) -- lokal oder im Netz. Welches
    Modell dort bereitsteht, wird ausserhalb entschieden (`ollama pull ...`).
    Das haelt die Modellbereitstellung aus dem Prototyp heraus, wo sie in einem
    realen Betrieb auch nicht laege.
    """

    def frage_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        import httpx

        try:
            antwort = httpx.post(
                f"{einstellungen.ollama_base_url}/api/chat",
                json={
                    "model": self.modell_id,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    # Ollama erzwingt das Schema ueber eine GBNF-Grammatik.
                    # Verlassen duerfen wir uns darauf nicht -- siehe R1 in
                    # docs/grenzen.md und die Validierung in llm/extraktion.py.
                    "format": schema.model_json_schema(),
                    "stream": False,
                    # temperature 0: Schema-Adhaerenz vor Kreativitaet.
                    "options": {"temperature": 0},
                },
                timeout=180.0,
            )
        except httpx.ConnectError as e:
            raise LLMNichtErreichbar(
                f"Keine Verbindung zu Ollama unter {einstellungen.ollama_base_url}. "
                "Laeuft der Dienst? Start: `ollama serve`. Adresse aendern: "
                "OLLAMA_BASE_URL in .env."
            ) from e
        except httpx.HTTPError as e:
            raise LLMNichtErreichbar(f"Ollama-Transportfehler: {e}") from e

        # Ollama meldet ein fehlendes Modell als 404 -- das ist ein
        # Einrichtungsproblem und verdient eine handlungsfaehige Meldung statt
        # eines generischen HTTP-Fehlers.
        if antwort.status_code == 404:
            raise LLMNichtErreichbar(
                f"Modell {self.modell_id!r} ist auf {einstellungen.ollama_base_url} "
                f"nicht geladen. Laden mit: `ollama pull {self.modell_id}` -- oder "
                "in .env ein anderes Modell eintragen "
                "(OLLAMA_MODELL_KLEIN / OLLAMA_MODELL_VISION)."
            )
        if antwort.status_code != 200:
            raise LLMNichtErreichbar(
                f"Ollama antwortete mit HTTP {antwort.status_code}: {antwort.text[:200]}"
            )

        return antwort.json()["message"]["content"]


class AnthropicClient(LLMClient):
    """Cloud-Frontier-Modell fuer die risikobehafteten Rollen."""

    def frage_json(self, *, system: str, prompt: str, schema: type[BaseModel]) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise LLMNichtErreichbar("Paket 'anthropic' ist nicht installiert.") from e

        if not einstellungen.anthropic_api_key:
            raise LLMNichtErreichbar(
                "ANTHROPIC_API_KEY ist nicht gesetzt. Fuer den Offline-Betrieb "
                "MODELL_MODUS=lokal in .env setzen."
            )

        client = anthropic.Anthropic(api_key=einstellungen.anthropic_api_key)
        try:
            antwort = client.messages.parse(
                model=self.modell_id,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except anthropic.APIError as e:
            raise LLMNichtErreichbar(f"Anthropic-API-Fehler: {e}") from e

        if antwort.stop_reason == "refusal":
            raise LLMNichtErreichbar(
                "Das Modell hat die Anfrage aus Sicherheitsgruenden abgelehnt."
            )

        # parsed_output ist bereits validiert; wir geben trotzdem JSON zurueck,
        # damit beide Anbieter denselben Vertrag erfuellen und die Validierung
        # an genau einer Stelle stattfindet.
        if antwort.parsed_output is not None:
            return antwort.parsed_output.model_dump_json()
        return next((b.text for b in antwort.content if b.type == "text"), "")


def client_fuer(agent_id: str) -> tuple[LLMClient, Modellwahl]:
    """Fabrik: liefert den passenden Client fuer einen Agenten."""
    wahl = waehle_modell(agent_id)
    client_klasse = OllamaClient if wahl.anbieter == "ollama" else AnthropicClient
    return client_klasse(wahl.modell_id), wahl
