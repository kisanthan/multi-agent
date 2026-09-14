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
from ui.shared import i18n

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
    fixed = ["cases", "notifications", "record", "architecture", "settings",
             "preferences", "case"]

    assert len(set(routes)) == len(routes)
    assert not set(routes) & set(fixed)


def _account_selector(at: AppTest):
    """The sign-in selector, found by its label rather than by position."""
    return next(s for s in at.selectbox
                if s.label == i18n.t("app.switch_account"))


def _account_tab(at: AppTest):
    """The compact account tab shown permanently in the top bar."""
    return next(element for element in at.main
                if element.type == "popover")


def test_topbar_offers_ad_users_for_sign_in():
    at = _app()
    selection = _account_selector(at)

    assert selection.label == "Konto wechseln"
    assert selection.options, "Ohne AD-Nutzer wäre keine Anmeldung möglich"
    tab = _account_tab(at).proto.popover
    assert tab.label.startswith(f"{selection.value} · ")
    assert tab.icon == ":material/info:"
    assert tab.help
    assert not any(s.label == "Konto wechseln" for s in at.sidebar.selectbox)
    stylesheet = " ".join(m.body for m in at.markdown)
    assert ".st-key-account_topbar" in stylesheet
    assert "position:fixed" in stylesheet
    assert "right:3.75rem" in stylesheet
    assert "border-bottom:1px solid var(--app-border)" not in stylesheet


def test_preferences_offer_every_language_not_the_agent_configuration():
    """Language has its own settings page in the navigation."""
    app = _app()
    assert not any(s.label == i18n.t("app.language")
                   for s in app.sidebar.selectbox)
    agent_config = _page(_frame(
        "e.extern@partner-consulting.de", "settings.render()",
        "from ui.pages import settings\n",
    ))
    assert not any(s.label == i18n.t("app.language")
                   for s in agent_config.selectbox)
    at = _page(_frame(
        "e.extern@partner-consulting.de", "preferences.render()",
        "from ui.pages import preferences\n",
    ))
    picker = next(s for s in at.selectbox if s.label == i18n.t("app.language"))

    assert any(t.value == "Einstellungen" for t in at.title)
    assert set(picker.options) == set(i18n.LANGUAGES.values())


def test_switching_the_language_translates_the_interface():
    at = _page(_frame(
        "e.extern@partner-consulting.de", "preferences.render()",
        "from ui.pages import preferences\n",
    ))
    picker = next(s for s in at.selectbox if s.label == "Sprache")

    picker.set_value("en").run()

    assert not at.exception
    assert any(s.label == "Language" for s in at.selectbox)


def test_preferences_switch_between_light_and_dark_mode():
    at = _page(_frame(
        "e.extern@partner-consulting.de", "preferences.render()",
        "from ui.pages import preferences\n",
    ))
    switch = next(t for t in at.toggle if t.label == "Dunkelmodus")

    assert switch.value is False

    switch.set_value(True).run()

    assert not at.exception
    assert next(t for t in at.toggle if t.label == "Dunkelmodus").value is True
    stylesheet = " ".join(m.body for m in at.markdown)
    assert "--app-background: #0e1117" in stylesheet
    assert '[data-testid="stSidebar"]' in stylesheet
    for surface in (
        "stSidebarNavLink", "stAlert", "stExpander", "stDialog",
        "stVerticalBlockBorderWrapper", "stStatusWidget", "stTabs",
        "stDataFrame", "stForm", "stMetric", "stPopover", "stCodeBlock",
        "stFileUploaderDropzone", 'role="tooltip"',
        'data-baseweb="calendar"',
    ):
        assert surface in stylesheet, f"Dark-Mode-Regel fehlt für {surface}"

    next(t for t in at.toggle if t.label == "Dunkelmodus").set_value(False).run()

    assert not at.exception
    assert next(t for t in at.toggle if t.label == "Dunkelmodus").value is False
    stylesheet = " ".join(m.body for m in at.markdown)
    assert "--app-background:#ffffff" in stylesheet
    assert "--app-background: #0e1117" not in stylesheet
    assert "html, body, .stApp" in stylesheet
    assert '[data-testid="stSidebar"]' in stylesheet
    assert "background-color:var(--app-background) !important" in stylesheet


def test_dark_mode_applies_to_other_pages(upn):
    at = _page(_frame(
        upn,
        "history.render()",
        "from ui.shared import theme\n"
        "st.session_state[theme.SESSION_DARK_MODE] = True\n"
        "from ui.pages import history\n",
    ))

    assert not at.exception
    stylesheet = " ".join(m.body for m in at.markdown)
    assert "--app-background: #0e1117" in stylesheet


