"""Page 'Protokoll' (audit trail): the tamper-evident record.

The chain check sits at the top and **always** refers to the complete
trail, never to the filtered view: a filter must not create a statement
about integrity. When filtering is active, that is stated explicitly.

The frame around the table is translated -- headings, column names,
filters. The cells are not: actor, reason, and outcome are what was
recorded, and rephrasing them for display would mean rewriting the
evidence (see `ui/shared/i18n.py`).
"""

from __future__ import annotations

import csv
import io

import streamlit as st

import process_registry
from governance import ad
from governance.audit import read_all, verify_chain, cases_in_trail
from ui.shared import i18n, style
from ui.shared.formatting import timestamp
from ui.shared.context import current_user, connection

# Column order, as keys. The visible header of each comes from the catalog
# (`audit.column.<key>`) and is resolved per render, so a language switch
# retitles the table without touching this list.
COLUMN_KEYS = ["id", "time", "actor", "step", "document",
               "decision", "outcome", "reason", "checksum"]

# The internal decision of an entry, in words. 'info' means: neither
# allowed nor denied, simply recorded.
DECISION_VALUES = ["erlaubt", "verweigert", "info"]

# Components that have no process step of their own but still log entries.
OTHER_PARTICIPANTS = ("orchestrator", "policy", "audit")


def _columns() -> dict[str, str]:
    return {k: i18n.t(f"audit.column.{k}") for k in [*COLUMN_KEYS, "case"]}


def _decision_label(value: str) -> str:
    return i18n.t(f"audit.decision.{value}", default=value)


def _step_name(agent_id: str | None) -> str:
    """Plain label of the component that wrote the entry.

    The acting agents carry the same ID as their node in the flow -- the
    process registry supplies the name for them. The remaining components
    are in `OTHER_PARTICIPANTS`.

    This passes an *agent ID* into `step_title()`, which is documented to
    take a *node name* -- correct today only because `step_title()` matches
    on `ProcessStep.node`, and every step's node name happens to equal its
    own agent_id except `klaerfall` (node="klaerfall", agent_id="buchung").
    Since that step's *node* is not "buchung", it does not shadow the real
    "buchung" step here. Do not replace this with an agent-id-based lookup
    (e.g. matching on `ProcessStep.agent_id`) -- process A's own_steps list
    `klaerfall` before `buchung`, so a first-match-by-agent_id lookup would
    resolve "buchung" to "klaerfall"'s title instead and mislabel every
    booking entry as an approval decision. Pinned by
    tests/test_process_registry.py.
    """
    if not agent_id:
        return "—"
    if agent_id in OTHER_PARTICIPANTS:
        return i18n.t(f"audit.participant.{agent_id}")
    return i18n.t(f"step.{agent_id}.title",
                  default=process_registry.step_title(agent_id))


def _as_row(e, columns: dict[str, str]) -> dict:
    return {
        columns["id"]: e.id,
        columns["time"]: timestamp(e.ts),
        columns["actor"]: e.actor,
        columns["step"]: _step_name(e.agent),
        columns["document"]: e.source or "—",
        columns["decision"]: _decision_label(e.decision.value),
        columns["outcome"]: e.outcome or "—",
        columns["reason"]: e.reason,
        columns["checksum"]: e.hash[:12] + "…",
        columns["case"]: e.case_id or "—",
    }


def render() -> None:
    style.css()
    st.title(i18n.t("audit.title"))
    st.caption(i18n.t("audit.caption"))

    upn = current_user()
    con = connection()
    try:
        chain = verify_chain(con)
        all_entries = read_all(con)
        known_cases = cases_in_trail(con)
        can_export = ad.check_approval_permission(con, upn).allowed
    finally:
        con.close()

    if chain.valid:
        st.success(i18n.t("audit.chain.valid", count=chain.checked))
    else:
        st.error(i18n.t("audit.chain.broken", detail=chain))

    if not all_entries:
        st.info(i18n.t("audit.empty"))
        return

    everything = i18n.t("word.all")

    # Preselected from a case (?case=…).
    preselected = st.query_params.get("case")
    options = [everything, *known_cases]
    index = options.index(preselected) if preselected in options else 0

    top = st.columns([3, 3, 2, 2])
    search = top[0].text_input(i18n.t("filter.search"),
                               placeholder=i18n.t("audit.search.placeholder"))
    case = top[1].selectbox(
        i18n.t("audit.filter.case"), options, index=index,
        format_func=lambda v: v if v == everything else v.rsplit("-", 1)[0])
    agent_ids = sorted({e.agent for e in all_entries if e.agent})
    agent = top[2].selectbox(
        i18n.t("audit.filter.step"), [everything, *agent_ids],
        format_func=lambda a: a if a == everything else _step_name(a))
    decision = top[3].selectbox(
        i18n.t("audit.filter.decision"), [everything, *DECISION_VALUES],
        format_func=lambda e: e if e == everything else _decision_label(e))

    matches = all_entries
    if case != everything:
        matches = [e for e in matches if e.case_id == case]
    if agent != everything:
        matches = [e for e in matches if e.agent == agent]
    if decision != everything:
        matches = [e for e in matches if e.decision.value == decision]
    if search:
        term = search.lower()
        matches = [e for e in matches if term in " ".join([
            e.actor, e.agent or "", e.action, e.reason,
            e.source or "", e.outcome or ""]).lower()]

    filtered = len(matches) != len(all_entries)
    if filtered:
        st.caption(i18n.t("audit.filtered", shown=len(matches),
                          total=len(all_entries)))

    columns = _columns()
    style.dataframe([_as_row(e, columns) for e in reversed(matches)],
                    column_order=[columns[k] for k in COLUMN_KEYS],
                    use_container_width=True, hide_index=True)

    if can_export:
        st.download_button(
            i18n.t("audit.download"), _to_csv(matches, chain, columns),
            file_name=i18n.t("audit.download.filename"), mime="text/csv",
        )
    else:
        st.caption(i18n.t("audit.no_download"))


def _to_csv(entries, chain, columns: dict[str, str]) -> str:
    """CSV with the chain status in the header.

    The status belongs in the file: an exported excerpt without the
    statement of whether the chain was intact is worthless as evidence.
    """
    buffer = io.StringIO()
    buffer.write(i18n.t("audit.csv.header", chain=chain) + "\n")
    fieldnames = [columns[k] for k in [*COLUMN_KEYS, "case"]]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames,
                            delimiter=";", extrasaction="ignore")
    writer.writeheader()
    for e in entries:
        writer.writerow(_as_row(e, columns))
    return buffer.getvalue()
