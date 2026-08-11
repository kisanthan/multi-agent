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
import sqlite3
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import process_registry  # noqa: E402
from config import DB_PATH  # noqa: E402
from ui.shared import user, style  # noqa: E402
from ui.shared.context import SESSION_USER, register_pages  # noqa: E402

st.set_page_config(page_title="CHG-MERIDIAN Vorgangsbearbeitung",
                   page_icon="📄", layout="wide")


def _login() -> None:
    """Sidebar: account selection and what this account may do.

    In the prototype, a selection instead of a real sign-in -- but the
    rights behind it are the real group memberships from the directory
    service.

    The *capability* is shown as a sentence, not membership in a security
    group: the group name helps no one who cannot manage it anyway.
    """
    con = sqlite3.connect(DB_PATH)
    try:
        accounts = con.execute(
            "SELECT upn, display_name FROM ad_users ORDER BY display_name"
        ).fetchall()
        if not accounts:
            st.sidebar.error("Keine Benutzerkonten vorhanden. "
                             "Zuerst `python -m data.generate` ausführen.")
            st.stop()

        # Display name only: the sign-in name does not fit the narrow
        # sidebar and was truncated there. It appears below it instead --
        # unless two accounts share a name, then it must go into the
        # selection.
        names = [name for _, name in accounts]
        unique = len(set(names)) == len(names)
        labels = {(name if unique else f"{name} ({upn})"): upn
                  for upn, name in accounts}

        # `with st.sidebar:` instead of individual `st.sidebar.xxx()` calls:
        # the status card is drawn via a plain `st.markdown()` (see
        # `style.status_card`), and without this block that would find its
        # way into the main area instead of the sidebar.
        with st.sidebar:
            style.css()

            choice = st.selectbox("Angemeldet als", list(labels))
            upn = labels[choice]
            st.session_state[SESSION_USER] = upn
            person = user.load(con, upn)

            # One card, one call: a badge for the quick glance, the full
            # sentence below it -- including the document kinds this
            # account may submit. Visible, not in a tooltip: what is only
            # found by hovering is not found.
            #
            # The sign-in name is only shown here if it is not already in
            # the selection itself (non-unique display names force it
            # there) -- otherwise it would appear twice.
            style.status_card(person, upn=upn if unique else None)
    finally:
        con.close()


def _build_pages() -> dict:
    """Builds the page objects.

    The process pages arise from `process_registry` -- an additional
    process thereby appears in the navigation on its own. `url_path` is
    explicit everywhere, because otherwise Streamlit derives the path from
    the function name and every page would be called `render`; slashes are
    not allowed in it.
    """
    from ui.pages import architecture, audit, history, process, upload, case

    pages = {
        # 'Upload' is already the section -- the page is therefore not
        # called that again. Likewise 'Alle Vorgänge' instead of
        # 'Historische Vorgänge': the latter is a section heading within
        # the process pages and means something narrower there.
        #
        # No `url_path`: Streamlit's default page always sits at '/' and
        # ignores a custom one -- an '/upload' would go nowhere.
        "upload": st.Page(upload.render, title="Neuer Beleg", icon="📥",
                          default=True),
        "historie": st.Page(history.render, title="Alle Vorgänge",
                            icon="🗂️", url_path="historie"),
        "audit": st.Page(audit.render, title="Protokoll", icon="🔐",
                         url_path="protokoll"),
        "architektur": st.Page(architecture.render, title="Architektur", icon="🏛️",
                               url_path="architektur"),
        # No entry in the navigation: one arrives here from a list.
        "vorgang": st.Page(case.render, title="Vorgang", icon="📄",
                           url_path="vorgang", visibility="hidden"),
    }
    for config in process_registry.all_processes():
        pages[config.route] = st.Page(
            functools.partial(process.render, config),
            title=config.name, icon=config.icon,
            url_path=config.route,
        )
    return pages


def main() -> None:
    _login()

    pages = _build_pages()
    register_pages(pages)

    st.navigation({
        "Upload": [pages["upload"], pages["historie"]],
        "Vorgangsarten": [pages[k.route] for k in process_registry.all_processes()],
        "Nachweis": [pages["audit"], pages["architektur"]],
        "": [pages["vorgang"]],
    }).run()


main()