@pytest.mark.parametrize(("call", "preamble"), [
    ("upload.render()", "from ui.pages import upload\n"),
    ("history.render()", "from ui.pages import history\n"),
    ("process.render(process_registry.get_config('A'))",
     "import process_registry\nfrom ui.pages import process\n"),
    ("process.render(process_registry.get_config('B'))",
     "import process_registry\nfrom ui.pages import process\n"),
    ("audit.render()", "from ui.pages import audit\n"),
    ("architecture.render()", "from ui.pages import architecture\n"),
    ("preferences.render()", "from ui.pages import preferences\n"),
    ("settings.render()", "from ui.pages import settings\n"),
    ("case.render()", "from ui.pages import case\n"),
])
def test_every_navigation_page_renders_with_the_dark_theme(upn, call, preamble):
    at = _page(_frame(
        upn,
        call,
        "from ui.shared import theme\n"
        "st.session_state[theme.SESSION_DARK_MODE] = True\n"
        + preamble,
    ))

    assert not at.exception
    stylesheet = " ".join(m.body for m in at.markdown)
    assert "--app-background: #0e1117" in stylesheet


def test_topbar_names_the_accounts_capabilities():
    """The compact tab names the account and explains its rights on hover."""
    at = _app()
    options = _account_selector(at).options

    # The account selection lives inside the floating details container.
    extern = [o for o in options if o.startswith("Erik Extern")]
    keller = [o for o in options if o.startswith("Martina Keller")]
    if not (extern and keller):
        pytest.skip("Erwartete Testkonten fehlen in den Stammdaten.")

    _account_selector(at).set_value(extern[0]).run()
    tab = _account_tab(at).proto.popover
    text = " ".join(
        [m.body for m in at.main.markdown]
        + [c.value for c in at.main.caption]
    )
    assert tab.label == "Erik Extern · Nur lesen"
    assert "Vorgänge ansehen" in tab.help
    assert "keine Belege hochladen" in tab.help
    assert "SG-CHG" not in text
    # The full sign-in name is available inside the floating details panel.
    assert "e.extern@partner-consulting.de" in text

    _account_selector(at).set_value(keller[0]).run()
    tab = _account_tab(at).proto.popover
    text = " ".join(
        [m.body for m in at.main.markdown]
        + [c.value for c in at.main.caption]
    )
    assert tab.label == "Martina Keller · Hochladen"
    assert "Zahlungsbestätigungen oder Eingangsrechnungen hochladen" in tab.help
    assert "Zahlungsbestätigungen oder Eingangsrechnungen hochladen" in text


# ------------------------------------------------------------ Individual pages

def test_upload_page_offers_dropzone_without_case_history(upn):
    """Case history belongs only on the dedicated history page."""
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
    assert "Zuletzt hochgeladen" not in _text(at)


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


def test_settings_page_is_editable_for_configuration_admin():
    source = _frame(
        "s.hofmann@chg-meridian.com", "settings.render()",
        "from governance.ad import ensure_configuration_seed\n"
        "from ui.shared.context import connection\n"
        "con = connection(); ensure_configuration_seed(con); con.close()\n"
        "from ui.pages import settings\n",
    )
    at = _page(source)
    assert not at.exception
    assert any(t.value == "Agentenkonfiguration" for t in at.title)
    assert at.button, "Ein Konfigurations-Admin muss speichern und testen können"
    # Only the active profile is rendered. Hidden configuration panels no
    # longer create duplicate widgets or run work on every rerun.
    assert len([s for s in at.selectbox if s.label == "Anbieter"]) == 1
    assert len([b for b in at.button
                if b.label == "Verbindung prüfen und Modelle laden"]) == 1
    assert len([i for i in at.text_input if i.label == "Ollama-Adresse"]) == 1
    descriptions = " ".join(
        item.value for collection in (at.markdown, at.caption, at.info)
        for item in collection
    )
    assert "ausschließlich die Belegart" in descriptions
    assert "Orchestrator" in descriptions and "kein eigenes KI-Modell" in descriptions


def test_notifications_page_renders(upn):
    at = _page(_frame(
        upn,
        "notifications.render([])",
        "from ui.pages import notifications\n",
    ))

    assert not at.exception
    assert any(t.value == "Benachrichtigungen" for t in at.title)
    assert any("kein Vorgang" in i.value for i in at.info)


def test_settings_page_is_read_only_without_configuration_right():
    at = _page(_frame(
        "e.extern@partner-consulting.de", "settings.render()",
        "from ui.pages import settings\n",
    ))
    assert not at.exception
    assert any("nicht ändern" in item.value for item in at.info)
    assert not at.button


def test_agent_configuration_loads_provider_models_into_selectors():
    source = _frame(
        "s.hofmann@chg-meridian.com", "settings.render()",
        "from governance.ad import ensure_configuration_seed\n"
        "from ui.shared.context import connection\n"
        "con = connection(); ensure_configuration_seed(con); con.close()\n"
        "from ui.pages import settings\n"
        "from ui.settings import providers\n"
        "providers.list_models = lambda provider: ['model-a', 'model-b']\n",
    )
    at = _page(source)
    test_button = next(
        button for button in at.button
        if button.label == "Verbindung prüfen und Modelle laden"
    )
    test_button.click().run()

    assert not at.exception
    selectors = [box for box in at.selectbox if box.label == "Modell"]
    assert selectors
    assert all("model-a" in box.options and "model-b" in box.options
               for box in selectors)
    assert any("Verbunden" in message.value for message in at.success)
