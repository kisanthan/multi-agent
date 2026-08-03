"""Seite 'Vorgang': die Detailansicht eines einzelnen Vorgangs.

Eigene Route mit `?id=…` statt Sitzungszustand: ein Vorgang ist damit
verlinkbar und überlebt ein Neuladen der Seite. Ohne Eintrag in der
Seitenleiste -- man kommt aus einer Liste hierher, nicht aus der Navigation.
"""

from __future__ import annotations

import streamlit as st

from ui.shared import stil
from ui.shared.kontext import angemeldet, graph
from ui.vorgaenge import detail


def seite() -> None:
    stil.css()
    thread_id = st.query_params.get("id")

    if not thread_id:
        st.title("Vorgang")
        st.info("Kein Vorgang ausgewählt. Öffnen Sie einen Vorgang aus "
                "einer der Listen.")
        return

    app, _ = graph()
    st.title(thread_id.rsplit("-", 1)[0])
    st.caption("Vorgang", help=f"Kennung: {thread_id}")

    detail.zeige(app, thread_id, upn=angemeldet(), mit_titel=False)
