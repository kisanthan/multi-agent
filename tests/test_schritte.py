"""Tests der Prozessdarstellung.

Der Stepper ist die Stelle, an der ein Betrachter den Ablauf abliest -- ein
falsch markierter Schritt behauptet etwas, das nicht passiert ist. Besonders
heikel: der Buchungsknoten laeuft zweimal (erst "Freigabe erforderlich", dann
der echte Versuch), und Prozess B ueberspringt die Freigabe im Normalfall.
"""

from __future__ import annotations

from graph.vorgaenge import Status
from ui.shared.formate import euro, zeitpunkt
from ui.vorgaenge.schritte import Schrittstatus, schritte_fuer


def _nach_knoten(schritte):
    return {s.knoten: s.status for s in schritte}


def _protokoll(*knoten: str) -> list[dict]:
    return [{"knoten": k, "text": "-"} for k in knoten]


# ------------------------------------------------------------- Prozess A

def test_prozess_a_wartet_auf_buchungsfreigabe():
    """Nach dem ersten Buchungsversuch haengt der Vorgang am Freigabepunkt.

    Der Buchungsschritt darf hier NICHT als erledigt gelten -- gebucht wurde
    noch nichts, der Knoten hat nur die Freigabe angefordert.
    """
    schritte = schritte_fuer(
        "A", _protokoll("reader", "klassifikation", "abgleich", "buchung"),
        wartet_auf="klaerfall", status=Status.WARTET_AUF_FREIGABE,
    )
    zustand = _nach_knoten(schritte)

    assert zustand["abgleich"] is Schrittstatus.ERLEDIGT
    assert zustand["klaerfall"] is Schrittstatus.AKTIV
    assert zustand["buchung"] is Schrittstatus.OFFEN


def test_prozess_a_nach_freigabe_verbucht():
    schritte = schritte_fuer(
        "A", _protokoll("reader", "klassifikation", "abgleich", "buchung",
                        "klaerfall", "buchung"),
        status=Status.ABGESCHLOSSEN,
    )
    zustand = _nach_knoten(schritte)

    assert zustand["klaerfall"] is Schrittstatus.ERLEDIGT
    assert zustand["buchung"] is Schrittstatus.ERLEDIGT
    assert all(s.status is Schrittstatus.ERLEDIGT for s in schritte)


def test_prozess_a_zielsystem_lehnt_ab():
    """Navision weist die Buchung zurueck -- der Schritt ist gescheitert."""
    schritte = schritte_fuer(
        "A", _protokoll("reader", "klassifikation", "abgleich", "buchung",
                        "klaerfall", "buchung"),
        status=Status.FEHLGESCHLAGEN,
    )

    assert _nach_knoten(schritte)["buchung"] is Schrittstatus.GESCHEITERT


def test_verworfener_vorgang_bucht_nicht():
    schritte = schritte_fuer(
        "A", _protokoll("reader", "klassifikation", "abgleich", "buchung", "klaerfall"),
        status=Status.VERWORFEN,
    )

    assert _nach_knoten(schritte)["buchung"] is Schrittstatus.OFFEN


# ------------------------------------------------------------- Prozess B

def test_prozess_b_ueberspringt_freigabe_bei_eindeutiger_referenz():
    """Der Normalfall in B: Human-on-the-loop, keine Freigabe noetig."""
    schritte = schritte_fuer(
        "B", _protokoll("reader", "klassifikation", "kostenstelle", "elo"),
        status=Status.ABGESCHLOSSEN,
    )
    zustand = _nach_knoten(schritte)

    assert zustand["freigabe"] is Schrittstatus.UEBERSPRUNGEN
    assert zustand["elo"] is Schrittstatus.ERLEDIGT


def test_prozess_b_wartet_auf_kostenstellenfreigabe():
    schritte = schritte_fuer(
        "B", _protokoll("reader", "klassifikation", "kostenstelle"),
        wartet_auf="kostenstellen_freigabe", status=Status.WARTET_AUF_FREIGABE,
    )
    zustand = _nach_knoten(schritte)

    assert zustand["kostenstelle"] is Schrittstatus.ERLEDIGT
    assert zustand["freigabe"] is Schrittstatus.AKTIV
    assert zustand["elo"] is Schrittstatus.OFFEN


def test_prozess_b_nach_freigabe_archiviert():
    schritte = schritte_fuer(
        "B", _protokoll("reader", "klassifikation", "kostenstelle", "freigabe", "elo"),
        status=Status.ABGESCHLOSSEN,
    )

    assert _nach_knoten(schritte)["freigabe"] is Schrittstatus.ERLEDIGT


# --------------------------------------------------- Gemeinsame Strecke

def test_ad_check_verweigert_markiert_reader_als_gescheitert():
    """Szenario 5: der Vorgang endet am ersten Schritt."""
    schritte = schritte_fuer(None, _protokoll("reader"), status=Status.ABGEWIESEN)
    zustand = _nach_knoten(schritte)

    assert zustand["reader"] is Schrittstatus.GESCHEITERT
    assert zustand["klassifikation"] is Schrittstatus.OFFEN


def test_vor_der_klassifikation_nur_gemeinsame_strecke():
    """Solange der Typ nicht feststeht, gehoert der Vorgang keinem Prozess an."""
    schritte = schritte_fuer(None, _protokoll("reader"), status=Status.LAEUFT)

    assert [s.knoten for s in schritte] == ["reader", "klassifikation"]


# ------------------------------------------------------------ Formate

def test_euro_nutzt_deutsche_notation():
    assert euro(1341.96) == "1.341,96 €"
    assert euro(35632.01) == "35.632,01 €"
    assert euro(5.0) == "5,00 €"


def test_euro_ohne_wert():
    assert euro(None) == "—"


def test_zeitpunkt_kuerzt_iso():
    assert zeitpunkt("2026-07-29T17:27:49.123456+00:00") == "29.07.2026, 17:27"


def test_zeitpunkt_bleibt_bei_unerwartetem_format_lesbar():
    assert zeitpunkt("kein Zeitstempel") == "kein Zeitstempel"
    assert zeitpunkt(None) == "—"
