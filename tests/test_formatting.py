"""Tests of the text helpers in ui/shared/formatting.py."""

from __future__ import annotations

from ui.shared.formatting import enumerate_list, pluralize


def test_enumerate_list_with_two_parts():
    assert enumerate_list(["A", "B"]) == "A und B"


def test_enumerate_list_with_custom_connector():
    assert enumerate_list(["A", "B"], connector="oder") == "A oder B"


def test_enumerate_list_with_three_parts():
    """Must still hold when a third process is added."""
    assert enumerate_list(["A", "B", "C"]) == "A, B und C"


def test_enumerate_list_with_one_part():
    assert enumerate_list(["A"]) == "A"


def test_enumerate_list_with_no_parts():
    assert enumerate_list([]) == ""


def test_enumerate_list_ignores_empty_entries():
    assert enumerate_list(["A", "", None, "B"]) == "A und B"


def test_pluralize_known_document_kinds():
    assert pluralize("Zahlungsbestätigung") == "Zahlungsbestätigungen"
    assert pluralize("Eingangsrechnung") == "Eingangsrechnungen"
