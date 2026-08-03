"""The working views stay free of domain jargon.

Terms like "Prozess A", "Human-in-the-loop", "Einspeiser", or the name of a
security group come from the functional concept. They belong there and are
wrong on a case worker's screen.

Two places are deliberately exempted:

- the **Architektur** page -- it explains exactly these terms,
- the **content of the audit trail** -- there stands what was actually
  recorded. Rephrasing a recorded reason for the display would mean
  falsifying the evidence. So only the surroundings of the audit page are
  checked, not the table inside it.
"""

from __future__ import annotations

import pytest

from config import DB_PATH, PROJECT_ROOT

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

# What must not appear on any working view.
JARGON = [
    "SG-CHG",
    "Prozess A",
    "Prozess B",
    "Human-in-the-loop",
    "Human-on-the-loop",
    "AD-Check",
    "Einspeiser",
    "einspeisen",
    "eingespeist",
    "Klärfall",
    "Vier-Augen",
    "Autonomiestufe",
    "Least Privilege",
    "Audit-Trail",
    "Zielsystem",
]


@pytest.fixture(scope="module")
def upn() -> str:
    import sqlite3

    if not DB_PATH.is_file():
        pytest.skip("Stammdaten fehlen -- zuerst `python -m data.generate`.")
    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute(
            "SELECT upn FROM ad_memberships WHERE group_name = 'SG-CHG-Freigabe'"
            " LIMIT 1").fetchone()
    finally:
        con.close()
    if not row:
        pytest.skip("Kein freigabeberechtigtes Konto in den Stammdaten.")
    return row[0]


def _render(source: str) -> AppTest:
    at = AppTest.from_string(source, default_timeout=90)
    at.run()
    return at


def _page(upn: str, call: str, imports: str) -> AppTest:
    return _render(
        f"import sys; sys.path.insert(0, r'{PROJECT_ROOT}')\n"
        "import streamlit as st\n"
        "from ui.shared.context import SESSION_USER\n"
        f"st.session_state[SESSION_USER] = '{upn}'\n"
        f"{imports}"
        f"{call}\n"
    )


def _visible_text(at: AppTest) -> str:
    """Everything a human reads on the page.

    Without the content of tables: that is where the audit page holds the
    recorded wording, which deliberately stays unchanged.
    """
    parts: list[str] = []
    for name in ("markdown", "caption", "title", "header", "subheader",
                 "info", "warning", "error", "success"):
        for element in getattr(at, name, []):
            parts.append(str(getattr(element, "value", getattr(element, "body", ""))))

    for name in ("button", "selectbox", "multiselect", "text_input",
                 "date_input", "metric", "file_uploader", "toggle"):
        for element in getattr(at, name, []):
            parts.append(str(getattr(element, "label", "")))

    # The embedded stylesheet is not text for humans.
    return " ".join(t for t in parts if not t.lstrip().startswith("<style>"))


def _check_free_of_jargon(at: AppTest, page_name: str) -> None:
    text = _visible_text(at)
    hits = [w for w in JARGON if w.lower() in text.lower()]
    assert not hits, f"{page_name} zeigt Fachjargon: {hits}"


def test_upload_page_without_jargon(upn):
    at = _page(upn, "upload.render()", "from ui.pages import upload\n")
    assert not at.exception
    _check_free_of_jargon(at, "Upload")


def test_upload_page_without_jargon_even_without_permission():
    """Especially the block message must not name a security group."""
    at = _page("e.extern@partner-consulting.de", "upload.render()",
               "from ui.pages import upload\n")
    assert not at.exception
    _check_free_of_jargon(at, "Upload (gesperrt)")


def test_all_cases_without_jargon(upn):
    at = _page(upn, "history.render()", "from ui.pages import history\n")
    assert not at.exception
    _check_free_of_jargon(at, "Alle Vorgänge")


def test_process_pages_without_jargon(upn):
    import process_registry

    for config in process_registry.all_processes():
        at = _page(
            upn,
            f"process.render(process_registry.get_config('{config.key}'))",
            "import process_registry\nfrom ui.pages import process\n")
        assert not at.exception
        _check_free_of_jargon(at, config.name)


def test_audit_page_without_jargon_in_the_surroundings(upn):
    at = _page(upn, "audit.render()", "from ui.pages import audit\n")
    assert not at.exception
    _check_free_of_jargon(at, "Protokoll")


def test_architecture_page_may_show_the_jargon(upn):
    """The counter-test: here it belongs, otherwise the exception would be pointless."""
    at = _page(upn, "architecture.render()", "from ui.pages import architecture\n")
    text = _visible_text(at)

    assert not at.exception
    assert "Human-in-the-loop" in text
    assert "Prozess A" in text
