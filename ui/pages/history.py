"""Page 'Alle Vorgänge': all cases, across processes.

The same data source as the process pages -- just without a process
filter. The separation is not duplication, but a different question: here
"what has been submitted overall", there "how does this process stand".
"""

from __future__ import annotations

import streamlit as st

from config import CHECKPOINT_PATH
from graph.cases import overview
from ui.shared import i18n
from ui.shared import user
from ui.shared import filter as filters
from ui.shared import style
from ui.shared.context import current_user, graph, connection
from ui.cases import list as case_list

KEY = "history"


def render() -> None:
    style.css()
    st.title(i18n.t("history.title"))
    st.caption(i18n.t("history.caption"))

    app, _ = graph()
    all_rows = overview(app, CHECKPOINT_PATH)

    con = connection()
    try:
        person = user.load(con, current_user())
    finally:
        con.close()

    if not all_rows:
        st.info(i18n.t("history.empty"))
        return

    counts = filters.counts(all_rows)
    columns = st.columns(4)
    columns[0].metric(person.label_pending, counts["pending"])
    columns[1].metric(i18n.t("metric.in_progress"), counts["running"])
    columns[2].metric(i18n.t("metric.completed"), counts["completed"])
    columns[3].metric(i18n.t("metric.not_completed"), counts["failed"])

    selection = case_list.filter_bar(key=KEY)
    matches = filters.apply(all_rows, selection)

    case_list.section(
        filters.open_cases(matches), title=i18n.t("section.in_progress"),
        key=f"{KEY}_open", view="cards",
        empty_text=i18n.t("history.empty.open"),
        filter_active=not selection.is_empty,
    )
    case_list.section(
        filters.closed_cases(matches), title=i18n.t("section.done"),
        key=f"{KEY}_done", empty_text=i18n.t("history.empty.done"),
        filter_active=not selection.is_empty,
    )
