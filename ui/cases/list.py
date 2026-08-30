"""Case lists -- one implementation for every page.

Two views, deliberately used differently:

- **Cards** where action happens (open approvals, most recently submitted):
  more context per row and a direct button.
- **Table** where searching happens (history, completed cases): dense and
  built for many rows.

All views draw from the same source (`graph.cases.overview`) and differ
only in the filter -- there is no duplicated list logic.
"""

from __future__ import annotations

import streamlit as st

import process_registry
from graph.cases import Status, CaseOverview
from ui.shared import i18n, style
from ui.shared.filter import PAGE_SIZE, Filter
from ui.shared.formatting import label, date_only, timestamp
from ui.shared.context import open_case

def _document_kind(key: str | None) -> str:
    """What kind of document this is -- not what the process is called.

    A case list shows a single document; "Zahlungsbestätigung" says more
    about it than "Zahlungseingang". As long as the analysis is still
    running, the kind is not yet known.
    """
    if not key:
        return i18n.t("list.detecting")
    return i18n.process_text(process_registry.get_config(key), "document_kind")


# ------------------------------------------------------------------ Filter bar

def filter_bar(*, key: str, process_fixed: str | None = None) -> Filter:
    """Collects the filter inputs.

    On a process page, the process is already determined by the page --
    then the field is not offered, instead of showing it pointlessly.
    """
    top = st.columns([3, 2, 2] if process_fixed else [3, 2, 2, 2])
    search = top[0].text_input(i18n.t("filter.search"), key=f"search_{key}",
                               placeholder=i18n.t("filter.search.placeholder"))

    col = 1
    processes: set[str] = set()
    if not process_fixed:
        chosen = top[col].multiselect(
            i18n.t("filter.document_kind"),
            [p.key for p in process_registry.all_processes()],
            format_func=_document_kind, key=f"kind_{key}")
        processes = set(chosen)
        col += 1

    statuses = top[col].multiselect(
        i18n.t("filter.status"), list(Status), format_func=i18n.status_label,
        key=f"status_{key}")
    date_range = top[col + 1].date_input(
        i18n.t("filter.received_between"), value=(), key=f"period_{key}",
        help=i18n.t("filter.received_between.help"))

    date_from = date_to = ""
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        date_from, date_to = date_range[0].isoformat(), date_range[1].isoformat()

    return Filter(search=search, processes=frozenset(processes),
                  statuses=frozenset(statuses), date_from=date_from, date_to=date_to)


# ---------------------------------------------------------------------- Cards

def as_cards(rows: list[CaseOverview], *, key: str,
            with_process: bool = True) -> None:
    for z in rows:
        with st.container(border=True):
            left, middle, right = st.columns([4, 3, 1.4])
            with left:
                st.markdown(f"**{z.filename}**")
                parts = [i18n.t("list.by", actor=z.actor)]
                if with_process:
                    parts.insert(0, _document_kind(z.process))
                st.caption(" · ".join(parts))
            with middle:
                st.markdown(style.badge(z.status), unsafe_allow_html=True)
                st.caption(i18n.t("list.started", time=timestamp(z.started_at)))
            with right:
                if st.button(i18n.t("list.open"), key=f"open_{key}_{z.thread_id}",
                             use_container_width=True):
                    open_case(z.thread_id)


# -------------------------------------------------------------------- Table

def as_table(rows: list[CaseOverview], *, key: str,
            config=None) -> None:
    """Dense view with incremental loading.

    Loading more instead of paging: Streamlit re-renders on every
    interaction, and a page number in session state would be additional
    state that would have to be kept consistent with filters.
    """
    limit_key = f"limit_{key}"
    limit = st.session_state.get(limit_key, PAGE_SIZE)
    visible = rows[:limit]

    # The column headers are also the row dicts' keys, so both come from the
    # same lookups -- a translated header with an untranslated key would
    # silently produce an empty column.
    head = {name: i18n.t(f"column.{name}") for name in
            ("document", "document_kind", "status", "uploaded_by",
             "received", "outcome")}
    columns = [head["document"], head["document_kind"], head["status"],
               head["uploaded_by"], head["received"], head["outcome"]]
    if config:
        columns.remove(head["document_kind"])

    style.dataframe(
        [{
            head["document"]: z.filename,
            **({} if config else
               {head["document_kind"]: _document_kind(z.process)}),
            head["status"]: i18n.status_label(z.status),
            head["uploaded_by"]: z.actor,
            head["received"]: date_only(z.started_at),
            head["outcome"]: z.outcome or "—",
        } for z in visible],
        column_order=columns, use_container_width=True, hide_index=True,
    )

    if len(rows) > limit:
        if st.button(i18n.t("list.show_more",
                            count=min(PAGE_SIZE, len(rows) - limit)),
                     key=f"more_{key}"):
            st.session_state[limit_key] = limit + PAGE_SIZE
            st.rerun()
        st.caption(i18n.t("list.count", shown=len(visible), total=len(rows)))

    # A table cannot be clicked -- the selection therefore goes through a
    # field, so historical cases remain reachable too.
    choice = st.selectbox(
        i18n.t("list.open_case"), ["—", *[z.thread_id for z in visible]],
        format_func=lambda t: t if t == "—" else next(
            (f"{z.filename} · {timestamp(z.started_at)}"
             for z in visible if z.thread_id == t), t),
        key=f"choice_{key}",
    )
    if choice != "—":
        open_case(choice)


# ------------------------------------------------------------------ Empty state

def empty_state(text: str, *, filter_active: bool, key: str) -> None:
    if filter_active:
        st.info(i18n.t("list.no_match"))
        if st.button(i18n.t("list.reset_search"), key=f"reset_{key}"):
            for prefix in ("search_", "kind_", "status_", "period_"):
                st.session_state.pop(f"{prefix}{key}", None)
            st.rerun()
    else:
        st.info(text)


# ------------------------------------------------------- Composed view

def section(rows: list[CaseOverview], *, title: str, key: str,
           view: str = "table", empty_text: str | None = None,
           config=None, filter_active: bool = False) -> None:
    """A labeled list section."""
    style.section_title(title)
    if not rows:
        empty_state(empty_text if empty_text is not None else i18n.t("list.empty"),
                    filter_active=filter_active, key=key)
        return
    if view == "cards":
        as_cards(rows, key=key, with_process=config is None)
    else:
        as_table(rows, key=key, config=config)


__all__ = ["section", "as_cards", "as_table", "filter_bar",
           "empty_state", "label"]
