"""Case detail view: stepper, approval, confirmation.

One view for all processes -- what differs by business (which fields
appear in the header) comes from `process_registry`, not from case
distinctions here.
"""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

import process_registry
from agents import cost_center as cost_center_agent
from governance.audit import verify_chain
from governance.policy import check_approval
from graph.cases import Status, process_of, determine_status
from graph.effects import read_effect
from ui.shared import style
from ui.shared import user
from ui.shared.formatting import field
from ui.shared.context import connection, show_audit_for
from ui.cases.run import resume
from ui.cases.steps import steps_for

# Which agent is responsible for which approval point. Checking the
# permission against the wrong agent would be a silent bypass of the
# policy.
AGENT_FOR_INTERRUPT = {
    "klaerfall": "buchung",
    "kostenstellen_freigabe": "kostenstelle",
}

RESULT_TEXTS = {
    "verbucht": "Die Zahlung ist verbucht. Die Rechnung gilt als bezahlt.",
    "archiviert": "Die Rechnung ist revisionssicher abgelegt. Damit ist der "
                  "Vorgang beendet.",
    "verworfen": "Der Vorgang wurde abgelehnt. Es wurde nichts gebucht und "
                 "nichts abgelegt.",
    "zugriff_verweigert": "Der Beleg wurde nicht geöffnet: das Konto ist dazu "
                          "nicht berechtigt.",
    "abgelehnt": "Die Buchhaltung hat die Buchung abgelehnt.",
    "archivierung_fehlgeschlagen": "Die Ablage im Archiv ist fehlgeschlagen.",
}


def render(app, thread_id: str, *, upn: str, with_title: bool = True) -> None:
    """Renders a case in full."""
    snapshot = app.get_state({"configurable": {"thread_id": thread_id}})
    values = snapshot.values or {}

    if not values:
        st.warning("Zu diesem Vorgang liegen keine Daten vor. "
                   "Möglicherweise wurde er nie gestartet.")
        return

    request = snapshot.interrupts[0].value if snapshot.interrupts else None
    status = determine_status(values, waiting=bool(request))
    process = process_of(values)

    _header(values, status, process, thread_id, with_title=with_title)
    style.stepper(steps_for(process, values.get("log", []),
                            waiting_on=(request or {}).get("kind"), status=status))

    if request:
        _decision_form(app, thread_id, request, values, upn=upn)
    else:
        _outcome(values, status)

    with st.expander("Was bisher geschah"):
        for entry in values.get("log", []):
            st.markdown(
                f"**{process_registry.step_title(entry['node'])}** — "
                f"{entry['text']}")

    _document_preview(values.get("path"))

    if st.button("Protokoll zu diesem Vorgang", key=f"audit_{thread_id}",
                 use_container_width=False,
                 help="Zeigt alle protokollierten Schritte dieses Vorgangs"):
        show_audit_for(thread_id)


def _header(values: dict, status: Status, process: str | None, thread_id: str, *,
           with_title: bool) -> None:
    config = process_registry.get_config(process) if process else None
    # The document kind, not the process name: this is about a single
    # document, and "Zahlungsbestätigung" says more about it than
    # "Zahlungseingang". No "Prozess A" -- the A/B assignment lives on the
    # architecture page.
    process_text = (config.document_kind if config
                    else "Belegart wird noch erkannt")

    if with_title:
        st.subheader(values.get("filename") or thread_id)
    st.markdown(
        f"{style.badge(status)} &nbsp; <span style='opacity:0.75'>{process_text}</span>",
        unsafe_allow_html=True,
    )

    # Which fields matter for the business is known by the process.
    business_fields = list(config.detail_fields) if config else ["number"]
    left, right = st.columns(2)
    with left:
        style.fields(values, ["actor", "started_at"])
    with right:
        style.fields(values, business_fields)


