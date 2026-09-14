"""Shared runtime objects of the UI.

Graph, database connection, and session state live here, so the page
modules can use them without importing each other.
"""

from __future__ import annotations

import sqlite3

import streamlit as st

import config

SESSION_USER = "signed_in_user"


@st.cache_resource
def graph():
    """Compiled graph, including the checkpoint connection.

    `cache_resource`, because the SQLite checkpointer holds an open
    connection -- recompiling on every Streamlit rerun would accumulate
    connections.
    """
    from graph.workflow import compile_graph
    return compile_graph()


def connection() -> sqlite3.Connection:
    """Fresh read connection to the master data.

    Deliberately not cached: Streamlit reruns happen on varying threads, and
    a SQLite connection shared across threads is not allowed.
    """
    return sqlite3.connect(config.DB_PATH)


def current_user() -> str:
    """UPN of the signed-in user (set by the sidebar)."""
    return st.session_state.get(SESSION_USER, "")


def open_case(thread_id: str) -> None:
    """Jumps to a case's detail page.

    Via query parameter instead of session state: that way a case is
    linkable and survives a page reload.
    """
    st.switch_page(get_page("case"), query_params={"id": thread_id})


def show_audit_for(thread_id: str) -> None:
    """Jumps into the audit trail, pre-filtered to this case."""
    st.switch_page(get_page("audit"), query_params={"case": thread_id})


# --- Page registry ----------------------------------------------------------
# `st.switch_page` needs the page object. The pages are created in app.py; so
# the modules can jump between each other without importing app.py
# (circular reference), app.py registers them here.

_PAGES: dict[str, object] = {}


def register_pages(pages: dict[str, object]) -> None:
    _PAGES.clear()
    _PAGES.update(pages)


def get_page(name: str):
    return _PAGES[name]
