"""Tests der Textbausteine in ui/shared/formate.py."""

from __future__ import annotations

from ui.shared.formate import aufzaehlung, mehrzahl


def test_aufzaehlung_bei_zwei_teilen():
    assert aufzaehlung(["A", "B"]) == "A und B"


def test_aufzaehlung_mit_eigenem_verbinder():
    assert aufzaehlung(["A", "B"], verbinder="oder") == "A oder B"


def test_aufzaehlung_bei_drei_teilen():
    """Muss auch dann noch stimmen, wenn ein dritter Prozess dazukommt."""
    assert aufzaehlung(["A", "B", "C"]) == "A, B und C"


def test_aufzaehlung_bei_einem_teil():
    assert aufzaehlung(["A"]) == "A"


def test_aufzaehlung_bei_keinem_teil():
    assert aufzaehlung([]) == ""


def test_aufzaehlung_ignoriert_leere_eintraege():
    assert aufzaehlung(["A", "", None, "B"]) == "A und B"


def test_mehrzahl_der_bekannten_belegarten():
    assert mehrzahl("Zahlungsbestätigung") == "Zahlungsbestätigungen"
    assert mehrzahl("Eingangsrechnung") == "Eingangsrechnungen"
