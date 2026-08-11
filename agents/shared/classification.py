"""Classification & extraction agent (Shared Domain, level 1-2).

Determines the document type AND extracts the relevant fields in a single
pass -- as required by the functional concept. Two separate calls would be
more expensive and could contradict each other (type 'invoice', but fields
of a payment confirmation).

Autonomy level 2: proposes, executes nothing. The agent writes nowhere --
the policy enforces that (test_policy.py).
"""

from __future__ import annotations

import sqlite3

from agents.schemas import Classification
from governance.audit import NO_REFERENCE, CaseReference
from llm.extraction import ExtractionResult, extract

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


def classify(con: sqlite3.Connection, *, markdown: str, actor: str,
             reference: CaseReference = NO_REFERENCE) -> ExtractionResult:
    """Classifies and extracts. Escalates on a schema violation (R1)."""
    prompt = (
        "Klassifiziere das folgende Dokument und extrahiere die Felder.\n\n"
        "--- DOKUMENT ---\n"
        f"{markdown}\n"
        "--- ENDE ---"
    )
    return extract(con, agent_id=AGENT_ID, actor=actor, system=SYSTEM,
                   prompt=prompt, schema=Classification, reference=reference)
