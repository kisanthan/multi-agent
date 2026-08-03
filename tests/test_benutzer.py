"""Tests des Benutzerkontexts.

Was ein Konto darf, entscheidet die Governance-Schicht. Hier wird geprueft, dass
die Oberflaeche daraus die richtige Aussage macht -- und zwar ohne den Namen
einer Sicherheitsgruppe, denn der hilft niemandem weiter, der sie nicht
verwalten kann.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

import prozessregistry
from ui.shared import stil
from ui.shared.benutzer import Benutzer, lade

ALLE_RECHTE = Benutzer("a@b.c", "Alle Rechte", True, True)
NUR_HOCHLADEN = Benutzer("a@b.c", "Einspeisend", True, False)
NUR_BESTAETIGEN = Benutzer("a@b.c", "Prüfend", False, True)
OHNE_RECHTE = Benutzer("a@b.c", "Zuschauend", False, False)

ALLE = [ALLE_RECHTE, NUR_HOCHLADEN, NUR_BESTAETIGEN, OHNE_RECHTE]


def test_nur_ansicht_erkennt_das_leserecht():
    assert OHNE_RECHTE.nur_ansicht
    for person in (ALLE_RECHTE, NUR_HOCHLADEN, NUR_BESTAETIGEN):
        assert not person.nur_ansicht


@pytest.mark.parametrize("person,erwartet", [
    (ALLE_RECHTE, "Beides"),
    (NUR_HOCHLADEN, "Hochladen"),
    (NUR_BESTAETIGEN, "Bestätigen"),
    (OHNE_RECHTE, "Nur lesen"),
])
def test_kurzform_je_rechtekombination(person, erwartet):
    assert person.rechte_kurz == erwartet


def test_abzeichen_bleibt_kurz_wie_die_uebrigen_statusabzeichen():
    """Kein Abzeichen im System ist eine Belegartenliste plus Verb -- die
    Vorgangsstatus (z. B. 'Wartet auf Bestätigung') sind ein bis drei
    Woerter lang. Die Belegarten gehoeren in den Satz, nicht ins Abzeichen."""
    for person in ALLE:
        assert len(person.rechte_kurz) <= 12, person.rechte_kurz
        for art in prozessregistry.belegarten():
            assert art not in person.rechte_kurz


def test_partielle_rechte_sind_im_abzeichen_unterscheidbar():
    """Hochladen und Bestätigen sind fachlich sehr unterschiedliche Rechte
    (Vier-Augen-Trennung) -- ein Abzeichen, das beide gleich aussehen laesst,
    waere irrefuehrend."""
    assert NUR_HOCHLADEN.rechte_kurz != NUR_BESTAETIGEN.rechte_kurz


def test_jede_kombination_hat_eine_eigene_volle_aussage():
    """Der ausführliche Satz unterscheidet alle vier Kombinationen und nennt
    die Belegarten -- das Abzeichen selbst darf dafür knapp bleiben."""
    assert len({p.faehigkeiten for p in ALLE}) == 4


def test_faehigkeiten_nennen_die_belegarten_konkret():
    """„Belege hochladen" laesst offen, welche. Der Satz sagt es aus."""
    satz = NUR_HOCHLADEN.faehigkeiten

    for art in prozessregistry.belegarten():
        assert art in satz, f"{art} fehlt in: {satz}"
    assert "Zahlungsbestätigungen" in satz
    assert "Eingangsrechnungen" in satz


def test_auch_die_sperrmeldung_nennt_die_belegarten():
    for art in prozessregistry.belegarten():
        assert art in OHNE_RECHTE.hinweis_hochladen


