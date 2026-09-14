"""Automatic opening rules of the approval dialog."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402


def _waiting_card(*, viewer: str, submitter: str) -> AppTest:
    source = f'''
import streamlit as st
from ui.cases import approval_dialog, detail
from ui.shared import i18n

st.session_state[i18n.SESSION_LANGUAGE] = "de"
original_open = approval_dialog.open_decision

def record_open(*args, **kwargs):
    st.write("AUTOMATIC_DIALOG_OPENED")

approval_dialog.open_decision = record_open
try:
    detail._waiting_card(
        object(),
        "case-1",
        {{"kind": "klaerfall", "trigger": "oversight_mode"}},
        {{"actor": "{submitter}", "filename": "payment.pdf"}},
        upn="{viewer}",
    )
finally:
    approval_dialog.open_decision = original_open
'''
    return AppTest.from_string(source, default_timeout=30).run()


def test_uploader_does_not_get_automatic_approval_dialog():
    at = _waiting_card(
        viewer="s.hofmann@chg-meridian.com",
        submitter="S.HOFMANN@CHG-MERIDIAN.COM",
    )

    assert not at.exception
    assert not any("AUTOMATIC_DIALOG_OPENED" in item.value
                   for item in at.markdown)
    assert any(button.label == "Entscheidung öffnen" for button in at.button)


def test_other_person_still_gets_automatic_approval_dialog():
    at = _waiting_card(
        viewer="r.wagner@chg-meridian.com",
        submitter="s.hofmann@chg-meridian.com",
    )

    assert not at.exception
    assert any("AUTOMATIC_DIALOG_OPENED" in item.value
               for item in at.markdown)
