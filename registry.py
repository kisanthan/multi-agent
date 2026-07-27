"""Agenten-Konfigurationstabelle des Fachkonzepts als wirksame Datenstruktur.

Dieses Modul liegt bewusst auf oberster Ebene und nicht in `agents/`: sowohl die
Agenten als auch die Governance-Schicht lesen daraus, und `governance/` darf
nicht von `agents/` abhaengen (siehe tests/test_schichtgrenze.py). Die Tabelle
ist reine Konfiguration ohne Verhalten und ohne LLM-Bezug.

Autonomiestufen nach Parasuraman et al. (2000); Aufsichtsmodi nach Kap. 2.2 der
Arbeit. Eine Aenderung hier aendert das Laufzeitverhalten -- die Tabelle ist
nicht Dokumentation, sondern Durchsetzung.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentTyp(str, Enum):
    """Funktionstypen aus Kap. 2.2 / 3.3 / 3.4.

    Personal Agents kommen in diesen beiden Prozessen nicht vor; alle fachlichen
    Agenten sind Shared Domain Agents. Einen `System Agent` als Funktionstyp
    gibt es in der Typologie der Arbeit nicht.
    """

    SHARED_DOMAIN = "Shared Domain"
    ORCHESTRATOR = "Orchestrator"
    POLICY = "Policy-Governance"
    AUDIT = "Audit-Monitoring"
    KEIN_AGENT = "kein Agent (deterministisch)"


class Autonomiestufe(int, Enum):
    """Nach Parasuraman et al. (2000), Auspraegung gemaess Kap. 3.4."""

    LESEZUGRIFF = 1
    VORSCHLAG = 2
    REVERSIBLES_SCHREIBEN = 3
    IRREVERSIBLE_AKTION = 4


class Aufsichtsmodus(str, Enum):
    """Aufsichtsmodi nach Kap. 2.2."""

    HUMAN_LED = "Human-led"
    HUMAN_IN_THE_LOOP = "Human-in-the-loop"
    HUMAN_ON_THE_LOOP = "Human-on-the-loop"
    VOLLAUTOMATISIERT = "vollautomatisiert"
    DETERMINISTISCH = "deterministisch (kein LLM)"
    READ_ONLY = "read-only"


class Modellklasse(str, Enum):
    """Modellzuordnung nach Risiko (Konzeptdiagramm `teil2_ki_modelle.png`).

    Die konkreten Modell-IDs stehen in llm/config.py -- hier steht nur die
    Risikoklasse, damit die Zuordnung eine Architekturaussage bleibt und keine
    Abhaengigkeit zu einem Anbieter.
    """

    KEINE = "kein Modell"
    LOKAL_KLEIN = "lokal/klein"
    VISION = "vision-faehig"
    FRONTIER = "Frontier"


@dataclass(frozen=True)
class AgentKonfiguration:
    name: str
    typ: AgentTyp
    autonomiestufe: Autonomiestufe | None
    aufsicht: Aufsichtsmodus
    modellklasse: Modellklasse
    prozesse: tuple[str, ...]
    darf_schreiben: bool
    beschreibung: str


# Die Tabelle aus Abschnitt 1 des Fachkonzepts, 1:1.
REGISTRY: dict[str, AgentKonfiguration] = {
    "reader": AgentKonfiguration(
        name="Reader-Tool",
        typ=AgentTyp.KEIN_AGENT,
        autonomiestufe=None,
        aufsicht=Aufsichtsmodus.DETERMINISTISCH,
        modellklasse=Modellklasse.KEINE,
        prozesse=("A", "B"),
        darf_schreiben=False,
        beschreibung="PDF -> Markdown. Kein KI-Agent. Zugriff nur fuer Mitglieder "
        "der AD-Sicherheitsgruppe (Least Privilege).",
    ),
    "orchestrator": AgentKonfiguration(
        name="Orchestrator-Agent",
        typ=AgentTyp.ORCHESTRATOR,
        autonomiestufe=None,
        aufsicht=Aufsichtsmodus.HUMAN_ON_THE_LOOP,
        modellklasse=Modellklasse.LOKAL_KLEIN,
        prozesse=("A", "B"),
        darf_schreiben=False,
        beschreibung="Routet nach Dokumenttyp und steuert den Workflow.",
    ),
    "klassifikation": AgentKonfiguration(
        name="Klassifikations- & Extraktions-Agent",
        typ=AgentTyp.SHARED_DOMAIN,
        # Tabelle nennt "1-2"; massgeblich ist die Obergrenze, weil die Policy
        # gegen die hoechste beanspruchte Stufe prueft.
        autonomiestufe=Autonomiestufe.VORSCHLAG,
        aufsicht=Aufsichtsmodus.HUMAN_ON_THE_LOOP,
        modellklasse=Modellklasse.VISION,
        prozesse=("A", "B"),
        darf_schreiben=False,
        beschreibung="Bestimmt in einem Durchgang Dokumenttyp UND extrahiert die "
        "relevanten Felder.",
    ),
    "abgleich": AgentKonfiguration(
        name="Abgleich-Agent",
        typ=AgentTyp.SHARED_DOMAIN,
        autonomiestufe=Autonomiestufe.LESEZUGRIFF,
        aufsicht=Aufsichtsmodus.HUMAN_ON_THE_LOOP,
        modellklasse=Modellklasse.LOKAL_KLEIN,
        prozesse=("A",),
        darf_schreiben=False,
        beschreibung="Gleicht die extrahierte Rechnungs-/Bestellnummer gegen die "
        "Stammdatenbasis ab. Nur Lesezugriff.",
    ),
    "buchung": AgentKonfiguration(
        name="Buchungs-Agent",
        typ=AgentTyp.SHARED_DOMAIN,
        autonomiestufe=Autonomiestufe.REVERSIBLES_SCHREIBEN,
        # Offene fachliche Festlegung: schwellenwertabhaengig. Der hier
        # hinterlegte Modus ist der Default unterhalb der Schwelle; oberhalb
        # eskaliert governance.policy auf Human-in-the-loop.
        aufsicht=Aufsichtsmodus.HUMAN_ON_THE_LOOP,
        modellklasse=Modellklasse.FRONTIER,
        prozesse=("A",),
        darf_schreiben=True,
        beschreibung="Verbucht die Zahlung im ERP, Status offen -> bezahlt. "
        "Oberhalb BUCHUNG_SCHWELLE_EUR freigabepflichtig.",
    ),
    "kostenstelle": AgentKonfiguration(
        name="Kostenstellen-Agent",
        typ=AgentTyp.SHARED_DOMAIN,
        autonomiestufe=Autonomiestufe.VORSCHLAG,
        # Diagramm Teil 3: Human-on-the-loop. Bei eindeutiger Zuordnung laeuft
        # der Vorgang automatisch weiter; nur bei Mehrdeutigkeit greift die
        # Vier-Augen-Freigabe (Klaerfall). Spiegelt Prozess A.
        aufsicht=Aufsichtsmodus.HUMAN_ON_THE_LOOP,
        modellklasse=Modellklasse.LOKAL_KLEIN,
        prozesse=("B",),
        darf_schreiben=False,
        beschreibung="Schlaegt anhand der Kostenstellen-Referenz eine Kostenstelle "
        "vor. Bei Mehrdeutigkeit Vier-Augen-Freigabe durch einen Menschen.",
    ),
    "elo": AgentKonfiguration(
        name="ELO-Agent",
        typ=AgentTyp.SHARED_DOMAIN,
        autonomiestufe=Autonomiestufe.REVERSIBLES_SCHREIBEN,
        aufsicht=Aufsichtsmodus.HUMAN_ON_THE_LOOP,
        modellklasse=Modellklasse.LOKAL_KLEIN,
        prozesse=("B",),
        darf_schreiben=True,
        beschreibung="Archiviert die Rechnung revisionssicher im DMS. "
        "Prozessende von Prozess B (Diagramm Teil 3).",
    ),
    "policy": AgentKonfiguration(
        name="Policy-/Governance-Komponente",
        typ=AgentTyp.POLICY,
        autonomiestufe=None,
        aufsicht=Aufsichtsmodus.DETERMINISTISCH,
        modellklasse=Modellklasse.KEINE,
        prozesse=("A", "B"),
        darf_schreiben=False,
        beschreibung="Deterministisches RBAC/ABAC-Enforcement. Kein LLM.",
    ),
    "audit": AgentKonfiguration(
        name="Audit-/Monitoring-Komponente",
        typ=AgentTyp.AUDIT,
        autonomiestufe=None,
        aufsicht=Aufsichtsmodus.READ_ONLY,
        modellklasse=Modellklasse.KEINE,
        prozesse=("A", "B"),
        darf_schreiben=False,
        beschreibung="Manipulationsgeschuetzter, hash-verketteter Audit-Trail.",
    ),
}


def konfiguration(agent_id: str) -> AgentKonfiguration:
    """Liefert die Konfiguration eines Agenten.

    Ein unbekannter Agent ist ein Programmierfehler, kein Laufzeitfall: die
    Policy darf niemals gegen eine geratene Default-Konfiguration pruefen.
    """
    try:
        return REGISTRY[agent_id]
    except KeyError:
        raise KeyError(
            f"Unbekannter Agent {agent_id!r}. Bekannt: {sorted(REGISTRY)}"
        ) from None
