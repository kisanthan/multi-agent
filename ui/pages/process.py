"""Working view of a process -- one implementation for every process.

What distinguishes process A from process B lives entirely in
`process_registry`: name, target system, step sequence, business fields.
This page reads that and renders it. A third process needs no line here.
"""

from __future__ import annotations

import streamlit as st

from config import CHECKPOINT_PATH
from graph.cases import overview
from process_registry import ProcessConfig
from registry import REGISTRY, OversightMode
from ui.shared import user
from ui.shared import filter as filters
from ui.shared import style
from ui.shared.context import current_user, graph, connection
from ui.cases import list as case_list
from ui.cases.steps import steps_for


def render(config: ProcessConfig) -> None:
    style.css()
    st.title(config.name)
    st.caption(config.description)

    app, _ = graph()
    key = f"prozess_{config.key}"
    own_rows = filters.for_process(overview(app, CHECKPOINT_PATH),
                                   config.key)

    con = connection()
    try:
        person = user.load(con, current_user())
    finally:
        con.close()

    counts = filters.counts(own_rows)
    columns = st.columns(4)
    columns[0].metric(person.label_pending, counts["pending"])
    columns[1].metric("In Bearbeitung", counts["running"])
    columns[2].metric("Abgeschlossen", counts["completed"])
    columns[3].metric("Nicht abgeschlossen", counts["failed"])
    st.caption(f"Am Ende steht: {config.process_end} – "
               f"festgehalten in: {config.target_system}.")

    if not own_rows:
        st.info(f"Hier liegt noch kein Vorgang. Laden Sie unter „Upload“ eine "
                f"{config.document_kind} hoch.")
        _flow_overview(config)
        return

    selection = case_list.filter_bar(key=key,
                                     process_fixed=config.key)
    matches = filters.apply(own_rows, selection)

    case_list.section(
        filters.open_cases(matches), title="In Bearbeitung",
        key=f"{key}_offen", view="karten",
        empty_text="Zurzeit ist hier nichts in Bearbeitung.",
        config=config, filter_active=not selection.is_empty,
    )
    case_list.section(
        filters.closed_cases(matches), title="Erledigt",
        key=f"{key}_fertig",
        empty_text="Hier ist noch nichts erledigt.",
        config=config, filter_active=not selection.is_empty,
    )

    _flow_overview(config)


def _flow_overview(config: ProcessConfig) -> None:
    """The process-specific slice of what the architecture page shows in full."""
    with st.expander("So läuft dieser Vorgang ab"):
        style.stepper(steps_for(config.key, []))
        for step in config.steps:
            if not step.agent_id:
                continue
            cfg = REGISTRY[step.agent_id]
            if cfg.oversight is OversightMode.HUMAN_IN_THE_LOOP:
                note = "🔒 Eine Person muss diesen Schritt bestätigen."
            elif cfg.can_write:
                note = "Wird automatisch ausgeführt und protokolliert."
            else:
                note = "Wird automatisch ausgeführt, ohne etwas zu ändern."
            st.markdown(
                f'<div class="feldzeile"><b>{step.title}</b> — {note}</div>',
                unsafe_allow_html=True,
            )
        st.caption("Welche Rolle und welche Berechtigung hinter jedem Schritt "
                   "steht, zeigt die Seite „Architektur“.")
