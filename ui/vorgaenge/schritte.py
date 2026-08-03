"""Ableitung des Prozessfortschritts aus dem Laufprotokoll.

Der Stepper ist die Stelle, an der ein Betrachter den Ablauf abliest -- ein
falsch markierter Schritt behauptet etwas, das nicht passiert ist. Die
Ableitung ist deshalb von der Darstellung getrennt und liefert reine Daten.

*Welche* Schritte es gibt, steht nicht hier, sondern in `prozessregistry`.
Dieses Modul beantwortet nur: in welchem Zustand ist jeder davon?
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import prozessregistry
from graph.vorgaenge import Status
from prozessregistry import GEMEINSAME_SCHRITTE, Prozessschritt


class Schrittstatus(str, Enum):
    ERLEDIGT = "erledigt"
    AKTIV = "aktiv"
    OFFEN = "offen"
    UEBERSPRUNGEN = "uebersprungen"
    GESCHEITERT = "gescheitert"


@dataclass(frozen=True)
class Schritt:
    """Ein Prozessschritt mit seinem Zustand in einem konkreten Vorgang."""

    knoten: str
    titel: str
    agent_id: str | None
    status: Schrittstatus = Schrittstatus.OFFEN
    hinweis: str = ""


# Ordnet die Art eines Interrupts dem Schritt zu, an dem er haengt.
WARTEPUNKTE = {"klaerfall": "klaerfall", "kostenstellen_freigabe": "freigabe"}


def _rohschritte(prozess: str | None) -> tuple[Prozessschritt, ...]:
    """Steht der Prozess noch nicht fest, ist nur die gemeinsame Strecke bekannt."""
    if prozess is None:
        return GEMEINSAME_SCHRITTE
    return prozessregistry.konfiguration(prozess).schritte


def _schrittstatus(knoten: str, anzahl: dict[str, int], *, wartet_am: str | None,
                   status: Status | None, zielknoten: str) -> tuple[Schrittstatus, str]:
    """Regel je Knoten. Bewusst eine Regel pro Zeile statt einer Heuristik.

    Zwei Faelle verhalten sich nicht so, wie das blosse Vorkommen im Protokoll
    vermuten laesst, und bekommen eine eigene Regel:

    - Der **Buchungsknoten laeuft zweimal**: der erste Durchlauf meldet nur
      "Freigabe erforderlich" und schickt den Vorgang in den Klaerfall
      (graph/workflow.py::knoten_buchung). Ein Protokolleintrag allein ist also
      keine Verbuchung -- massgeblich ist das Gesamtergebnis.
    - Die **Freigabe in Prozess B wird uebersprungen**, wenn die Belegreferenz
      eindeutig aufloest. Das ist der Normalfall (Human-on-the-loop), kein
      ausgelassener Schritt.
    """
    if knoten == wartet_am:
        return Schrittstatus.AKTIV, "Wartet auf Entscheidung"

    gelaufen = anzahl.get(knoten, 0)
    fertig = status is Status.ABGESCHLOSSEN

    if knoten == "reader":
        if status is Status.ABGEWIESEN:
            return Schrittstatus.GESCHEITERT, "Zugriff verweigert"
        return (Schrittstatus.ERLEDIGT, "") if gelaufen else (Schrittstatus.OFFEN, "")

    # Der letzte Schritt traegt das Gesamtergebnis: er gilt genau dann als
    # erledigt, wenn der Vorgang erfolgreich abgeschlossen ist.
    if knoten == zielknoten:
        if fertig:
            return Schrittstatus.ERLEDIGT, ""
        if status is Status.FEHLGESCHLAGEN and gelaufen:
            return Schrittstatus.GESCHEITERT, "Zielsystem hat abgelehnt"
        return Schrittstatus.OFFEN, ""

    if knoten == "freigabe" and not gelaufen:
        if anzahl.get(zielknoten) or fertig:
            return (Schrittstatus.UEBERSPRUNGEN,
                    "Nicht nötig – die Kostenstelle war eindeutig")
        return Schrittstatus.OFFEN, ""

    if knoten == "klaerfall" and not gelaufen and fertig:
        return Schrittstatus.UEBERSPRUNGEN, ""

    return (Schrittstatus.ERLEDIGT, "") if gelaufen else (Schrittstatus.OFFEN, "")


def schritte_fuer(
    prozess: str | None,
    protokoll: list[dict],
    *,
    wartet_auf: str | None = None,
    status: Status | None = None,
) -> list[Schritt]:
    """Zustand jedes Prozessschritts.

    `wartet_auf` ist die Art des aktiven Interrupts, `status` der fachliche
    Gesamtstatus des Vorgangs.
    """
    anzahl: dict[str, int] = {}
    for eintrag in protokoll:
        knoten = eintrag.get("knoten", "")
        anzahl[knoten] = anzahl.get(knoten, 0) + 1

    rohschritte = _rohschritte(prozess)
    wartet_am = WARTEPUNKTE.get(wartet_auf or "")
    zielknoten = rohschritte[-1].knoten if prozess else ""

    return [
        Schritt(s.knoten, s.titel, s.agent_id,
                *_schrittstatus(s.knoten, anzahl, wartet_am=wartet_am,
                                status=status, zielknoten=zielknoten))
        for s in rohschritte
    ]
