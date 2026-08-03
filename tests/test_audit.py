"""Tests des Audit-Trails -- der Manipulationsnachweis der Arbeit.

Der Kern ist test_verify_chain_erkennt_*: die Kette muss eine nachtraegliche
Aenderung erkennen. Ohne diesen Nachweis waere "manipulationsgeschuetzt" eine
Behauptung.
"""

from __future__ import annotations

import pytest

from governance.audit import (
    GENESIS_HASH,
    Entscheidung,
    Vorgangsbezug,
    lies_alle,
    protokolliere,
    verify_chain,
    vorgaenge_im_trail,
)


BEZUG = Vorgangsbezug("vorgang-1", "a.pdf")


def _drei_eintraege(con):
    protokolliere(con, akteur="einspeiser@chg-meridian.com", agent="reader",
                  aktion="dokument_eingespeist", entscheidung=Entscheidung.ERLAUBT,
                  begruendung="AD-Check bestanden", payload={"datei": "a.pdf"},
                  bezug=BEZUG, ergebnis="1 Seite(n) gelesen")
    protokolliere(con, akteur="einspeiser@chg-meridian.com", agent="abgleich",
                  aktion="nummer_abgeglichen", entscheidung=Entscheidung.INFO,
                  begruendung="RE-2026-4200 gefunden", payload={"nummer": "RE-2026-4200"},
                  bezug=BEZUG, ergebnis="ok")
    protokolliere(con, akteur="einspeiser@chg-meridian.com", agent="buchung",
                  aktion="zahlung_verbucht", entscheidung=Entscheidung.ERLAUBT,
                  begruendung="freigegeben", payload={"betrag": 1234.56},
                  bezug=BEZUG, ergebnis="verbucht")
    con.commit()


def test_erster_eintrag_verweist_auf_genesis(con):
    e = protokolliere(con, akteur="a@b.c", aktion="start",
                      entscheidung=Entscheidung.INFO, begruendung="Systemstart")
    assert e.prev_hash == GENESIS_HASH


def test_kette_verkettet_fortlaufend(con):
    _drei_eintraege(con)
    eintraege = lies_alle(con)

    assert len(eintraege) == 3
    assert eintraege[0].prev_hash == GENESIS_HASH
    # Jeder Eintrag verweist auf den Hash seines Vorgaengers.
    assert eintraege[1].prev_hash == eintraege[0].hash
    assert eintraege[2].prev_hash == eintraege[1].hash


def test_intakte_kette_wird_als_gueltig_erkannt(con):
    _drei_eintraege(con)
    ergebnis = verify_chain(con)
    assert ergebnis.gueltig
    assert ergebnis.geprueft == 3


def test_leere_kette_ist_gueltig(con):
    assert verify_chain(con).gueltig


def test_trigger_verhindert_update(con):
    """Die Datenbank selbst weist ein UPDATE ab -- append-only ist erzwungen."""
    _drei_eintraege(con)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("UPDATE audit SET begruendung = 'manipuliert' WHERE id = 2")


def test_trigger_verhindert_delete(con):
    _drei_eintraege(con)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("DELETE FROM audit WHERE id = 2")


def test_verify_chain_erkennt_inhaltliche_manipulation(con):
    """Kernnachweis: eine nachtraegliche Aenderung bricht die Kette.

    Die Trigger werden hier bewusst umgangen, um den Fall zu simulieren, dass
    jemand mit direktem Datenbankzugriff (also unter Umgehung der Anwendung)
    einen Eintrag faelscht. Genau dagegen schuetzt die Hash-Verkettung -- der
    Trigger allein wuerde das nicht auffangen.
    """
    _drei_eintraege(con)
    con.execute("DROP TRIGGER audit_kein_update")
    con.execute("UPDATE audit SET begruendung = 'war schon immer erlaubt' WHERE id = 2")
    con.commit()

    ergebnis = verify_chain(con)
    assert not ergebnis.gueltig
    assert ergebnis.bruch_bei == 2
    assert "Aenderung" in ergebnis.grund


def test_verify_chain_erkennt_geaenderten_akteur(con):
    """Auch der Akteur ist gehasht -- eine Zuschreibung laesst sich nicht faelschen."""
    _drei_eintraege(con)
    con.execute("DROP TRIGGER audit_kein_update")
    con.execute("UPDATE audit SET akteur = 'jemand.anderes@chg-meridian.com' WHERE id = 3")
    con.commit()

    assert not verify_chain(con).gueltig


