"""Preflight: prueft die Modell-Bereitstellung, bevor ein Vorgang startet.

Der Prototyp laedt keine Modelle und startet keine Dienste -- er verbindet sich
gegen eine Ollama-Instanz, deren Adresse in .env steht. Diese Trennung ist
Absicht: die Modellbereitstellung ist Betrieb, nicht Anwendung. Dann muss die
Anwendung aber praezise sagen koennen, *was* fehlt, statt an einem
Verbindungsfehler zu sterben.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config import ModellModus, einstellungen
from llm.client import waehle_modell
from registry import REGISTRY, Modellklasse


@dataclass
class Befund:
    bereit: bool
    meldungen: list[str] = field(default_factory=list)
    benoetigte_modelle: list[str] = field(default_factory=list)
    verfuegbare_modelle: list[str] = field(default_factory=list)

    def bericht(self) -> str:
        kopf = "Modell-Bereitstellung: OK" if self.bereit else "Modell-Bereitstellung: NICHT BEREIT"
        return "\n".join([kopf, *(f"  - {m}" for m in self.meldungen)])


def benoetigte_modelle() -> list[str]:
    """Welche Modelle braucht die aktuelle Konfiguration?

    Leitet sich aus der Registry ab: nur Agenten mit Modellklasse != KEINE
    rufen ueberhaupt ein Modell auf.
    """
    ids = set()
    for agent_id, cfg in REGISTRY.items():
        if cfg.modellklasse is Modellklasse.KEINE:
            continue
        wahl = waehle_modell(agent_id)
        if wahl.anbieter == "ollama":
            ids.add(wahl.modell_id)
    return sorted(ids)


def pruefe() -> Befund:
    """Prueft Erreichbarkeit und geladene Modelle. Laedt selbst nichts."""
    modus = einstellungen.modell_modus

    if modus is ModellModus.CLOUD:
        if not einstellungen.anthropic_api_key:
            return Befund(False, ["MODELL_MODUS=cloud, aber ANTHROPIC_API_KEY ist leer."])
        return Befund(True, ["Cloud-Modus, API-Key vorhanden."])

    noetig = benoetigte_modelle()
    if not noetig:
        return Befund(True, ["Keine lokalen Modelle noetig."])

    import httpx

    url = einstellungen.ollama_base_url
    try:
        antwort = httpx.get(f"{url}/api/tags", timeout=5.0)
        antwort.raise_for_status()
    except httpx.HTTPError as e:
        return Befund(
            False,
            [f"Ollama unter {url} nicht erreichbar ({type(e).__name__}).",
             "Dienst starten: `ollama serve`",
             "Andere Adresse: OLLAMA_BASE_URL in .env setzen.",
             f"Benoetigte Modelle: {', '.join(noetig)}"],
            benoetigte_modelle=noetig,
        )

    verfuegbar = [m["name"] for m in antwort.json().get("models", [])]
    # Ollama fuehrt Tags als 'name:tag'; ein Eintrag ohne Tag meint ':latest'.
    normalisiert = {n.split(":")[0] if n.endswith(":latest") else n for n in verfuegbar}

    fehlend = [m for m in noetig if m not in verfuegbar and m not in normalisiert]
    if fehlend:
        return Befund(
            False,
            [f"Ollama unter {url} erreichbar.",
             f"Nicht geladen: {', '.join(fehlend)}",
             *[f"Laden mit: `ollama pull {m}`" for m in fehlend],
             f"Verfuegbar waeren: {', '.join(verfuegbar) or '(keine)'}",
             "Alternativ in .env ein vorhandenes Modell eintragen "
             "(OLLAMA_MODELL_KLEIN / OLLAMA_MODELL_VISION)."],
            benoetigte_modelle=noetig, verfuegbare_modelle=verfuegbar,
        )

    if modus is ModellModus.HYBRID and not einstellungen.anthropic_api_key:
        return Befund(
            False,
            [f"Ollama unter {url} bereit ({', '.join(noetig)}).",
             "MODELL_MODUS=hybrid verlangt zusaetzlich ANTHROPIC_API_KEY fuer die "
             "risikobehafteten Agenten (Buchung, Navision, Klassifikation).",
             "Fuer reinen Offline-Betrieb: MODELL_MODUS=lokal setzen."],
            benoetigte_modelle=noetig, verfuegbare_modelle=verfuegbar,
        )

    return Befund(
        True,
        [f"Ollama unter {url} erreichbar.",
         f"Modelle geladen: {', '.join(noetig)}"],
        benoetigte_modelle=noetig, verfuegbare_modelle=verfuegbar,
    )
