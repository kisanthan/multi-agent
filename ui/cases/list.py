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
from ui.shared import style
from ui.shared.filter import PAGE_SIZE, Filter, apply
from ui.shared.formatting import label, date_only, timestamp
from ui.shared.context import open_case

def _document_kind(key: str | None) -> str:
    """What kind of document this is -- not what the process is called.

    A case list shows a single document; "Zahlungsbestätigung" says more
    about it than "Zahlungseingang". As long as the analysis is still
    running, the kind is not yet known.
    """
    if not key:
        return "wird erkannt"
    return process_registry.get_config(key).document_kind


# ------------------------------------------------------------------ Filter bar

def filter_bar(*, key: str, process_fixed: str | None = None) -> Filter:
    """Collects the filter inputs.

    On a process page, the process is already determined by the page --
    then the field is not offered, instead of showing it pointlessly.
    """
    top = st.columns([3, 2, 2] if process_fixed else [3, 2, 2, 2])
    search = top[0].text_input("Suche", key=f"suche_{key}",
                               placeholder="Beleg, Person, Ergebnis …")

    col = 1
    processes: set[str] = set()
    if not process_fixed:
        chosen = top[col].multiselect(
            "Belegart", [p.key for p in process_registry.all_processes()],
            format_func=_document_kind, key=f"proz_{key}")
        processes = set(chosen)
        col += 1

    statuses = top[col].multiselect(
        "Status", list(Status), format_func=lambda s: s.label,
        key=f"stat_{key}")
    date_range = top[col + 1].date_input(
        "Eingegangen zwischen", value=(), key=f"zeit_{key}",
        help="Leer lassen, um alle Vorgänge zu sehen")

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
                parts = [f"von {z.actor}"]
                if with_process:
                    parts.insert(0, _document_kind(z.process))
                st.caption(" · ".join(parts))
            with middle:
                st.markdown(style.badge(z.status), unsafe_allow_html=True)
                st.caption(f"Gestartet {timestamp(z.started_at)}")
            with right:
                if st.button("Öffnen", key=f"o_{key}_{z.thread_id}",
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
    limit_key = f"anzahl_{key}"
    limit = st.session_state.get(limit_key, PAGE_SIZE)
    visible = rows[:limit]

    columns = ["Beleg", "Belegart", "Status", "Hochgeladen von",
               "Eingegangen", "Ergebnis"]
    if config:
        columns.remove("Belegart")

    st.dataframe(
        [{
            "Beleg": z.filename,
            **({} if config else
               {"Belegart": _document_kind(z.process)}),
            "Status": z.status.label,
            "Hochgeladen von": z.actor,
            "Eingegangen": date_only(z.started_at),
            "Ergebnis": z.outcome or "—",
        } for z in visible],
        column_order=columns, use_container_width=True, hide_index=True,
    )

    if len(rows) > limit:
        if st.button(f"Weitere {min(PAGE_SIZE, len(rows) - limit)} anzeigen",
                     key=f"mehr_{key}"):
            st.session_state[limit_key] = limit + PAGE_SIZE
            st.rerun()
        st.caption(f"{len(visible)} von {len(rows)} Vorgängen")

    # A table cannot be clicked -- the selection therefore goes through a
    # field, so historical cases remain reachable too.
    choice = st.selectbox(
        "Vorgang öffnen", ["—", *[z.thread_id for z in visible]],
        format_func=lambda t: t if t == "—" else next(
            (f"{z.filename} · {timestamp(z.started_at)}"
             for z in visible if z.thread_id == t), t),
        key=f"wahl_{key}",
    )
    if choice != "—":
        open_case(choice)


# ------------------------------------------------------------------ Empty state

def empty_state(text: str, *, filter_active: bool, key: str) -> None:
    if filter_active:
        st.info("Keine Vorgänge passen zu Ihrer Suche.")
        if st.button("Suche zurücksetzen", key=f"reset_{key}"):
            for prefix in ("suche_", "proz_", "stat_", "zeit_"):
                st.session_state.pop(f"{prefix}{key}", None)
            st.rerun()
    else:
        st.info(text)


# ------------------------------------------------------- Composed view

def section(rows: list[CaseOverview], *, title: str, key: str,
           view: str = "tabelle", empty_text: str = "Keine Vorgänge.",
           config=None, filter_active: bool = False) -> None:
    """A labeled list section."""
    style.section_title(title)
    if not rows:
        empty_state(empty_text, filter_active=filter_active, key=key)
        return
    if view == "karten":
        as_cards(rows, key=key, with_process=config is None)
    else:
        as_table(rows, key=key, config=config)


def filtered(rows: list[CaseOverview], f: Filter) -> list[CaseOverview]:
    return apply(rows, f)


__all__ = ["section", "as_cards", "as_table", "filter_bar", "filtered",
           "empty_state", "label"]
