"""Kostenstellen-Agent (Shared Domain, Stufe 2 = Vorschlag), Prozess B.

Schlaegt anhand der Kostenstellen-Referenz eine Kostenstelle vor. Stufe 2
heisst: er schlaegt vor und fuehrt nichts aus. Die Zuordnung wird erst durch
einen Menschen wirksam (Vier-Augen-Prinzip, Human-in-the-loop) -- das ist der
einzige Agent im System, dessen Aufsichtsmodus *immer* eine Freigabe verlangt,
unabhaengig von Betraegen.

Hier ist ein Sprachmodell fachlich begruendet -- anders als beim Abgleich-Agenten
(siehe dort): die Zuordnung von Freitext-Rechnungspositionen zu Kostenstellen
ist eine semantische Aufgabe, die sich nicht als exakte Abfrage formulieren
laesst.
"""

from __future__ import annotations

import sqlite3

from agents.schemas import Kostenstellenvorschlag
from llm.extraktion import Extraktionsergebnis, extrahiere

AGENT_ID = "kostenstelle"

SYSTEM = """Du ordnest Rechnungspositionen einer Kostenstelle der CHG-MERIDIAN zu.

Regeln:
- Waehle nur aus dem vorgegebenen Katalog. Erfinde keine IDs.
- Treffen Positionen auf Schluesselwoerter mehrerer Kostenstellen zu, ist die \
Zuordnung NICHT eindeutig: setze eindeutig=false und nenne alle plausiblen IDs \
in alternativen.
- Lieber mehrdeutig melden als falsch zuordnen. Ein Mensch entscheidet ohnehin.
- Antworte nur mit JSON nach dem Schema."""


def _katalog(con: sqlite3.Connection) -> str:
    zeilen = con.execute(
        "SELECT id, bezeichnung, schluesselwoerter FROM kostenstellen ORDER BY id"
    ).fetchall()
    return "\n".join(f"- {i} | {b} | Schluesselwoerter: {s}" for i, b, s in zeilen)


def schlage_vor(con: sqlite3.Connection, *, lieferant: str | None,
                positionen: list[str], akteur: str) -> Extraktionsergebnis:
    """Schlaegt eine Kostenstelle vor. Fuehrt nichts aus (Stufe 2)."""
    pos_text = "\n".join(f"- {p}" for p in positionen) or "(keine Positionen erkannt)"
    prompt = (
        f"Kostenstellen-Katalog:\n{_katalog(con)}\n\n"
        f"Lieferant: {lieferant or 'unbekannt'}\n"
        f"Rechnungspositionen:\n{pos_text}\n\n"
        "Welche Kostenstelle trifft zu?"
    )
    return extrahiere(con, agent_id=AGENT_ID, akteur=akteur, system=SYSTEM,
                      prompt=prompt, schema=Kostenstellenvorschlag)


def ist_gueltig(con: sqlite3.Connection, kostenstelle_id: str | None) -> bool:
    """Prueft den Vorschlag gegen den Katalog.

    Das Modell koennte eine plausibel aussehende, aber nicht existente ID
    liefern -- das Schema erzwingt nur den Typ, nicht die Existenz.
    """
    if not kostenstelle_id:
        return False
    return con.execute("SELECT 1 FROM kostenstellen WHERE id = ?",
                       (kostenstelle_id,)).fetchone() is not None
