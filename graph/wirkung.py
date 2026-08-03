"""Wirkung eines abgeschlossenen Vorgangs im Zielsystem.

Der eigentliche Nachweis eines Laufs ist nicht das Protokoll, sondern der
veraenderte Zustand im Zielsystem: die Rechnung steht in Navision auf
'bezahlt', das Dokument liegt in ELO unter einer Archiv-ID. CLI und UI muessen
denselben Nachweis zeigen -- deshalb liegt die Abfrage hier und nicht in
`demo.py` oder in der Oberflaeche.

Reine Leseabfrage: dieses Modul veraendert nichts und ruft kein Modell auf.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Wirkung:
    """Was der Vorgang im Zielsystem hinterlassen hat.

    Alle Felder sind optional, weil ein Vorgang je nach Prozess und Ausgang nur
    eines der Zielsysteme beruehrt -- oder keines (Szenario 5: der AD-Check
    verweigert vor jedem Zugriff).
    """

    navision_nummer: str | None = None
    navision_status: str | None = None
    navision_bezahlt_am: str | None = None
    elo_archiv_id: str | None = None
    elo_abgelegt_am: str | None = None

    @property
    def hat_wirkung(self) -> bool:
        return bool(self.navision_status or self.elo_archiv_id)


def lies_wirkung(con: sqlite3.Connection, zustand: dict) -> Wirkung:
    """Liest den Zielsystemzustand zu einem Vorgang.

    Bewusst tolerant: eine Nummer, die nicht in den Stammdaten steht (Szenario
    'unbekannte Nummer'), ist ein regulaerer fachlicher Fall und darf hier
    keinen Fehler ausloesen -- sie liefert schlicht keinen Navision-Status.
    """
    nummer = zustand.get("nummer")
    navision_status = navision_bezahlt_am = None
    if nummer:
        row = con.execute(
            "SELECT status, bezahlt_am FROM rechnungen WHERE nummer = ?", (nummer,)
        ).fetchone()
        if row:
            navision_status, navision_bezahlt_am = row

    archiv_id = zustand.get("archiv_id")
    abgelegt_am = None
    if archiv_id:
        row = con.execute(
            "SELECT abgelegt_am FROM archiv WHERE archiv_id = ?", (archiv_id,)
        ).fetchone()
        if row:
            abgelegt_am = row[0]

    return Wirkung(
        navision_nummer=nummer if navision_status else None,
        navision_status=navision_status,
        navision_bezahlt_am=navision_bezahlt_am,
        elo_archiv_id=archiv_id,
        elo_abgelegt_am=abgelegt_am,
    )
