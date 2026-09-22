"""Streamlit UI of the multi-agent system.

Shows a document's complete path: upload → process A or B → approval at
the risk points → confirmation with the effect in the target system.

The UI is not an afterthought, but the visible evidence of two of the
thesis's claims:

- **Least Privilege**: the signed-in user is also the submitter. Whoever is
  not in the AD security group does not get past the reader.
- **Human-in-the-loop**: whatever is waiting for approval does not proceed
  without a human decision.

This file is the router: it signs in, builds the navigation from the
registries, and runs the chosen page. There is no business logic here.

Start:  streamlit run ui/app.py
"""

from __future__ import annotations

import functools
import importlib
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import process_registry  # noqa: E402
import config  # noqa: E402
from data.bootstrap import ensure_configured_runtime  # noqa: E402
from graph.approval_queue import ApprovalTask, available_for  # noqa: E402
from ui.shared import i18n, style, theme  # noqa: E402
from ui.shared.context import (  # noqa: E402
    SESSION_USER,
    connection,
    current_user,
    graph,
    register_pages,
)
from ui.shared.identity import SqliteIdentityProvider  # noqa: E402
from ui.cases import live_ai_panel  # noqa: E402

st.set_page_config(page_title=i18n.t("app.page_title"),
                   page_icon="📄", layout="wide")


def _replace_session_identity(*, upn: str, token: str) -> None:
    """Start a clean UI session for a newly selected identity.

    Streamlit keeps widget values and custom-component state across reruns.
    None of that state may cross the identity boundary: in particular, the
    fixed AI drawer can otherwise continue to show the previous person's
    document.  Re-seed only the new authenticated identity; preferences are
    restored by their normal initialization on the following script run.
    """
    st.session_state.clear()
    st.session_state["auth_token"] = token
    st.session_state[SESSION_USER] = upn


def _demo_access() -> None:
    """Enter without a password while retaining distinct demo identities."""
    from governance import identity

    demo_portal_upns = getattr(identity, "demo_portal_upns", None)
    if demo_portal_upns is None:
        # Streamlit may retain an older imported module while hot-reloading
        # this entry point after identity.py gained new helpers.
        demo_portal_upns = importlib.reload(identity).demo_portal_upns
    provider = SqliteIdentityProvider(config.DB_PATH)
    style.css()
    roles = demo_portal_upns()
    accounts = {upn: provider.user(upn) for upn in roles}
    current = st.session_state.get(SESSION_USER)
    selected = st.sidebar.selectbox(
        "Demo-Rolle",
        roles,
        index=roles.index(current) if current in roles else 0,
        format_func=lambda upn: f"{accounts[upn].display_name} · {accounts[upn].rights_short}",
        help="Die Rolle simuliert eine Identität. Berechtigungen und Vier-Augen-Prinzip bleiben aktiv.",
    )
    con = connection()
    try:
        token = st.session_state.get("auth_token")
        try:
            principal = identity.principal(con, token) if token else None
        except identity.AuthenticationError:
            principal = None
        if principal != selected:
            if token and principal is not None:
                identity.logout(con, token)
            token = identity.issue_demo_session(con, selected)
        if current is not None and current != selected:
            _replace_session_identity(upn=selected, token=token)
            st.rerun()
        st.session_state["auth_token"] = token
        st.session_state[SESSION_USER] = selected
    finally:
        con.close()
    with style.account_topbar():
        with style.account_tab(accounts[selected]):
            style.account_details(accounts[selected], upn=selected)
            st.caption("Demo-Modus · simulierte Identität")


def _login() -> None:
    """Authenticate a local synthetic account; account selection is not sign-in."""
    if config.settings.portal_mode is config.PortalMode.DEMO:
        _demo_access()
        return
    from governance import identity
    provider = SqliteIdentityProvider(config.DB_PATH)
    style.css()
    token = st.session_state.get("auth_token")
    con = connection()
    try:
        try:
            upn = identity.principal(con, token) if token else None
        except identity.AuthenticationError:
            upn = None
            st.session_state.pop("auth_token", None)
        if upn:
            st.session_state[SESSION_USER] = upn
            person = provider.user(upn)
            with style.account_topbar():
                with style.account_tab(person):
                    style.account_details(person, upn=upn)
                    if st.button("Abmelden", key="logout"):
                        identity.logout(con, token)
                        st.session_state.clear()
                        st.rerun()
            return
        st.title("Anmelden")
        st.caption(f"Admin-Modus · vorkonfiguriertes Konto: {config.settings.portal_admin_email}")
        with st.form("login"):
            upn = st.text_input("Benutzerkonto")
            password = st.text_input("Passwort", type="password")
            submitted = st.form_submit_button("Anmelden")
        if submitted:
            try:
                normalized_upn = upn.strip()
                token = identity.login(con, normalized_upn, password)
                _replace_session_identity(upn=normalized_upn, token=token)
                st.rerun()
            except identity.AuthenticationError as error:
                st.error(str(error))
        st.info("Das Startpasswort des Administratorkontos steht in README.md. Weitere Konten werden über die Einrichtungsanleitung angelegt.")
        st.stop()
    finally:
        con.close()