def test_belegarten_stammen_aus_der_registry():
    """Ein dritter Prozess muss von selbst im Satz auftauchen.

    Sonst waere die Aufzaehlung eine zweite Wahrheit, die beim naechsten
    Prozess vergessen wird.
    """
    echte = prozessregistry.PROZESSE
    zusatz = dict(echte)
    beispiel = next(iter(echte.values()))
    zusatz["Z"] = replace(beispiel, schluessel="Z", route="mahnung",
                          bezeichnung="Mahnung", belegart="Mahnung")

    with patch.dict(prozessregistry.PROZESSE, zusatz, clear=True):
        assert "Mahnungen" in NUR_HOCHLADEN.faehigkeiten


def test_kennzahl_spricht_den_pruefer_direkt_an():
    assert "Ihre" in NUR_BESTAETIGEN.label_offene
    assert "Ihre" not in NUR_HOCHLADEN.label_offene


def test_hinweise_nennen_keine_sicherheitsgruppe():
    """Der Gruppenname gehoert auf die Architekturseite, nicht in eine Sperre."""
    for person in ALLE:
        for text in (person.faehigkeiten, person.rechte_kurz,
                     person.hinweis_hochladen, person.hinweis_bestaetigen,
                     person.hinweis_eigener_beleg, person.label_offene):
            assert "SG-CHG" not in text
            assert "Least Privilege" not in text


def test_statuskarte_ist_ein_einzelner_zusammenhaengender_block():
    """Abzeichen und Satz muessen im selben HTML-Element stecken.

    Zwei getrennte Streamlit-Elemente hatten zuvor dazu gefuehrt, dass die
    Karte den Satz abschnitt, weil Streamlit die Blockhoehe eines mehrelementigen
    Containers per JS misst und diese Messung bei mehrzeiligem Text zu knapp
    ausfiel. Ein einzelner HTML-Block hat dieses Problem grundsaetzlich nicht.
    """
    markup = stil.statuskarte_html(NUR_HOCHLADEN, upn="a@b.c")

    # Eine Karte oeffnet und schliesst sich genau einmal.
    assert markup.count('class="statuskarte"') == 1
    assert markup.startswith('<div class="statuskarte">')
    assert markup.rstrip().endswith("</div>")
    # Abzeichen und Satz stehen beide innerhalb dieser einen Karte.
    assert NUR_HOCHLADEN.rechte_kurz in markup
    assert NUR_HOCHLADEN.faehigkeiten in markup


def test_statuskarte_zeigt_den_anmeldenamen_nur_wenn_angegeben():
    ohne = stil.statuskarte_html(NUR_HOCHLADEN)
    mit = stil.statuskarte_html(NUR_HOCHLADEN, upn="a@b.c")

    assert "konto-upn" not in ohne
    assert "a@b.c" in mit


def test_abzeichen_unterscheidet_handlungsfaehig_von_zuschauend():
    """Die Farbe folgt der Handlungsfähigkeit -- der Text steht immer daneben."""
    voll = stil.rechte_abzeichen(ALLE_RECHTE)
    teilweise = stil.rechte_abzeichen(NUR_HOCHLADEN)
    keine = stil.rechte_abzeichen(OHNE_RECHTE)

    assert "#1a6b3c" in voll
    assert "#0b5cad" in teilweise
    assert "#5a5a5a" in keine
    # Farbe allein traegt die Aussage nie.
    for markup, person in ((voll, ALLE_RECHTE), (teilweise, NUR_HOCHLADEN),
                           (keine, OHNE_RECHTE)):
        assert person.rechte_kurz in markup


def test_unbekanntes_konto_hat_keine_rechte_statt_eines_fehlers(con):
    """Ein Konto ohne Verzeichniseintrag darf die Oberfläche nicht sprengen."""
    person = lade(con, "gibt.es.nicht@example.com")

    assert person.nur_ansicht
    assert person.anzeigename == "gibt.es.nicht@example.com"


def test_bekanntes_konto_wird_mit_namen_geladen(con):
    person = lade(con, "pruefer@chg-meridian.com")

    assert person.anzeigename == "Peter Pruefer"
    assert person.darf_hochladen and person.darf_bestaetigen
