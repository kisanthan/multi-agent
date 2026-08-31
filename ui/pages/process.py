"""Working view of a process -- one implementation for every process.

What distinguishes process A from process B lives entirely in
`process_registry`: name, target system, step sequence, business fields.
This page reads that and renders it. A third process needs no line here.
"""

from __future__ import annotations

import streamlit as st

from config import CHECKPOINT_PATH
from graph.cases import overview
from agent_registry import REGISTRY, OversightMode
from process_registry import ProcessConfig
from ui.shared import i18n
from ui.shared import user
from ui.shared import filter as filters
from ui.shared import style
from ui.shared.context import current_user, graph, connection
from ui.cases import list as case_list
from ui.cases.steps import steps_for


def render(config: ProcessConfig) -> None:
    style.css()
    st.title(i18n.process_text(config, "name"))
    st.caption(i18n.process_text(config, "description"))

    app, _ = graph()
    key = f"process_{config.key}"
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
    columns[1].metric(i18n.t("metric.in_progress"), counts["running"])
    columns[2].metric(i18n.t("metric.completed"), counts["completed"])
    columns[3].metric(i18n.t("metric.not_completed"), counts["failed"])
    st.caption(i18n.t("process.ends_with",
                      end=i18n.process_text(config, "process_end"),
                      system=i18n.process_text(config, "target_system")))

    if not own_rows:
        st.info(i18n.t("process.empty",
                       kind=i18n.process_text(config, "document_kind")))
        _flow_overview(config)
        return

    selection = case_list.filter_bar(key=key,
                                     process_fixed=config.key)
    matches = filters.apply(own_rows, selection)

    case_list.section(
        filters.open_cases(matches), title=i18n.t("section.in_progress"),
        key=f"{key}_open", view="cards",
        empty_text=i18n.t("process.empty.open"),
        config=config, filter_active=not selection.is_empty,
    )
    case_list.section(
        filters.closed_cases(matches), title=i18n.t("section.done"),
        key=f"{key}_done",
        empty_text=i18n.t("process.empty.done"),
        config=config, filter_active=not selection.is_empty,
    )

    _flow_overview(config)


def _flow_overview(config: ProcessConfig) -> None:
    """The process-specific slice of what the architecture page shows in full."""
    with st.expander(i18n.t("process.flow")):
        style.stepper(steps_for(config.key, []))
        for step in config.steps:
            if not step.agent_id:
                continue
            cfg = REGISTRY[step.agent_id]
            if cfg.oversight is OversightMode.HUMAN_IN_THE_LOOP:
                note = i18n.t("process.flow.confirmed")
            elif cfg.can_write:
                note = i18n.t("process.flow.writes")
            else:
                note = i18n.t("process.flow.reads")
            style.value_row(i18n.step_title(step.node), note)
        st.caption(i18n.t("process.flow.footer"))
