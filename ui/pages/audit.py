"""Page 'Protokoll' (audit trail): the tamper-evident record.

The chain check sits at the top and **always** refers to the complete
trail, never to the filtered view: a filter must not create a statement
about integrity. When filtering is active, that is stated explicitly.
"""

from __future__ import annotations

import csv
import io

import streamlit as st

import process_registry
from governance import ad
from governance.audit import read_all, verify_chain, cases_in_trail
from ui.shared import style
from ui.shared.formatting import timestamp
from ui.shared.context import current_user, connection

COLUMNS = ["#", "Zeitpunkt", "Person oder System", "Schritt", "Beleg",
           "Bewertung", "Ergebnis", "Erläuterung", "Prüfsumme"]

# The internal decision of an entry, in words. 'info' means: neither
# allowed nor denied, simply recorded.
DECISION_LABELS = {"erlaubt": "Erlaubt", "verweigert": "Abgelehnt", "info": "Vermerk"}

# Components that have no process step of their own but still log entries.
OTHER_PARTICIPANTS = {
    "orchestrator": "Weiterleitung",
    "policy": "Berechtigungsprüfung",
    "audit": "Protokollierung",
}


def _step_name(agent_id: str | None) -> str:
    """Plain label of the component that wrote the entry.

    The acting agents carry the same ID as their node in the flow -- the
    process registry supplies the name for them. The remaining components
    are in `OTHER_PARTICIPANTS`.
    """
    if not agent_id:
        return "—"
    if agent_id in OTHER_PARTICIPANTS:
        return OTHER_PARTICIPANTS[agent_id]
    return process_registry.step_title(agent_id)


def _as_row(e) -> dict:
    return {
        "#": e.id,
        "Zeitpunkt": timestamp(e.ts),
        "Person oder System": e.actor,
        "Schritt": _step_name(e.agent),
        "Beleg": e.source or "—",
        "Bewertung": DECISION_LABELS.get(e.decision.value, e.decision.value),
        "Ergebnis": e.outcome or "—",
        "Erläuterung": e.reason,
        "Prüfsumme": e.hash[:12] + "…",
        "Vorgang": e.case_id or "—",
    }


def render() -> None:
    style.css()
    st.title("Protokoll")
    st.caption("Jeder Schritt jedes Vorgangs wird hier festgehalten – auch "
               "abgelehnte Zugriffe und zurückgewiesene Uploads. Die Einträge "
               "lassen sich nachträglich nicht ändern.")

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
        st.success(f"Das Protokoll ist unverändert – alle {chain.checked} "
                   "Einträge sind lückenlos.")
    else:
        st.error(f"Das Protokoll wurde nachträglich verändert. {chain}")

    if not all_entries:
        st.info("Noch keine Einträge vorhanden.")
        return

    # Preselected from a case (?vorgang=…).
    preselected = st.query_params.get("vorgang")
    options = ["Alle", *known_cases]
    index = options.index(preselected) if preselected in options else 0

    top = st.columns([3, 3, 2, 2])
    search = top[0].text_input("Suche", placeholder="Person, Beleg, Erläuterung …")
    case = top[1].selectbox(
        "Vorgang", options, index=index,
        format_func=lambda v: v if v == "Alle" else v.rsplit("-", 1)[0])
    agent_ids = sorted({e.agent for e in all_entries if e.agent})
    agent = top[2].selectbox(
        "Schritt", ["Alle", *agent_ids],
        format_func=lambda a: a if a == "Alle" else _step_name(a))
    decision = top[3].selectbox(
        "Bewertung", ["Alle", "erlaubt", "verweigert", "info"],
        format_func=lambda e: e if e == "Alle" else DECISION_LABELS[e])

    matches = all_entries
    if case != "Alle":
        matches = [e for e in matches if e.case_id == case]
    if agent != "Alle":
        matches = [e for e in matches if e.agent == agent]
    if decision != "Alle":
        matches = [e for e in matches if e.decision.value == decision]
    if search:
        term = search.lower()
        matches = [e for e in matches if term in " ".join([
            e.actor, e.agent or "", e.action, e.reason,
            e.source or "", e.outcome or ""]).lower()]

    filtered = len(matches) != len(all_entries)
    if filtered:
        st.caption(f"{len(matches)} von {len(all_entries)} Einträgen. Die Aussage "
                   "oben gilt für das vollständige Protokoll, nicht nur für "
                   "diese Auswahl.")

    st.dataframe([_as_row(e) for e in reversed(matches)],
                 column_order=COLUMNS, use_container_width=True, hide_index=True)

    if can_export:
        st.download_button(
            "Auswahl als CSV herunterladen", _to_csv(matches, chain),
            file_name="protokoll.csv", mime="text/csv",
        )
    else:
        st.caption("Zum Herunterladen des Protokolls ist Ihr Konto nicht "
                   "berechtigt.")


def _to_csv(entries, chain) -> str:
    """CSV with the chain status in the header.

    The status belongs in the file: an exported excerpt without the
    statement of whether the chain was intact is worthless as evidence.
    """
    buffer = io.StringIO()
    buffer.write(f"# Protokollprüfung: {chain}\n")
    writer = csv.DictWriter(buffer, fieldnames=[*COLUMNS, "Vorgang"],
                            delimiter=";", extrasaction="ignore")
    writer.writeheader()
    for e in entries:
        writer.writerow(_as_row(e))
    return buffer.getvalue()
