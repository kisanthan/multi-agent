"""Tests der Policy-Engine.

Deckt die Kombinationen aus Rolle x Autonomiestufe x Betrag ab. Dass diese
Tests ueberhaupt moeglich sind, ist selbst das Argument: eine Governance-Regel
im Sprachmodell koennte man so nicht pruefen.
"""

from __future__ import annotations

import pytest

from config import einstellungen
from governance.policy import Ergebnis, pruefe_freigabe, pruefe_reader_zugriff, pruefe_schreibaktion

EINSPEISER = "einspeiser@chg-meridian.com"
PRUEFER = "pruefer@chg-meridian.com"
EXTERN = "extern@partner.de"


# ------------------------------------------------- Regel 1: Zero Trust

def test_unbekannter_akteur_wird_verweigert(con):
    e = pruefe_schreibaktion(con, agent_id="buchung", akteur="niemand@nirgends.de",
                             aktion="verbuchen", betrag_eur=100.0)
    assert e.ergebnis is Ergebnis.VERWEIGERT
    assert e.regel == "zero_trust"


# ------------------------------------- Regel 2/3: Least Privilege + Stufe

@pytest.mark.parametrize("agent_id", ["reader", "orchestrator", "policy", "audit"])
def test_komponenten_ohne_schreibrecht_duerfen_nicht_schreiben(con, agent_id):
    e = pruefe_schreibaktion(con, agent_id=agent_id, akteur=EINSPEISER, aktion="schreiben")
    assert e.ergebnis is Ergebnis.VERWEIGERT
    assert e.regel == "least_privilege"


@pytest.mark.parametrize("agent_id,stufe", [("abgleich", 1), ("klassifikation", 2),
                                            ("kostenstelle", 2)])
def test_stufe_1_und_2_duerfen_nicht_schreiben(con, agent_id, stufe):
    """Ein Agent der Stufe 1/2 darf auch bei 0 EUR nicht ausfuehren.

    Die Stufe wird vor dem Betrag geprueft -- ein kleiner Betrag darf eine zu
    niedrige Autonomiestufe nicht aushebeln.
    """
    e = pruefe_schreibaktion(con, agent_id=agent_id, akteur=EINSPEISER,
                             aktion="schreiben", betrag_eur=0.0)
    assert e.ergebnis is Ergebnis.VERWEIGERT
    assert e.regel in ("least_privilege", "autonomiestufe")


# ------------------------------------------------ Regel 4: Betragsschwelle

def test_buchung_unter_schwelle_ist_automatisch(con):
    betrag = einstellungen.buchung_schwelle_eur - 0.01
    e = pruefe_schreibaktion(con, agent_id="buchung", akteur=EINSPEISER,
                             aktion="verbuchen", betrag_eur=betrag)
    assert e.ergebnis is Ergebnis.ERLAUBT
    assert e.regel == "betragsschwelle"


def test_buchung_ueber_schwelle_braucht_freigabe(con):
    betrag = einstellungen.buchung_schwelle_eur + 0.01
    e = pruefe_schreibaktion(con, agent_id="buchung", akteur=EINSPEISER,
                             aktion="verbuchen", betrag_eur=betrag)
    assert e.ergebnis is Ergebnis.FREIGABE_NOETIG
    assert e.regel == "betragsschwelle"


def test_buchung_genau_auf_schwelle_ist_automatisch(con):
    """Die Schwelle ist exklusiv: erst *ueber* dem Wert wird eskaliert.

    Explizit getestet, weil die Grenze sonst eine stillschweigende Annahme
    waere -- und in der Arbeit steht 'unterhalb Betrag X automatisch'.
    """
    e = pruefe_schreibaktion(con, agent_id="buchung", akteur=EINSPEISER,
                             aktion="verbuchen", betrag_eur=einstellungen.buchung_schwelle_eur)
    assert e.ergebnis is Ergebnis.ERLAUBT


# ------------------------------------------------ Regel 5: Aufsichtsmodus

def test_elo_agent_ist_on_the_loop_und_laeuft_automatisch(con):
    """ELO-Agent (Stufe 3, Human-on-the-loop) ist das Prozessende von Prozess B.

    Die menschliche Freigabe in Prozess B liegt beim Kostenstellen-Schritt davor
    und nur bei Mehrdeutigkeit (Vier-Augen); an der Archivierung wird nicht
    erneut gefragt.
    """
    e = pruefe_schreibaktion(con, agent_id="elo", akteur=EINSPEISER, aktion="archivieren")
    assert e.ergebnis is Ergebnis.ERLAUBT
    assert e.regel == "aufsichtsmodus"


# --------------------------------------------------------- Reader-Zugriff

def test_reader_zugriff_fuer_gruppenmitglied(con):
    assert pruefe_reader_zugriff(con, akteur=EINSPEISER).ergebnis is Ergebnis.ERLAUBT


def test_reader_zugriff_ohne_gruppe_verweigert(con):
    """Szenario 5 auf Policy-Ebene."""
    e = pruefe_reader_zugriff(con, akteur=EXTERN)
    assert e.ergebnis is Ergebnis.VERWEIGERT
    assert "SG-CHG-DocIngest" in e.begruendung


def test_reader_zugriff_unbekannter_nutzer_verweigert(con):
    e = pruefe_reader_zugriff(con, akteur="niemand@nirgends.de")
    assert e.ergebnis is Ergebnis.VERWEIGERT


# ------------------------------------------- Freigabe / Vier-Augen-Prinzip

def test_pruefer_darf_freigeben(con):
    assert pruefe_freigabe(con, akteur=PRUEFER, agent_id="kostenstelle").erlaubt


def test_einspeiser_darf_nicht_freigeben(con):
    """Vier-Augen-Prinzip: wer einspeist, gibt nicht selbst frei."""
    e = pruefe_freigabe(con, akteur=EINSPEISER, agent_id="kostenstelle")
    assert e.ergebnis is Ergebnis.VERWEIGERT
    assert "SG-CHG-Freigabe" in e.begruendung


def test_externer_darf_nicht_freigeben(con):
    assert not pruefe_freigabe(con, akteur=EXTERN, agent_id="kostenstelle").erlaubt


# ---------------------------------------------------------- Sonstiges

def test_unbekannter_agent_ist_programmierfehler(con):
    """Kein Default-Fallback: die Policy darf nicht gegen Geratenes pruefen."""
    with pytest.raises(KeyError, match="Unbekannter Agent"):
        pruefe_schreibaktion(con, agent_id="gibt_es_nicht", akteur=EINSPEISER, aktion="x")


def test_entscheid_traegt_begruendung_und_regel(con):
    """Jede Entscheidung ist auditierbar begruendet."""
    e = pruefe_schreibaktion(con, agent_id="abgleich", akteur=EINSPEISER, aktion="schreiben")
    assert e.regel and e.begruendung
    assert e.kontext["agent"] == "abgleich"
