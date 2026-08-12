"""The working views stay free of domain jargon -- in every language.

Terms like "Prozess A", "Human-in-the-loop", "Einspeiser", or the name of a
security group come from the functional concept. They belong there and are
wrong on a case worker's screen.

Adding English made this test more than a German spell-check: a translation
is exactly the moment where the concept's vocabulary creeps back in, because
the obvious English word for "Protokoll" *is* "audit trail". So the same
pages are rendered twice and each language is checked against its own list.

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
from ui.shared import i18n

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

# What must not appear on any working view, per language.
JARGON = {
    "de": [
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
    ],
    "en": [
        "SG-CHG",
        "Process A",
        "Process B",
        "Human-in-the-loop",
        "Human-on-the-loop",
        "AD check",
        "four-eyes",
        "autonomy level",
        "Least Privilege",
        "audit trail",
        "exception case",
    ],
}

LANGUAGES = sorted(JARGON)


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


# Generous on purpose: every page here is rendered once per language, so
# this module drives twice the Streamlit runs it used to. The old 90s was
# enough for one pass and started timing out on a loaded machine at two --
# a timeout here would read as "the interface shows jargon", which is not
# what happened.
RENDER_TIMEOUT = 240


def _render(source: str) -> AppTest:
    at = AppTest.from_string(source, default_timeout=RENDER_TIMEOUT)
    at.run()
    return at


def _page(upn: str, call: str, imports: str, language: str = "de") -> AppTest:
    return _render(
        f"import sys; sys.path.insert(0, r'{PROJECT_ROOT}')\n"
        "import streamlit as st\n"
        "from ui.shared.context import SESSION_USER\n"
        "from ui.shared import i18n\n"
        f"st.session_state[SESSION_USER] = '{upn}'\n"
        f"st.session_state[i18n.SESSION_LANGUAGE] = '{language}'\n"
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


def _check_free_of_jargon(at: AppTest, page_name: str, language: str) -> None:
    text = _visible_text(at)
    hits = [w for w in JARGON[language] if w.lower() in text.lower()]
    assert not hits, f"{page_name} zeigt Fachjargon ({language}): {hits}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_upload_page_without_jargon(upn, language):
    at = _page(upn, "upload.render()", "from ui.pages import upload\n", language)
    assert not at.exception
    _check_free_of_jargon(at, "Upload", language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_upload_page_without_jargon_even_without_permission(language):
    """Especially the block message must not name a security group."""
    at = _page("e.extern@partner-consulting.de", "upload.render()",
               "from ui.pages import upload\n", language)
    assert not at.exception
    _check_free_of_jargon(at, "Upload (gesperrt)", language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_all_cases_without_jargon(upn, language):
    at = _page(upn, "history.render()", "from ui.pages import history\n", language)
    assert not at.exception
    _check_free_of_jargon(at, "Alle Vorgänge", language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_process_pages_without_jargon(upn, language):
    import process_registry

    for config in process_registry.all_processes():
        at = _page(
            upn,
            f"process.render(process_registry.get_config('{config.key}'))",
            "import process_registry\nfrom ui.pages import process\n",
            language)
        assert not at.exception
        _check_free_of_jargon(at, config.name, language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_audit_page_without_jargon_in_the_surroundings(upn, language):
    at = _page(upn, "audit.render()", "from ui.pages import audit\n", language)
    assert not at.exception
    _check_free_of_jargon(at, "Protokoll", language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_architecture_page_may_show_the_jargon(upn, language):
    """The counter-test: here it belongs, otherwise the exception would be
    pointless. The English page must carry it too -- a translation that
    quietly drops "Human-in-the-loop" would drop the claim with it."""
    at = _page(upn, "architecture.render()",
               "from ui.pages import architecture\n", language)
    text = _visible_text(at)

    assert not at.exception
    assert "Human-in-the-loop" in text
    assert ("Prozess A" if language == "de" else "Process A") in text


def test_the_jargon_lists_are_kept_in_step():
    """A term listed for one language and forgotten for the other would
    leave that language unchecked without anything failing."""
    for language in LANGUAGES:
        assert JARGON[language], f"No jargon list for {language}"
    assert set(i18n.LANGUAGES) == set(JARGON), (
        "Every offered language needs its own jargon list."
    )
