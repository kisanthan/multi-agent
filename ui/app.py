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


def _login() -> None:
    """Top bar: compact account tab with details in a floating panel.

    In the prototype, a selection instead of a real sign-in -- but the
    rights behind it are the real group memberships from the directory
    service.

    The tab itself stays deliberately terse: display name and effective
    rights are enough for orientation. The sign-in name, account selector,
    and the plain-language capability description live in a popover. Its
    help text also exposes the description on hover.

    """
    identity = SqliteIdentityProvider(config.DB_PATH)
    accounts = identity.accounts()

    style.css()

    if not accounts:
        st.error(i18n.t("app.no_accounts"))
        st.stop()

    names = [account.display_name for account in accounts]
    unique = len(set(names)) == len(names)
    labels = {
        (account.display_name if unique
         else f"{account.display_name} ({account.upn})"): account.upn
        for account in accounts
    }

    current_upn = st.session_state.get(SESSION_USER)
    if current_upn not in labels.values():
        current_upn = accounts[0].upn
    st.session_state[SESSION_USER] = current_upn

    selector_key = "account_selector"
    current_label = next(
        label for label, account_upn in labels.items()
        if account_upn == current_upn
    )
    if st.session_state.get(selector_key) != current_label:
        st.session_state[selector_key] = current_label

    def select_account() -> None:
        selected_label = st.session_state[selector_key]
        st.session_state[SESSION_USER] = labels[selected_label]

    upn = current_upn
    person = identity.user(upn)

    with style.account_topbar():
        with style.account_tab(person):
            st.caption(i18n.t("app.signed_in_as"))
            st.selectbox(
                i18n.t("app.switch_account"),
                list(labels),
                key=selector_key,
                on_change=select_account,
            )
            style.account_details(person, upn=upn)


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
