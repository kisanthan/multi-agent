"""Tests of the user context.

What an account may do is decided by the governance layer. Here it is
checked that the UI derives the right statement from it -- and without the
name of a security group, since that helps no one who cannot manage it.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

import process_registry
from ui.shared import style
from ui.shared.user import User, load

ALL_RIGHTS = User("a@b.c", "Alle Rechte", True, True)
UPLOAD_ONLY = User("a@b.c", "Einspeisend", True, False)
CONFIRM_ONLY = User("a@b.c", "Prüfend", False, True)
NO_RIGHTS = User("a@b.c", "Zuschauend", False, False)

ALL_USERS = [ALL_RIGHTS, UPLOAD_ONLY, CONFIRM_ONLY, NO_RIGHTS]


def test_view_only_recognizes_the_read_right():
    assert NO_RIGHTS.view_only
    for person in (ALL_RIGHTS, UPLOAD_ONLY, CONFIRM_ONLY):
        assert not person.view_only


@pytest.mark.parametrize("person,expected", [
    (ALL_RIGHTS, "Beides"),
    (UPLOAD_ONLY, "Hochladen"),
    (CONFIRM_ONLY, "Bestätigen"),
    (NO_RIGHTS, "Nur lesen"),
])
def test_short_form_per_rights_combination(person, expected):
    assert person.rights_short == expected


def test_badge_stays_as_short_as_other_status_badges():
    """No badge in the system is a document-kind list plus a verb -- case
    statuses (e.g. 'Wartet auf Bestätigung') are one to three words long.
    The document kinds belong in the sentence, not in the badge."""
    for person in ALL_USERS:
        assert len(person.rights_short) <= 12, person.rights_short
        for kind in process_registry.document_kinds():
            assert kind not in person.rights_short


def test_partial_rights_are_distinguishable_in_the_badge():
    """Uploading and confirming are business-wise very different rights
    (four-eyes separation) -- a badge that makes both look the same would
    be misleading."""
    assert UPLOAD_ONLY.rights_short != CONFIRM_ONLY.rights_short


def test_every_combination_has_its_own_full_sentence():
    """The full sentence distinguishes all four combinations and names the
    document kinds -- the badge itself may stay terse for that reason."""
    assert len({p.capabilities for p in ALL_USERS}) == 4


def test_capabilities_name_the_document_kinds_concretely():
    """"Belege hochladen" leaves open which. The sentence says it."""
    sentence = UPLOAD_ONLY.capabilities

    for kind in process_registry.document_kinds():
        assert kind in sentence, f"{kind} fehlt in: {sentence}"
    assert "Zahlungsbestätigungen" in sentence
    assert "Eingangsrechnungen" in sentence


def test_the_block_message_also_names_the_document_kinds():
    for kind in process_registry.document_kinds():
        assert kind in NO_RIGHTS.upload_hint


def test_document_kinds_come_from_the_registry():
    """A third process must appear in the sentence on its own.

    Otherwise the enumeration would be a second source of truth that gets
    forgotten for the next process.
    """
    real = process_registry.PROCESSES
    extended = dict(real)
    example = next(iter(real.values()))
    extended["Z"] = replace(example, key="Z", route="mahnung",
                            name="Mahnung", document_kind="Mahnung")

    with patch.dict(process_registry.PROCESSES, extended, clear=True):
        assert "Mahnungen" in UPLOAD_ONLY.capabilities


def test_metric_addresses_the_approver_directly():
    assert "Ihre" in CONFIRM_ONLY.label_pending
    assert "Ihre" not in UPLOAD_ONLY.label_pending


def test_hints_name_no_security_group():
    """The group name belongs on the architecture page, not in a block message."""
    for person in ALL_USERS:
        for text in (person.capabilities, person.rights_short,
                     person.upload_hint, person.confirm_hint,
                     person.own_document_hint, person.label_pending):
            assert "SG-CHG" not in text
            assert "Least Privilege" not in text


def test_status_card_is_a_single_coherent_block():
    """Badge and sentence must sit inside the same HTML element.

    Two separate Streamlit elements had previously caused the card to cut
    off the sentence, because Streamlit measures a multi-element
    container's block height via JS, and that measurement was too tight
    for multi-line text. A single HTML block does not have this problem at
    all.
    """
    markup = style.status_card_html(UPLOAD_ONLY, upn="a@b.c")

    # A card opens and closes exactly once.
    assert markup.count('class="status-card"') == 1
    assert markup.startswith('<div class="status-card">')
    assert markup.rstrip().endswith("</div>")
    # Badge and sentence both sit inside this one card.
    assert UPLOAD_ONLY.rights_short in markup
    assert UPLOAD_ONLY.capabilities in markup


def test_status_card_shows_the_sign_in_name_only_if_given():
    without = style.status_card_html(UPLOAD_ONLY)
    with_upn = style.status_card_html(UPLOAD_ONLY, upn="a@b.c")

    assert "account-upn" not in without
    assert "a@b.c" in with_upn


def test_badge_distinguishes_active_from_view_only():
    """The color follows the capability -- the text always sits next to it."""
    full = style.rights_badge(ALL_RIGHTS)
    partial = style.rights_badge(UPLOAD_ONLY)
    none_ = style.rights_badge(NO_RIGHTS)

    assert "#1a6b3c" in full
    assert "#0b5cad" in partial
    assert "#5a5a5a" in none_
    # Color alone never carries the meaning.
    for markup, person in ((full, ALL_RIGHTS), (partial, UPLOAD_ONLY),
                           (none_, NO_RIGHTS)):
        assert person.rights_short in markup


def test_unknown_account_has_no_rights_instead_of_an_error(con):
    """An account without a directory entry must not break the UI."""
    person = load(con, "gibt.es.nicht@example.com")

    assert person.view_only
    assert person.display_name == "gibt.es.nicht@example.com"


def test_known_account_is_loaded_with_a_name(con):
    person = load(con, "pruefer@chg-meridian.com")

    assert person.display_name == "Peter Pruefer"
    assert person.can_upload and person.can_confirm