def _decision_form(app, thread_id: str, request: dict, values: dict, *,
                   upn: str) -> None:
    """Here the case pauses until a human decides."""
    kind = request.get("kind", "")
    agent_id = AGENT_FOR_INTERRUPT.get(kind, "buchung")

    con = connection()
    try:
        person = user.load(con, upn)
        decision = check_approval(con, actor=upn, agent_id=agent_id)
    finally:
        con.close()

    # What appears here depends on who is looking: whoever may decide is
    # prompted to; whoever may not gets context instead of a prompt.
    if decision.allowed:
        st.markdown("#### Ihre Entscheidung")
    else:
        st.markdown("#### Wartet auf Bestätigung")

    rows = "".join(
        f"<div class='feldzeile'><b>{field(s, request[s])[0]}:</b> "
        f"{field(s, request[s])[1]}</div>"
        for s in ("reason", "finding", "escalation") if request.get(s)
    )
    st.markdown(f'<div class="karte">{rows}</div>', unsafe_allow_html=True)

    if request.get("line_items"):
        st.markdown("**Rechnungsposten:** " + ", ".join(request["line_items"]))

    cost_center_id = None
    if kind == "kostenstellen_freigabe":
        catalog = request.get("catalog") or []
        if not catalog:
            con = connection()
            try:
                catalog = [{"id": z[0], "name": z[1], "reference": z[2]}
                           for z in cost_center_agent.catalog(con)]
            finally:
                con.close()
        labels = {e["id"]: f"{e['id']} — {e['name']} ({e['reference']})"
                  for e in catalog}
        st.warning("Auf dem Beleg steht keine Kostenstelle, die zugeordnet "
                   "werden konnte. Bitte wählen Sie die passende aus.")
        cost_center_id = st.selectbox(
            "Kostenstelle", [e["id"] for e in catalog],
            format_func=lambda o: labels.get(o, o), key=f"kst_{thread_id}",
        )

    if not decision.allowed:
        # No error bar: for this person, this is not an error, simply not
        # their task.
        st.info(person.confirm_hint)
    elif values.get("actor") == upn:
        # Hint only. What is technically enforced so far is group
        # membership (governance/policy.py) -- forbidding the same person
        # would be a governance change (docs/grenzen.md L10).
        st.warning(person.own_document_hint)

    left, right = st.columns(2)
    with left:
        confirm = st.button("Bestätigen", key=f"f_{thread_id}", type="primary",
                            disabled=not decision.allowed, use_container_width=True)
    with right:
        reject = st.button("Ablehnen", key=f"v_{thread_id}",
                           disabled=not decision.allowed, use_container_width=True)

    if reject and not st.session_state.get(f"ablehnen_bestaetigt_{thread_id}"):
        st.session_state[f"ablehnen_bestaetigt_{thread_id}"] = True
        st.warning("Ablehnen beendet den Vorgang endgültig. Zum Fortfahren "
                   "erneut auf „Ablehnen“ klicken.")
        return

    if confirm or reject:
        response = {
            "decision": "freigegeben" if confirm else "verworfen",
            "approver": upn,
            "number": request.get("number"),
        }
        if cost_center_id:
            response["cost_center_id"] = cost_center_id
        st.session_state.pop(f"ablehnen_bestaetigt_{thread_id}", None)
        resume(app, thread_id=thread_id, response=response)
        st.rerun()


def _outcome(values: dict, status: Status) -> None:
    """Completion card: what actually happened in the end?"""
    if not values.get("completed"):
        st.info("Der Vorgang wird gerade bearbeitet.")
        return

    outcome = values.get("outcome", "")
    text = RESULT_TEXTS.get(outcome, f"Vorgang beendet: {outcome or 'unbekannt'}")

    st.markdown("#### Ergebnis")
    if status is Status.COMPLETED:
        st.success(text)
    elif status is Status.REJECTED:
        st.warning(text)
    else:
        st.error(text)

    if values.get("error"):
        st.caption(f"Rückmeldung: {values['error']}")

    con = connection()
    try:
        effect = read_effect(con, values)
        chain = verify_chain(con)
    finally:
        con.close()

    if effect.has_effect:
        cols = st.columns(2)
        if effect.navision_status:
            cols[0].metric(f"Rechnung {effect.navision_number}",
                          effect.navision_status.capitalize())
        if effect.elo_archive_id:
            cols[1].metric("Im Archiv abgelegt unter", effect.elo_archive_id)

    if values.get("approved_by"):
        st.caption(f"Bestätigt von {values['approved_by']}")

    st.caption(
        "✓ Das Protokoll dieses Systems ist unverändert."
        if chain.valid else
        f"✕ Das Protokoll wurde nachträglich verändert. {chain}"
    )


def _document_preview(path: str | None) -> None:
    """Shows the original PDF -- an approver does not decide without the document."""
    if not path or not Path(path).is_file():
        return
    with st.expander("Beleg ansehen"):
        data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{data}" '
            'width="100%" height="620" style="border:1px solid #ccc; '
            'border-radius:6px;"></iframe>',
            unsafe_allow_html=True,
        )
