"""Was der angemeldete Mensch darf -- in Worten, die er versteht.

Die Governance-Schicht antwortet praezise und technisch: „X ist nicht Mitglied
der Sicherheitsgruppe SG-CHG-Freigabe (Least Privilege)". Das ist als
Audit-Eintrag genau richtig und als Bildschirmtext unbrauchbar.

Dieses Modul ist die Uebersetzungsschicht dazwischen. Es entscheidet nichts --
die Regeln bleiben in `governance/` -- es formuliert nur, was sie bedeuten, und
welche Hinweise auf welcher Seite ueberhaupt sinnvoll sind.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import prozessregistry
from governance import ad
from ui.shared.formate import aufzaehlung, mehrzahl


@dataclass(frozen=True)
class Benutzer:
    """Der angemeldete Mensch aus Sicht der Oberflaeche."""

    upn: str
    anzeigename: str
    darf_hochladen: bool
    darf_bestaetigen: bool

    @property
    def nur_ansicht(self) -> bool:
        return not (self.darf_hochladen or self.darf_bestaetigen)

    @property
    def faehigkeiten(self) -> str:
        """Ein Satz statt zweier Haekchen -- und mit den Belegarten im Klartext.

        „Sie können Belege hochladen" laesst offen, *welche*. Die Antwort steht
        in der Prozessregistry und wird hier ausgeschrieben, damit niemand erst
        durch Ausprobieren herausfindet, was das System annimmt.
        """
        arten = aufzaehlung([mehrzahl(a) for a in prozessregistry.belegarten()],
                           verbinder="oder")

        if self.darf_hochladen and self.darf_bestaetigen:
            return (f"Sie können {arten} hochladen und Vorgänge bestätigen.")
        if self.darf_hochladen:
            return f"Sie können {arten} hochladen."
        if self.darf_bestaetigen:
            return ("Sie können Vorgänge bestätigen, aber keine Belege "
                    "hochladen.")
        return "Sie können Vorgänge ansehen, aber keine Belege hochladen."

    @property
    def rechte_kurz(self) -> str:
        """Kurzform fuers Abzeichen -- knapp und handlungsbezogen.

        Bewusst OHNE Belegarten: die gehoeren in den ausfuehrlichen Satz
        (`faehigkeiten`), nicht ins Abzeichen. Zwei Gruende dagegen, sie hier
        zu wiederholen:

        1. Redundanz -- der Satz sagt es bereits vollstaendig.
        2. Laenge -- jedes andere Abzeichen im System (Vorgangsstatus wie
           "Abgeschlossen" oder "Wartet auf Bestätigung") ist ein bis drei
           Woerter lang. Eine Belegartenliste plus Verb sprengt dieses Muster.

        Was hier zaehlt, ist die Handlung: "Hochladen" und "Bestätigen" sind
        fachlich sehr unterschiedliche Rechte (Vier-Augen-Trennung) und muessen
        im Abzeichen selbst unterscheidbar bleiben.
        """
        if self.darf_hochladen and self.darf_bestaetigen:
            return "Beides"
        if self.darf_hochladen:
            return "Hochladen"
        if self.darf_bestaetigen:
            return "Bestätigen"
        return "Nur lesen"

    @property
    def label_offene(self) -> str:
        """Kennzahl-Beschriftung fuer wartende Vorgaenge.

        Fuer eine berechtigte Person ist die Zahl eine Aufgabenliste, fuer alle
        anderen eine Statusangabe. Dasselbe Wort fuer beides waere entweder
        eine falsche Aufforderung oder eine verschenkte.
        """
        return ("Warten auf Ihre Bestätigung" if self.darf_bestaetigen
                else "Warten auf Bestätigung")

    # --- Begruendungen fuer gesperrte Aktionen -----------------------------
    # Immer nach demselben Muster: was geht nicht, und was tut man dagegen.
    # Nie mit dem Namen einer Sicherheitsgruppe -- der hilft niemandem weiter,
    # der sie nicht ohnehin verwalten kann.

    @property
    def hinweis_hochladen(self) -> str:
        arten = aufzaehlung([mehrzahl(a) for a in prozessregistry.belegarten()],
                            verbinder="oder")
        return (f"Ihr Konto ist nicht berechtigt, {arten} hochzuladen. "
                "Wenden Sie sich an Ihre IT, wenn Sie diese Berechtigung "
                "benötigen.")

    @property
    def hinweis_bestaetigen(self) -> str:
        return ("Diesen Vorgang kann nur eine dafür berechtigte Person "
                "bestätigen. Ihr Konto hat diese Berechtigung nicht.")

    @property
    def hinweis_eigener_beleg(self) -> str:
        return ("Sie haben diesen Beleg selbst hochgeladen. Vorgesehen ist, "
                "dass eine zweite Person ihn bestätigt.")


def lade(con: sqlite3.Connection, upn: str) -> Benutzer:
    """Baut den Benutzerkontext aus dem Verzeichnisdienst.

    Ein unbekanntes Konto ist kein Fehler, sondern ein Konto ohne Rechte --
    die Oberflaeche soll es anzeigen koennen, statt abzustuerzen.
    """
    try:
        nutzer = ad.lade_nutzer(con, upn)
        anzeigename = nutzer.anzeigename
    except ad.UnbekannterNutzer:
        anzeigename = upn

    return Benutzer(
        upn=upn,
        anzeigename=anzeigename,
        darf_hochladen=ad.pruefe_reader_zugriff(con, upn).erlaubt,
        darf_bestaetigen=ad.pruefe_freigabe_berechtigung(con, upn).erlaubt,
    )
