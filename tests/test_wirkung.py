"""Tests der Zielsystem-Wirkung.

Die Wirkung ist der eigentliche Nachweis eines Laufs: CLI und Oberflaeche
zeigen beide diese Abfrage, deshalb muss sie auch die Randfaelle sauber
beantworten statt zu werfen.
"""

from __future__ import annotations

import pytest

from graph.wirkung import lies_wirkung


@pytest.fixture
def stammdaten(con):
    con.execute("INSERT INTO lieferanten VALUES ('L1','Musterlieferant GmbH',NULL,NULL)")
    con.executemany("INSERT INTO rechnungen VALUES (?,?,?,?,?,?)", [
        ("RE-2026-4200", 1341.96, "2026-08-01", "bezahlt", "L1", "2026-07-29T10:00:00"),
        ("RE-2026-4201", 500.00, "2026-08-01", "offen", "L1", None),
    ])
    con.execute("INSERT INTO archiv VALUES ('ELO-2026-0001','b.pdf','abc123',"
                "'2026-07-29T11:00:00')")
    con.commit()
    return con


def test_verbuchte_zahlung_zeigt_navision_status(stammdaten):
    w = lies_wirkung(stammdaten, {"nummer": "RE-2026-4200"})

    assert w.navision_nummer == "RE-2026-4200"
    assert w.navision_status == "bezahlt"
    assert w.navision_bezahlt_am == "2026-07-29T10:00:00"
    assert w.hat_wirkung


def test_offene_rechnung_wird_als_offen_gemeldet(stammdaten):
    w = lies_wirkung(stammdaten, {"nummer": "RE-2026-4201"})

    assert w.navision_status == "offen"
    assert w.navision_bezahlt_am is None


def test_unbekannte_nummer_ist_kein_fehler(stammdaten):
    """Szenario 2: die Nummer steht nicht in den Stammdaten.

    Das ist ein regulaerer fachlicher Fall (Klaerfall) und darf die Anzeige
    nicht sprengen.
    """
    w = lies_wirkung(stammdaten, {"nummer": "RE-9999-0000"})

    assert w.navision_status is None
    assert w.navision_nummer is None
    assert not w.hat_wirkung


def test_archivierung_zeigt_elo_kennung(stammdaten):
    w = lies_wirkung(stammdaten, {"archiv_id": "ELO-2026-0001"})

    assert w.elo_archiv_id == "ELO-2026-0001"
    assert w.elo_abgelegt_am == "2026-07-29T11:00:00"
    assert w.hat_wirkung


def test_vorgang_ohne_zielsystemberuehrung(stammdaten):
    """Szenario 5 endet vor jedem Zielsystem -- es gibt nichts anzuzeigen."""
    w = lies_wirkung(stammdaten, {"ergebnis": "zugriff_verweigert"})

    assert not w.hat_wirkung
    assert w.navision_status is None
    assert w.elo_archiv_id is None