def _build_pages(notification_tasks: list[ApprovalTask] | None = None) -> dict:
    """Builds the page objects.

    The process pages arise from `process_registry` -- an additional
    process thereby appears in the navigation on its own. `url_path` is
    explicit everywhere, because otherwise Streamlit derives the path from
    the function name and every page would be called `render`; slashes are
    not allowed in it.

    The paths themselves stay in one language regardless of the interface
    language: a URL is an address, and an address that moves when someone
    switches language cannot be shared.
    """
    from ui.pages import (architecture, audit, case, history, notifications,
                          preferences, process, settings, upload)

    notification_tasks = notification_tasks or []

    pages = {
        # 'Upload' is already the section -- the page is therefore not
        # called that again. Likewise 'Alle Vorgänge' instead of
        # 'Historische Vorgänge': the latter is a section heading within
        # the process pages and means something narrower there.
        #
        # No `url_path`: Streamlit's default page always sits at '/' and
        # ignores a custom one -- an '/upload' would go nowhere.
        "upload": st.Page(upload.render, title=i18n.t("page.upload"),
                          icon="📥", default=True),
        "history": st.Page(history.render, title=i18n.t("page.history"),
                           icon="🗂️", url_path="cases"),
        "notifications": st.Page(
            functools.partial(notifications.render, notification_tasks),
            title=i18n.t(
                "page.notifications.count", count=len(notification_tasks)
            ),
            icon=":material/notifications:",
            url_path="notifications",
        ),
        "audit": st.Page(audit.render, title=i18n.t("page.audit"), icon="🔐",
                         url_path="record"),
        "architecture": st.Page(architecture.render,
                                title=i18n.t("page.architecture"), icon="🏛️",
                                url_path="architecture"),
        "settings": st.Page(settings.render, title=i18n.t("page.settings"),
                            icon="⚙️", url_path="settings"),
        "preferences": st.Page(
            preferences.render, title=i18n.t("page.preferences"),
            icon="🌐", url_path="preferences",
        ),
        # No entry in the navigation: one arrives here from a list.
        "case": st.Page(case.render, title=i18n.t("page.case"), icon="📄",
                        url_path="case", visibility="hidden"),
    }
    for config in process_registry.all_processes():
        pages[config.route] = st.Page(
            functools.partial(process.render, config),
            title=i18n.process_text(config, "name"), icon=config.icon,
            url_path=config.route,
        )
    return pages


def main() -> None:
    try:
        ensure_configured_runtime()
    except FileNotFoundError as error:
        st.error(i18n.t("app.demo_seed_missing", error=error))
        st.stop()

    sync_native = getattr(theme, "sync_native", None)
    if sync_native is None:
        # Streamlit can retain an imported helper module while hot-reloading
        # this entry point. Reload only for that precise stale-module case.
        sync_native = importlib.reload(theme).sync_native
    sync_native()
    _login()
    live_ai_panel.mount()

    app, _ = graph()
    con = connection()
    try:
        notification_tasks = available_for(
            app,
            config.CHECKPOINT_PATH,
            con,
            actor=current_user(),
        )
    finally:
        con.close()

    from ui.pages import notifications
    notifications.announce_new(current_user(), notification_tasks)

    pages = _build_pages(notification_tasks)
    register_pages(pages)

    from governance.identity import session
    with session(st.session_state["auth_token"]):
        st.navigation({
            i18n.t("nav.tasks"): [pages["notifications"]],
            i18n.t("nav.upload"): [pages["upload"], pages["history"]],
            i18n.t("nav.case_types"): [pages[k.route]
                                       for k in process_registry.all_processes()],
            i18n.t("nav.evidence"): [pages["audit"], pages["architecture"]],
            i18n.t("nav.system"): [pages["preferences"], pages["settings"]],
            "": [pages["case"]],
        }).run()


main()
