"""Tests der Vorgangsuebersicht.

`status_von` und `prozess_von` sind die Grundlage der Fallliste in der
Oberflaeche. Sie sind rein gehalten, damit genau das hier ohne LangGraph und
ohne Streamlit pruefbar ist.
"""

from __future__ import annotations

from graph.vorgaenge import Status, prozess_von, status_von


def test_wartender_vorgang_ist_freigabepflichtig():
    """Ein aktiver Interrupt ist die staerkste Aussage ueber den Status."""
    assert status_von({}, wartet=True) is Status.WARTET_AUF_FREIGABE


def test_interrupt_schlaegt_alten_ergebniswert():
    """Nach einer Teilstrecke steht evtl. noch ein alter Wert im Zustand.

    Der Vorgang haengt trotzdem am Freigabepunkt -- sonst wuerde die Queue ihn
    nicht anzeigen und niemand koennte ihn fortsetzen.
    """
    werte = {"abgeschlossen": True, "ergebnis": "verbucht"}
    assert status_von(werte, wartet=True) is Status.WARTET_AUF_FREIGABE


def test_laufender_vorgang():
    assert status_von({"typ": "eingangsrechnung"}, wartet=False) is Status.LAEUFT


def test_verbuchte_zahlung_ist_abgeschlossen():
    werte = {"abgeschlossen": True, "ergebnis": "verbucht"}
    assert status_von(werte, wartet=False) is Status.ABGESCHLOSSEN


def test_archivierte_rechnung_ist_abgeschlossen():
    """Prozess B endet bei ELO -- das ist ein vollwertiger Abschluss."""
    werte = {"abgeschlossen": True, "ergebnis": "archiviert"}
    assert status_von(werte, wartet=False) is Status.ABGESCHLOSSEN


def test_verworfener_vorgang():
    werte = {"abgeschlossen": True, "ergebnis": "verworfen"}
    assert status_von(werte, wartet=False) is Status.VERWORFEN


def test_ad_check_verweigert_ist_eigener_status():
    """Szenario 5 ist kein Fehlschlag, sondern eine wirksame Governance-Regel."""
    werte = {"abgeschlossen": True, "ergebnis": "zugriff_verweigert"}
    assert status_von(werte, wartet=False) is Status.ABGEWIESEN


def test_zielsystem_ablehnung_ist_fehlgeschlagen():
    werte = {"abgeschlossen": True, "ergebnis": "abgelehnt"}
    assert status_von(werte, wartet=False) is Status.FEHLGESCHLAGEN


def test_unbekanntes_ergebnis_gilt_nicht_als_erfolg():
    """Default deny auch in der Anzeige: nichts Unerwartetes wird gruen."""
    werte = {"abgeschlossen": True, "ergebnis": "voellig_neuer_wert"}
    assert status_von(werte, wartet=False) is Status.FEHLGESCHLAGEN


def test_offene_stati():
    assert Status.LAEUFT.ist_offen
    assert Status.WARTET_AUF_FREIGABE.ist_offen
    assert not Status.ABGESCHLOSSEN.ist_offen
    assert not Status.ABGEWIESEN.ist_offen


def test_prozesszuordnung_nach_dokumenttyp():
    assert prozess_von({"typ": "zahlungsbestaetigung"}) == "A"
    assert prozess_von({"typ": "eingangsrechnung"}) == "B"


def test_prozess_steht_vor_der_klassifikation_nicht_fest():
    """Auf der gemeinsamen Ingestionsstrecke gehoert der Vorgang keinem Prozess."""
    assert prozess_von({}) is None
    assert prozess_von({"typ": "unbekannt"}) is None
