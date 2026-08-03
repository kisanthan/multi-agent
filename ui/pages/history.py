"""Page 'Alle Vorgänge': all cases, across processes.

The same data source as the process pages -- just without a process
filter. The separation is not duplication, but a different question: here
"what has been submitted overall", there "how does this process stand".
"""

from __future__ import annotations

import streamlit as st

from config import CHECKPOINT_PATH
from graph.cases import overview
from ui.shared import user
from ui.shared import filter as filters
from ui.shared import style
from ui.shared.context import current_user, graph, connection
from ui.cases import list as case_list

KEY = "historie"


def render() -> None:
    style.css()
    st.title("Alle Vorgänge")
    st.caption("Alle Zahlungseingänge und Eingangsrechnungen zusammen.")

    app, _ = graph()
    all_rows = overview(app, CHECKPOINT_PATH)

    con = connection()
    try:
        person = user.load(con, current_user())
    finally:
        con.close()

    if not all_rows:
        st.info("Noch keine Vorgänge. Laden Sie unter „Upload“ einen Beleg hoch.")
        return

    counts = filters.counts(all_rows)
    columns = st.columns(4)
    columns[0].metric(person.label_pending, counts["pending"])
    columns[1].metric("In Bearbeitung", counts["running"])
    columns[2].metric("Abgeschlossen", counts["completed"])
    columns[3].metric("Nicht abgeschlossen", counts["failed"])

    selection = case_list.filter_bar(key=KEY)
    matches = filters.apply(all_rows, selection)

    case_list.section(
        filters.open_cases(matches), title="In Bearbeitung",
        key=f"{KEY}_offen", view="karten",
        empty_text="Zurzeit ist nichts in Bearbeitung.",
        filter_active=not selection.is_empty,
    )
    case_list.section(
        filters.closed_cases(matches), title="Erledigt",
        key=f"{KEY}_fertig", empty_text="Noch nichts erledigt.",
        filter_active=not selection.is_empty,
    )
