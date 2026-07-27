"""Kostenstellen-Agent (Shared Domain, Stufe 2 = Vorschlag), Prozess B.

Ordnet eine Eingangsrechnung einer Kostenstelle zu. Nach Thesis §7.4 ist das ein
**exakter referenzieller Nachschlag** auf strukturierte Stammdaten: die auf dem
Beleg angegebene Kostenstellenreferenz wird gegen den Katalog abgeglichen -- kein
semantisches Matching, kein Sprachmodell.

Damit gilt fuer diesen Agenten dieselbe Begruendung wie fuer den Abgleich-Agenten
(vgl. agents/abgleich.py, docs/mapping.md I1): Rolle und Autonomiestufe bleiben
gueltig, die eigentliche Zuordnung ist aber ein deterministischer
Datenbankzugriff, kein Modellaufruf. Das Extrahieren der Referenz vom Beleg
leistet der vorgelagerte Klassifikations-/Extraktions-Agent.

"Zuordnung eindeutig?" (Diagramm Teil 3) heisst hier: die extrahierte Referenz
loest genau eine Kostenstelle auf. Fehlt die Referenz oder ist sie unbekannt,
ist die Zuordnung nicht eindeutig und geht als Klaerfall an den Menschen.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from enum import Enum

from governance.audit import Entscheidung, protokolliere

AGENT_ID = "kostenstelle"


class Befund(str, Enum):
    EINDEUTIG = "eindeutig"          # Referenz loest genau eine Kostenstelle auf
    KEINE_REFERENZ = "keine_referenz"  # Beleg nennt keine Referenz
    UNBEKANNTE_REFERENZ = "unbekannte_referenz"  # Referenz nicht im Katalog


@dataclass(frozen=True)
class Kostenstellenzuordnung:
    befund: Befund
    kostenstelle_id: str | None
    bezeichnung: str | None
    referenz: str | None
    begruendung: str

    @property
    def eindeutig(self) -> bool:
        return self.befund is Befund.EINDEUTIG


def normalisiere(referenz: str) -> str:
    """Bereinigt Zusatzzeichen aus der Markdown-Formatierung.

    Wie beim Abgleich-Agenten ist das eine Formatfrage, keine fachliche: der
    Parser liefert die Referenz gelegentlich als '**KTR-ITINFRA**'.
    """
    return re.sub(r"[^A-Z0-9-]", "", referenz.upper())


def ordne_zu(con: sqlite3.Connection, *, referenz: str | None, akteur: str,
             positionen: list[str] | None = None) -> Kostenstellenzuordnung:
    """Schlaegt die Kostenstellenreferenz exakt im Katalog nach. Nur Lesezugriff."""
    if not referenz:
        ergebnis = Kostenstellenzuordnung(
            Befund.KEINE_REFERENZ, None, None, None,
            "Der Beleg nennt keine Kostenstellenreferenz -- keine eindeutige "
            "Zuordnung moeglich.",
        )
        _protokolliere(con, akteur, ergebnis)
        return ergebnis

    norm = normalisiere(referenz)
    row = con.execute(
        "SELECT id, bezeichnung FROM kostenstellen WHERE referenz = ?", (norm,)
    ).fetchone()

    if row is None:
        ergebnis = Kostenstellenzuordnung(
            Befund.UNBEKANNTE_REFERENZ, None, None, norm,
            f"Referenz {norm} ist im Kostenstellenkatalog nicht vorhanden.",
        )
    else:
        ergebnis = Kostenstellenzuordnung(
            Befund.EINDEUTIG, row[0], row[1], norm,
            f"Referenz {norm} loest eindeutig auf {row[0]} ({row[1]}) auf.",
        )

    _protokolliere(con, akteur, ergebnis)
    return ergebnis


def katalog(con: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Liefert den Katalog (id, bezeichnung, referenz) fuer die Klaerfall-Anzeige."""
    return [
        (r[0], r[1], r[2])
        for r in con.execute(
            "SELECT id, bezeichnung, referenz FROM kostenstellen ORDER BY id"
        ).fetchall()
    ]


def existiert(con: sqlite3.Connection, kostenstelle_id: str | None) -> bool:
    """Prueft, ob eine (vom Menschen gewaehlte) Kostenstelle im Katalog ist."""
    if not kostenstelle_id:
        return False
    return con.execute("SELECT 1 FROM kostenstellen WHERE id = ?",
                       (kostenstelle_id,)).fetchone() is not None


def _protokolliere(con: sqlite3.Connection, akteur: str,
                   e: Kostenstellenzuordnung) -> None:
    protokolliere(
        con, akteur=akteur, agent=AGENT_ID, aktion="kostenstelle_zuordnen",
        entscheidung=Entscheidung.INFO, begruendung=e.begruendung,
        payload={"befund": e.befund.value, "kostenstelle_id": e.kostenstelle_id,
                 "referenz": e.referenz},
    )
    con.commit()
