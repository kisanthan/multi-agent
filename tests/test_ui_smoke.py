"""Smoke test of the UI with Streamlit's own test runner.

Does not check appearance, but that every page renders without an
exception and that navigation and the rights display follow the AD mock.
This is the regression most likely to break when the UI is restructured --
an import error, a duplicate route path, or a wrong field name shows up
immediately here.

No case is started: the tests touch neither a model nor a target system.
"""

from __future__ import annotations

import sqlite3

import pytest

import process_registry
from config import DB_PATH, MANIFEST_PATH, PROJECT_ROOT

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

STARTUP_TIMEOUT = 60


@pytest.fixture(scope="module")
def upn() -> str:
    """A user with both rights -- otherwise the page only shows locks."""
    if not DB_PATH.is_file():
        pytest.skip("Stammdaten fehlen -- zuerst `python -m data.generate`.")

    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute("""
            SELECT m.upn FROM ad_memberships m
            WHERE m.group_name = 'SG-CHG-Freigabe'
              AND EXISTS (SELECT 1 FROM ad_memberships d
                          WHERE d.upn = m.upn AND d.group_name = 'SG-CHG-DocIngest')
            LIMIT 1
        """).fetchone()
    finally:
        con.close()

    if not row:
        pytest.skip("Kein Nutzer mit beiden Rechten in den Stammdaten.")
    return row[0]


def _app() -> AppTest:
    at = AppTest.from_file("ui/app.py", default_timeout=STARTUP_TIMEOUT)
    at.run()
    return at


def _page(source: str) -> AppTest:
    """Renders a single page with a signed-in user.

    The pages are functions behind `st.navigation`; a page switch cannot be
    driven in the test runner. Calling them directly tests exactly the code
    in question.
    """
    at = AppTest.from_string(source, default_timeout=STARTUP_TIMEOUT)
    at.run()
    return at


def _frame(upn: str, call: str, preamble: str = "") -> str:
    return (
        f"import sys; sys.path.insert(0, r'{PROJECT_ROOT}')\n"
        "import streamlit as st\n"
        "from ui.shared.context import SESSION_USER\n"
        f"st.session_state[SESSION_USER] = '{upn}'\n"
        f"{preamble}"
        f"{call}\n"
    )


def _text(at: AppTest) -> str:
    return " ".join(m.body for m in at.markdown)


# ------------------------------------------------------------ Whole application

def test_app_starts_without_exception():
    assert not _app().exception


def test_navigation_has_unique_routes():
    """Streamlit rejects duplicate `url_path` -- and every process needs one."""
    routes = [k.route for k in process_registry.all_processes()]
    # The upload page is the default page and sits at '/' without its own path.
    fixed = ["historie", "protokoll", "architektur", "vorgang"]

    assert len(set(routes)) == len(routes)
    assert not set(routes) & set(fixed)


def test_sidebar_offers_ad_users_for_sign_in():
    selection = _app().sidebar.selectbox[0]

    assert selection.label == "Angemeldet als"
    assert selection.options, "Ohne AD-Nutzer wäre keine Anmeldung möglich"


def test_sidebar_names_the_accounts_capabilities():
    """The sidebar states what this account can do -- not which security
    group it is in."""
    at = _app()
    options = at.sidebar.selectbox[0].options

    # The selection carries display names -- the sign-in name did not fit
    # the narrow sidebar and sits below it.
    extern = [o for o in options if o.startswith("Erik Extern")]
    keller = [o for o in options if o.startswith("Martina Keller")]
    if not (extern and keller):
        pytest.skip("Erwartete Testkonten fehlen in den Stammdaten.")

    at.sidebar.selectbox[0].set_value(extern[0]).run()
    text = " ".join(m.body for m in at.sidebar.markdown)
    assert "Nur lesen" in text
    assert "SG-CHG" not in text
    # The sign-in name sits in full below it, instead of being truncated in
    # the selection.
    assert "e.extern@partner-consulting.de" in text

    at.sidebar.selectbox[0].set_value(keller[0]).run()
    text = " ".join(m.body for m in at.sidebar.markdown)
    # The badge stays terse ("Hochladen"); the document kinds are spelled
    # out in the sentence below it.
    assert "Hochladen" in text
    assert "Zahlungsbestätigungen oder Eingangsrechnungen hochladen" in text


# ------------------------------------------------------------ Individual pages

def test_upload_page_offers_dropzone_and_short_history(upn):
    """The upload is the main point, the history here only an excerpt."""
    if not MANIFEST_PATH.is_file():
        pytest.skip("Testbelege fehlen -- zuerst `python -m data.generate`.")
    at = _page(_frame(upn, "upload.render()",
                      "from ui.pages import upload\n"))

    assert not at.exception
    assert at.file_uploader, "Ohne Uploader gäbe es keine Ablagefläche"
    # The drop area carries its own usage hint (CSS); a label next to it
    # would say the same thing twice.
    assert str(at.file_uploader[0].label_visibility).strip().lower().endswith(
        "collapsed")
    assert "Zuletzt hochgeladen" in _text(at)


def test_upload_page_blocks_uploading_without_permission():
    """Blocked, but without an error bar and without a group name: for this
    account, this is not an error, but a different task."""
    at = _page(_frame("e.extern@partner-consulting.de", "upload.render()",
                      "from ui.pages import upload\n"))

    assert not at.exception
    hints = [i.value for i in at.info]
    assert any("nicht berechtigt" in h for h in hints)
    assert not any("SG-CHG" in h for h in hints)
    assert not at.file_uploader, "Ohne Recht darf keine Ablagefläche erscheinen"


def test_history_page_renders(upn):
    at = _page(_frame(upn, "history.render()",
                      "from ui.pages import history\n"))
    assert not at.exception


def test_every_process_page_renders(upn):
    """Both processes arise from the same function -- both must run."""
    for config in process_registry.all_processes():
        at = _page(_frame(
            upn,
            f"process.render(process_registry.get_config('{config.key}'))",
            "import process_registry\nfrom ui.pages import process\n"))

        assert not at.exception, f"Prozess {config.key} bricht"
        assert config.name in _text(at) + " ".join(
            t.value for t in at.title)


def test_architecture_page_shows_both_processes_and_the_registry(upn):
    at = _page(_frame(upn, "architecture.render()",
                      "from ui.pages import architecture\n"))
    text = _text(at)

    assert not at.exception
    assert "Zahlungsbestätigung" in text and "Eingangsrechnung" in text
    # The page reads the registry. If the booking agent did not appear here
    # as human-in-the-loop, the UI would show something different from what
    # the code does.
    assert "Human-in-the-loop" in text


def test_audit_page_evaluates_integrity(upn):
    at = _page(_frame(upn, "audit.render()", "from ui.pages import audit\n"))

    assert not at.exception
    messages = [e.value for e in at.success] + [e.value for e in at.error]
    assert any("Protokoll" in m for m in messages)


def test_case_page_without_id_stays_understandable(upn):
    """A direct call without `?id=` must not run into an error."""
    at = _page(_frame(upn, "case.render()", "from ui.pages import case\n"))

    assert not at.exception
    assert any("Kein Vorgang" in i.value for i in at.info)
