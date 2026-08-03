"""Gemeinsame Laufzeitobjekte der Oberflaeche.

Graph, Datenbankverbindung und Sitzungszustand liegen hier, damit die
Seitenmodule sie nutzen koennen, ohne sich gegenseitig zu importieren.
"""

from __future__ import annotations

import sqlite3

import streamlit as st

from config import DB_PFAD

SITZUNG_NUTZER = "angemeldeter_nutzer"


@st.cache_resource
def graph():
    """Kompilierter Graph samt Checkpoint-Verbindung.

    `cache_resource`, weil der SQLite-Checkpointer eine offene Verbindung haelt
    -- pro Streamlit-Rerun neu zu kompilieren wuerde Verbindungen anhaeufen.
    """
    from graph.workflow import kompiliere
    return kompiliere()


def verbindung() -> sqlite3.Connection:
    """Frische Leseverbindung auf die Stammdaten.

    Bewusst nicht gecacht: Streamlit-Reruns laufen in wechselnden Threads, und
    eine geteilte SQLite-Verbindung ueber Threads hinweg ist nicht zulaessig.
    """
    return sqlite3.connect(DB_PFAD)


def angemeldet() -> str:
    """UPN des angemeldeten Nutzers (von der Sidebar gesetzt)."""
    return st.session_state.get(SITZUNG_NUTZER, "")


def oeffne_vorgang(thread_id: str) -> None:
    """Springt zur Detailseite eines Vorgangs.

    Ueber Query-Parameter statt Sitzungszustand: so ist ein Vorgang verlinkbar
    und ueberlebt ein Neuladen der Seite.
    """
    st.query_params.clear()
    st.query_params["id"] = thread_id
    st.switch_page(seite("vorgang"))


def zeige_audit_zu(thread_id: str) -> None:
    """Springt in den Audit-Trail, vorgefiltert auf diesen Vorgang."""
    st.query_params.clear()
    st.query_params["vorgang"] = thread_id
    st.switch_page(seite("audit"))


# --- Seitenregister -------------------------------------------------------
# `st.switch_page` braucht das Seitenobjekt. Die Seiten entstehen in app.py;
# damit die Module untereinander springen koennen, ohne app.py zu importieren
# (Zirkelbezug), hinterlegt app.py sie hier.

_SEITEN: dict[str, object] = {}


def registriere_seiten(seiten: dict[str, object]) -> None:
    _SEITEN.clear()
    _SEITEN.update(seiten)


def seite(name: str):
    return _SEITEN[name]
