"""Abgleich-Agent (Shared Domain, Stufe 1 = Lesezugriff), Prozess A.

Gleicht die extrahierte Rechnungs-/Bestellnummer gegen die gemeinsame
Stammdatenbasis ab und entscheidet, ob ein Klaerfall vorliegt.

ABWEICHUNG VOM FACHKONZEPT -- bewusst und dokumentiert (docs/mapping.md):
Die Konfigurationstabelle weist diesem Agenten ein (kleines, lokales) Modell
zu. Der Abgleich ist jedoch eine Suche ueber einen Primaerschluessel. Ein
Sprachmodell koennte hier nichts beitragen, was SQL nicht exakt und
reproduzierbar leistet -- es koennte nur halluzinieren. Der Prototyp
implementiert den Abgleich daher deterministisch.

Das ist selbst ein Befund fuer die Arbeit: die Agenten-Typologie sagt, *welche
Rolle* eine Komponente hat und *welche Autonomiestufe* sie braucht -- daraus
folgt nicht automatisch, dass Modellinferenz noetig ist. Autonomiestufe 1
(Lesezugriff) und Aufsichtsmodus bleiben unveraendert gueltig; nur die
Modellzuordnung entfaellt.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from enum import Enum

from config import einstellungen
from governance.audit import OHNE_BEZUG, Entscheidung, Vorgangsbezug, protokolliere

AGENT_ID = "abgleich"


class Befund(str, Enum):
    OK = "ok"                          # Nummer bekannt, offen, Betrag plausibel
    UNBEKANNT = "unbekannt"            # Nummer nicht in den Stammdaten
    BEREITS_BEZAHLT = "bereits_bezahlt"  # Dublette
    BETRAG_ABWEICHEND = "betrag_abweichend"
    KEINE_NUMMER = "keine_nummer"      # Extraktion lieferte keine Nummer


@dataclass(frozen=True)
class Abgleichergebnis:
    befund: Befund
    nummer: str | None
    soll_betrag_eur: float | None
    ist_betrag_eur: float | None
    begruendung: str

    @property
    def ist_klaerfall(self) -> bool:
        return self.befund is not Befund.OK


def normalisiere(nummer: str) -> str:
    """Vereinheitlicht Schreibweisen vor dem Vergleich.

    Der Parser liefert die Nummer gelegentlich mit Zusatzzeichen aus der
    Markdown-Formatierung ('**RE-2026-4200**') oder mit Leerzeichen. Das ist
    eine Formatfrage, keine fachliche -- sie hier zu bereinigen ist etwas
    anderes als unscharf zu raten, welche Rechnung gemeint sein koennte.
    """
    return re.sub(r"[^A-Z0-9-]", "", nummer.upper())


def gleiche_ab(con: sqlite3.Connection, *, nummer: str | None, betrag_eur: float | None,
               akteur: str, bezug: Vorgangsbezug = OHNE_BEZUG) -> Abgleichergebnis:
    """Prueft die Nummer gegen die Stammdaten. Nur Lesezugriff."""
    if not nummer:
        ergebnis = Abgleichergebnis(
            Befund.KEINE_NUMMER, None, None, betrag_eur,
            "Im Dokument wurde keine Rechnungs-/Bestellnummer gefunden.",
        )
        _protokolliere(con, akteur, ergebnis, bezug)
        return ergebnis

    norm = normalisiere(nummer)
    row = con.execute(
        "SELECT nummer, betrag_eur, status FROM rechnungen WHERE nummer = ?", (norm,)
    ).fetchone()

    if row is None:
        ergebnis = Abgleichergebnis(
            Befund.UNBEKANNT, norm, None, betrag_eur,
            f"Nummer {norm} ist in den Stammdaten nicht vorhanden.",
        )
    elif row[2] == "bezahlt":
        ergebnis = Abgleichergebnis(
            Befund.BEREITS_BEZAHLT, norm, row[1], betrag_eur,
            f"Nummer {norm} ist bereits als bezahlt erfasst (moegliche Dublette).",
        )
    elif (betrag_eur is not None
          and abs(row[1] - betrag_eur) > einstellungen.betrag_toleranz_eur):
        ergebnis = Abgleichergebnis(
            Befund.BETRAG_ABWEICHEND, norm, row[1], betrag_eur,
            f"Zahlbetrag {betrag_eur:.2f} EUR weicht vom Stammdatenbetrag "
            f"{row[1]:.2f} EUR ab.",
        )
    else:
        ergebnis = Abgleichergebnis(
            Befund.OK, norm, row[1], betrag_eur,
            f"Nummer {norm} gefunden, Status offen, Betrag stimmt ueberein.",
        )

    _protokolliere(con, akteur, ergebnis, bezug)
    return ergebnis


def _protokolliere(con: sqlite3.Connection, akteur: str, e: Abgleichergebnis,
                   bezug: Vorgangsbezug = OHNE_BEZUG) -> None:
    protokolliere(
        con, akteur=akteur, agent=AGENT_ID, aktion="nummer_abgleichen",
        entscheidung=Entscheidung.INFO, begruendung=e.begruendung,
        payload={"befund": e.befund.value, "nummer": e.nummer,
                 "soll_betrag_eur": e.soll_betrag_eur, "ist_betrag_eur": e.ist_betrag_eur},
        bezug=bezug, ergebnis=e.befund.value,
    )
    con.commit()
