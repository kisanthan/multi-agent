"""Klassifikations- & Extraktions-Agent (Shared Domain, Stufe 1-2).

Bestimmt in einem Durchgang den Dokumenttyp UND extrahiert die relevanten
Felder -- so im Fachkonzept vorgegeben. Zwei getrennte Aufrufe waeren teurer
und koennten sich widersprechen (Typ 'Rechnung', aber Felder einer
Zahlungsbestaetigung).

Autonomiestufe 2: schlaegt vor, fuehrt nichts aus. Der Agent schreibt nirgends
hin -- das erzwingt die Policy (test_policy.py).
"""

from __future__ import annotations

import sqlite3

from agents.schemas import Klassifikation
from governance.audit import OHNE_BEZUG, Vorgangsbezug
from llm.extraktion import Extraktionsergebnis, extrahiere

AGENT_ID = "klassifikation"

SYSTEM = """Du bist ein Extraktionsagent fuer Finanzdokumente eines deutschen \
IT-Leasing-Unternehmens (CHG-MERIDIAN). Du liest ein Dokument als Markdown und \
gibst ausschliesslich strukturiertes JSON nach dem vorgegebenen Schema zurueck.

Regeln:
- Erfinde nichts. Steht ein Wert nicht im Dokument, gib null zurueck.
- Deutsche Zahlenschreibweise: '1.341,96' ist 1341.96 -- der Punkt trennt \
Tausender, das Komma die Dezimalstellen.
- Eine Zahlungsbestaetigung stammt von einer Bank und bestaetigt eine bereits \
erfolgte Zahlung; die Belegnummer steht meist im Verwendungszweck.
- Eine Eingangsrechnung stammt von einem Lieferanten und fordert Zahlung; sie \
hat Positionen.
- Antworte nur mit JSON, ohne erklaerenden Text."""


def klassifiziere(con: sqlite3.Connection, *, markdown: str, akteur: str,
                  bezug: Vorgangsbezug = OHNE_BEZUG) -> Extraktionsergebnis:
    """Klassifiziert und extrahiert. Eskaliert bei Schemaverletzung (R1)."""
    prompt = (
        "Klassifiziere das folgende Dokument und extrahiere die Felder.\n\n"
        "--- DOKUMENT ---\n"
        f"{markdown}\n"
        "--- ENDE ---"
    )
    return extrahiere(con, agent_id=AGENT_ID, akteur=akteur, system=SYSTEM,
                      prompt=prompt, schema=Klassifikation, bezug=bezug)
