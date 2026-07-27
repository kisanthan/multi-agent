"""AD-/Entra-Mock: Nutzer-, Gruppen- und Rollenpruefung (Least Privilege).

Bildet die Eintrittsbedingung ins Reader-Tool ab: nur Mitglieder der
AD-Sicherheitsgruppe duerfen Dokumente einspeisen (Abschnitt 1 des
Fachkonzepts). Kein LLM -- eine Berechtigungspruefung, die ein Sprachmodell
"entscheidet", waere keine Berechtigungspruefung.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum

# Die Gruppe, deren Mitgliedschaft das Reader-Tool voraussetzt.
READER_GRUPPE = "SG-CHG-DocIngest"
# Die Gruppe, die Klaerfaelle und Kostenstellen-Zuordnungen freigeben darf.
FREIGABE_GRUPPE = "SG-CHG-Freigabe"


class Rolle(str, Enum):
    EINSPEISER = "einspeiser"
    PRUEFER = "pruefer"
    BEOBACHTER = "beobachter"


@dataclass(frozen=True)
class Nutzer:
    upn: str
    anzeigename: str
    rolle: Rolle
    gruppen: frozenset[str]

    def ist_mitglied(self, gruppe: str) -> bool:
        return gruppe in self.gruppen


class UnbekannterNutzer(Exception):
    """Ein UPN ohne AD-Eintrag.

    Bewusst eine Exception statt eines anonymen Default-Nutzers: Zero Trust
    heisst, dass ein unbekannter Akteur nicht stillschweigend als
    Minimalberechtigter durchlaeuft, sondern den Vorgang abbricht.
    """


def lade_nutzer(con: sqlite3.Connection, upn: str) -> Nutzer:
    row = con.execute(
        "SELECT upn, anzeigename, rolle FROM ad_nutzer WHERE upn = ?", (upn,)
    ).fetchone()
    if row is None:
        raise UnbekannterNutzer(f"Kein AD-Eintrag fuer {upn!r}")

    gruppen = {
        g[0] for g in con.execute(
            "SELECT gruppe FROM ad_mitgliedschaften WHERE upn = ?", (upn,)
        ).fetchall()
    }
    return Nutzer(upn=row[0], anzeigename=row[1], rolle=Rolle(row[2]),
                  gruppen=frozenset(gruppen))


@dataclass(frozen=True)
class ZugriffsErgebnis:
    erlaubt: bool
    begruendung: str
    nutzer: Nutzer | None = None


def pruefe_reader_zugriff(con: sqlite3.Connection, upn: str) -> ZugriffsErgebnis:
    """Eintrittsbedingung ins Reader-Tool (Szenario 5).

    Wird diese Pruefung verweigert, darf danach *nichts* mehr passieren: kein
    Parsing, kein LLM-Aufruf. Genau das prueft tests/test_szenario5.
    """
    try:
        nutzer = lade_nutzer(con, upn)
    except UnbekannterNutzer as e:
        return ZugriffsErgebnis(False, f"Zero Trust: {e}")

    if not nutzer.ist_mitglied(READER_GRUPPE):
        return ZugriffsErgebnis(
            False,
            f"{nutzer.anzeigename} ist nicht Mitglied der Sicherheitsgruppe "
            f"{READER_GRUPPE} (Least Privilege).",
            nutzer,
        )
    return ZugriffsErgebnis(
        True, f"{nutzer.anzeigename} ist Mitglied von {READER_GRUPPE}.", nutzer
    )


def pruefe_freigabe_berechtigung(con: sqlite3.Connection, upn: str) -> ZugriffsErgebnis:
    """Darf dieser Nutzer einen HITL-Freigabepunkt entscheiden?

    Vier-Augen-Prinzip: relevant fuer die Kostenstellen-Freigabe (Prozess B)
    und die Klaerfall-/Buchungsfreigabe (Prozess A).
    """
    try:
        nutzer = lade_nutzer(con, upn)
    except UnbekannterNutzer as e:
        return ZugriffsErgebnis(False, f"Zero Trust: {e}")

    if not nutzer.ist_mitglied(FREIGABE_GRUPPE):
        return ZugriffsErgebnis(
            False,
            f"{nutzer.anzeigename} ist nicht Mitglied von {FREIGABE_GRUPPE} "
            "und darf keine Freigaben erteilen.",
            nutzer,
        )
    return ZugriffsErgebnis(
        True, f"{nutzer.anzeigename} ist freigabeberechtigt.", nutzer
    )