def test_verify_chain_erkennt_geloeschten_eintrag(con):
    """Ein entfernter Eintrag hinterlaesst eine Luecke in der Verkettung."""
    _drei_eintraege(con)
    con.execute("DROP TRIGGER audit_kein_delete")
    con.execute("DELETE FROM audit WHERE id = 2")
    con.commit()

    ergebnis = verify_chain(con)
    assert not ergebnis.gueltig
    # Eintrag 3 verweist jetzt auf einen Vorgaenger, den es nicht mehr gibt.
    assert ergebnis.bruch_bei == 3
    assert "geloeschten oder eingefuegten" in ergebnis.grund


def test_verify_chain_erkennt_umgehaengten_vorgang(con):
    """Der Vorgangsbezug ist gehasht -- ein Eintrag laesst sich nicht umwidmen.

    Waere `vorgang_id` vom Hash ausgenommen, koennte man eine verweigerte
    Aktion nachtraeglich einem anderen Vorgang zuschreiben, ohne dass die Kette
    bricht -- und der gefilterte Trail wuerde luegen.
    """
    _drei_eintraege(con)
    con.execute("DROP TRIGGER audit_kein_update")
    con.execute("UPDATE audit SET vorgang_id = 'ein-anderer-vorgang' WHERE id = 2")
    con.commit()

    assert not verify_chain(con).gueltig


def test_verify_chain_erkennt_geaenderte_datenquelle(con):
    _drei_eintraege(con)
    con.execute("DROP TRIGGER audit_kein_update")
    con.execute("UPDATE audit SET datenquelle = 'ein_anderer_beleg.pdf' WHERE id = 1")
    con.commit()

    assert not verify_chain(con).gueltig


def test_verify_chain_erkennt_geaendertes_ergebnis(con):
    """Ein nachtraeglich geschoentes Ergebnis muss auffallen.

    Eintrag 3 steht auf 'verbucht'; hier wird er auf 'abgelehnt' umgeschrieben
    -- die Richtung ist gleichgueltig, jede Aenderung muss die Kette brechen.
    """
    _drei_eintraege(con)
    con.execute("DROP TRIGGER audit_kein_update")
    con.execute("UPDATE audit SET ergebnis = 'abgelehnt' WHERE id = 3")
    con.commit()

    assert not verify_chain(con).gueltig


def test_eintraege_lassen_sich_nach_vorgang_filtern(con):
    _drei_eintraege(con)
    protokolliere(con, akteur="a@b.c", agent="reader", aktion="dokument_eingespeist",
                  entscheidung=Entscheidung.ERLAUBT, begruendung="anderer Lauf",
                  bezug=Vorgangsbezug("vorgang-2", "b.pdf"))
    con.commit()

    eintraege = lies_alle(con, vorgang_id="vorgang-1")

    assert len(eintraege) == 3
    assert {e.vorgang_id for e in eintraege} == {"vorgang-1"}
    assert sorted(vorgaenge_im_trail(con)) == ["vorgang-1", "vorgang-2"]


def test_eintraege_ohne_vorgang_stoeren_den_filter_nicht(con):
    """Ein Upload gehoert zu keinem Vorgang und darf in keinem auftauchen."""
    protokolliere(con, akteur="a@b.c", aktion="datei_hochgeladen",
                  entscheidung=Entscheidung.ERLAUBT, begruendung="abgelegt",
                  bezug=Vorgangsbezug(None, "c.pdf"))
    con.commit()

    assert lies_alle(con, vorgang_id="vorgang-1") == []
    assert vorgaenge_im_trail(con) == []
    assert verify_chain(con).gueltig


def test_payload_hash_ist_reihenfolgeunabhaengig(con):
    """Gleicher Inhalt, andere dict-Reihenfolge -> gleicher Hash.

    Sonst waere die Kette nicht reproduzierbar pruefbar.
    """
    a = protokolliere(con, akteur="a@b.c", aktion="x", entscheidung=Entscheidung.INFO,
                      begruendung="-", payload={"eins": 1, "zwei": 2})
    b = protokolliere(con, akteur="a@b.c", aktion="x", entscheidung=Entscheidung.INFO,
                      begruendung="-", payload={"zwei": 2, "eins": 1})
    assert a.payload_hash == b.payload_hash
