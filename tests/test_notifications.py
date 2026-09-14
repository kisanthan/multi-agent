"""Streamlit rendering and one-shot behavior of approval notifications."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402


def test_notification_page_shows_task_and_announces_it_once():
    source = """
import streamlit as st
from graph.approval_queue import ApprovalTask
from graph.cases import CaseOverview, Status
from ui.pages.notifications import announce_new, render
from ui.shared import i18n

st.session_state[i18n.SESSION_LANGUAGE] = "de"
case = CaseOverview(
    thread_id="case-1",
    filename="A_payment_duplicate_1.pdf",
    actor="s.hofmann@chg-meridian.com",
    status=Status.WAITING_FOR_APPROVAL,
    process="A",
    started_at="2026-09-01T09:57:00+00:00",
    outcome=None,
    approved_by=None,
)
tasks = [ApprovalTask(case=case, request={"kind": "klaerfall"}, agent_id="buchung")]
announce_new("r.wagner@chg-meridian.com", tasks)
announce_new("r.wagner@chg-meridian.com", tasks)
render(tasks)
"""
    at = AppTest.from_string(source).run()

    assert not at.exception
    assert len(at.toast) == 1
    assert "neuer Vorgang" in at.toast[0].value
    assert any(metric.value == "1" for metric in at.metric)
    assert any("A_payment_duplicate_1.pdf" in item.value for item in at.markdown)
