"""Tests der Listenfilter.

Dieselbe Datenquelle speist Upload-Seite, Historie und beide Prozessseiten --
sie unterscheiden sich nur im Filter. Was hier falsch ist, zeigt jede Seite
falsch an.
"""

from __future__ import annotations

from graph.vorgaenge import Status, Vorgangsuebersicht
from ui.shared import filter as filtern


def _zeile(**felder) -> Vorgangsuebersicht:
    standard = {
        "thread_id": "t1", "dateiname": "A_zahlung_ok_01.pdf",
        "akteur": "m.keller@chg-meridian.com", "status": Status.ABGESCHLOSSEN,
        "prozess": "A", "gestartet_am": "2026-07-30T12:00:00+00:00",
        "ergebnis": "verbucht", "freigegeben_von": None,
    }
    return Vorgangsuebersicht(**{**standard, **felder})


ZEILEN = [
    _zeile(thread_id="a", status=Status.WARTET_AUF_FREIGABE, prozess="A",
           gestartet_am="2026-07-30T12:00:00+00:00", ergebnis=None),
    _zeile(thread_id="b", status=Status.ABGESCHLOSSEN, prozess="B",
           dateiname="B_rechnung_ok_01.pdf", ergebnis="archiviert",
           gestartet_am="2026-07-29T09:00:00+00:00"),
    _zeile(thread_id="c", status=Status.LAEUFT, prozess=None,
           dateiname="unbekannt.pdf", ergebnis=None,
           gestartet_am="2026-07-28T08:00:00+00:00"),
]


def test_leerer_filter_liefert_alles():
    assert len(filtern.wende_an(ZEILEN, filtern.Filter())) == 3


def test_leerer_filter_erkennt_sich_selbst():
    assert filtern.Filter().ist_leer
    assert not filtern.Filter(suche="x").ist_leer


def test_sortierung_neueste_zuerst():
    ergebnis = filtern.wende_an(ZEILEN, filtern.Filter())
    assert [z.thread_id for z in ergebnis] == ["a", "b", "c"]


def test_suche_trifft_dateinamen():
    treffer = filtern.wende_an(ZEILEN, filtern.Filter(suche="rechnung"))
    assert [z.thread_id for z in treffer] == ["b"]


def test_suche_trifft_status_und_ergebnis():
    assert filtern.wende_an(ZEILEN, filtern.Filter(suche="archiviert"))
    assert filtern.wende_an(ZEILEN, filtern.Filter(suche="Wartet"))


def test_prozessfilter():
    treffer = filtern.wende_an(ZEILEN, filtern.Filter(prozesse=frozenset({"B"})))
    assert [z.thread_id for z in treffer] == ["b"]


def test_statusfilter():
    treffer = filtern.wende_an(
        ZEILEN, filtern.Filter(stati=frozenset({Status.LAEUFT})))
    assert [z.thread_id for z in treffer] == ["c"]


def test_zeitraum_schliesst_raender_ein():
    treffer = filtern.wende_an(
        ZEILEN, filtern.Filter(von="2026-07-29", bis="2026-07-30"))
    assert {z.thread_id for z in treffer} == {"a", "b"}


def test_vorgang_ohne_startzeit_wird_nie_weggefiltert():
    """Läufe aus älteren Ständen haben keinen Zeitstempel.

    Sie unsichtbar zu machen wäre schlimmer, als sie im Zeitraumfilter zu
    behalten -- der Nutzer würde sie schlicht nicht mehr finden.
    """
    alt = _zeile(thread_id="alt", gestartet_am="")
    treffer = filtern.wende_an([alt], filtern.Filter(von="2026-01-01", bis="2026-01-02"))
    assert [z.thread_id for z in treffer] == ["alt"]


def test_offene_zeigen_freigabepflichtige_zuerst():
    offen = filtern.offene(ZEILEN)
    assert [z.thread_id for z in offen] == ["a", "c"]


def test_abgeschlossene_enthalten_keine_offenen():
    assert [z.thread_id for z in filtern.abgeschlossene(ZEILEN)] == ["b"]


def test_fuer_prozess_grenzt_ein():
    assert [z.thread_id for z in filtern.fuer_prozess(ZEILEN, "A")] == ["a"]


def test_kennzahlen():
    zahlen = filtern.kennzahlen(ZEILEN)
    assert zahlen == {"offen": 1, "laeuft": 1, "abgeschlossen": 1,
                      "fehlgeschlagen": 0}


def test_kennzahlen_zaehlen_abgewiesene_als_nicht_erfolgreich():
    """Ein verweigerter AD-Check ist kein Erfolg -- aber auch kein offener Fall."""
    zeilen = [_zeile(status=Status.ABGEWIESEN, ergebnis="zugriff_verweigert")]
    assert filtern.kennzahlen(zeilen)["fehlgeschlagen"] == 1
