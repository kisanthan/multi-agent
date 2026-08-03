"""Filtern und Sortieren von Vorgangslisten.

Reine Funktionen ueber `Vorgangsuebersicht`-Zeilen: kein Streamlit, keine
Datenbank. Die Filterleiste in der Oberflaeche sammelt nur die Eingaben ein und
ruft `wende_an()` -- damit ist das Verhalten ohne laufende App pruefbar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from graph.vorgaenge import Status, Vorgangsuebersicht

SEITENGROESSE = 25


@dataclass(frozen=True)
class Filter:
    """Die Auswahl des Nutzers. Leere Felder bedeuten 'nicht einschraenken'."""

    suche: str = ""
    prozesse: frozenset[str] = field(default_factory=frozenset)
    stati: frozenset[Status] = field(default_factory=frozenset)
    von: str = ""      # ISO-Datum, einschliesslich
    bis: str = ""      # ISO-Datum, einschliesslich
    neueste_zuerst: bool = True

    @property
    def ist_leer(self) -> bool:
        return not (self.suche or self.prozesse or self.stati or self.von or self.bis)


def _passt_suche(zeile: Vorgangsuebersicht, begriff: str) -> bool:
    if not begriff:
        return True
    heuhaufen = " ".join([
        zeile.dateiname, zeile.akteur, zeile.status.beschriftung,
        zeile.ergebnis or "", zeile.freigegeben_von or "",
    ]).lower()
    return begriff.lower().strip() in heuhaufen


def _passt_zeitraum(zeile: Vorgangsuebersicht, von: str, bis: str) -> bool:
    """Vergleicht auf Tagesebene.

    ISO-Zeitstempel sind lexikografisch sortierbar, deshalb genuegt ein
    Stringvergleich der ersten zehn Zeichen. Vorgaenge ohne Startzeitpunkt
    (Laeufe aus aelteren Ständen) werden von einem Zeitraumfilter nie
    ausgeschlossen -- sonst verschwaenden sie unerklaerlich.
    """
    tag = (zeile.gestartet_am or "")[:10]
    if not tag:
        return True
    if von and tag < von:
        return False
    if bis and tag > bis:
        return False
    return True


def wende_an(zeilen: list[Vorgangsuebersicht], f: Filter) -> list[Vorgangsuebersicht]:
    """Filtert und sortiert. Aendert die Eingabeliste nicht."""
    treffer = [
        z for z in zeilen
        if _passt_suche(z, f.suche)
        and (not f.prozesse or z.prozess in f.prozesse)
        and (not f.stati or z.status in f.stati)
        and _passt_zeitraum(z, f.von, f.bis)
    ]
    return sorted(treffer, key=lambda z: z.gestartet_am or "",
                  reverse=f.neueste_zuerst)


def offene(zeilen: list[Vorgangsuebersicht]) -> list[Vorgangsuebersicht]:
    """Aktive Vorgaenge -- freigabepflichtige zuerst, denn sie brauchen jemanden."""
    aktiv = [z for z in zeilen if z.status.ist_offen]
    return sorted(aktiv, key=lambda z: z.status is not Status.WARTET_AUF_FREIGABE)


def abgeschlossene(zeilen: list[Vorgangsuebersicht]) -> list[Vorgangsuebersicht]:
    return [z for z in zeilen if not z.status.ist_offen]


def fuer_prozess(zeilen: list[Vorgangsuebersicht],
                 schluessel: str) -> list[Vorgangsuebersicht]:
    return [z for z in zeilen if z.prozess == schluessel]


def kennzahlen(zeilen: list[Vorgangsuebersicht]) -> dict[str, int]:
    """Zaehlwerte fuer die Kennzahlenzeile einer Seite."""
    return {
        "offen": sum(1 for z in zeilen if z.status is Status.WARTET_AUF_FREIGABE),
        "laeuft": sum(1 for z in zeilen if z.status is Status.LAEUFT),
        "abgeschlossen": sum(1 for z in zeilen if z.status is Status.ABGESCHLOSSEN),
        "fehlgeschlagen": sum(
            1 for z in zeilen
            if z.status in (Status.FEHLGESCHLAGEN, Status.ABGEWIESEN)
        ),
    }
