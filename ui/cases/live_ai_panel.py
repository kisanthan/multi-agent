"""Live right-hand drawer summarizing model work for the current document."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import streamlit as st

from agents.shared.schemas import DocumentType
from contracts import CaseOutcome
from ui.cases.ai_drawer_component import ai_status_drawer
from ui.shared import i18n
from ui.shared.formatting import field

SESSION_SNAPSHOT = "live_ai_panel_snapshot"
SESSION_SLOT = "live_ai_panel_slot"
SESSION_RENDER_SEQUENCE = "live_ai_panel_render_sequence"
COMPONENT_KEY = "live_ai_status_drawer"

PAYMENT_FIELDS = ("number", "amount_eur")
INVOICE_FIELDS = (
    "number", "amount_eur", "supplier", "line_items", "cost_center_reference"
)


@dataclass(frozen=True)
class PanelSnapshot:
    case_id: str
    filename: str
    profiles: dict[str, dict[str, str]]
    reader_done: bool = False
    router_done: bool = False
    extraction_done: bool = False
    document_type: str | None = None
    extraction_profile: str | None = None
    extracted: tuple[tuple[str, object], ...] = ()
    error: str | None = None


def snapshot_from_state(state: dict, previous: PanelSnapshot | None = None) -> PanelSnapshot:
    """Derive the panel from persisted workflow state, without UI logic."""
    logs = {entry.get("node") for entry in state.get("log", [])}
    document_type = state.get("document_type")
    payment_done = "extraktion_zahlung" in logs
    invoice_done = "extraktion_rechnung" in logs

    if payment_done:
        profile = "payment"
        keys = PAYMENT_FIELDS
    elif invoice_done:
        profile = "invoice"
        keys = INVOICE_FIELDS
    else:
        profile = None
        keys = ()

    model_error = None
    if state.get("outcome") == CaseOutcome.MODEL_UNAVAILABLE.value:
        model_error = state.get("error") or i18n.t("ai_panel.model_unavailable")
    elif state.get("escalation") and (
        document_type == DocumentType.UNKNOWN.value or payment_done or invoice_done
    ):
        model_error = state.get("escalation")

    return PanelSnapshot(
        case_id=state.get("case_id") or (previous.case_id if previous else ""),
        filename=(state.get("filename") or Path(state.get("path", "")).name
                  or (previous.filename if previous else "")),
        profiles=state.get("model_profiles") or (previous.profiles if previous else {}),
        reader_done="reader" in logs,
        router_done="klassifikation" in logs,
        extraction_done=payment_done or invoice_done,
        document_type=document_type,
        extraction_profile=profile,
        extracted=tuple((key, state.get(key)) for key in keys),
        error=model_error,
    )


def _model(snapshot: PanelSnapshot, profile: str) -> str:
    configured = snapshot.profiles.get(profile, {})
    provider = configured.get("provider", "—")
    model_id = configured.get("model_id", "—")
    return f"{provider} · {model_id}"


def _document_type(snapshot: PanelSnapshot) -> str:
    if snapshot.document_type == DocumentType.PAYMENT_CONFIRMATION.value:
        return i18n.t("ai_panel.type.payment")
    if snapshot.document_type == DocumentType.INCOMING_INVOICE.value:
        return i18n.t("ai_panel.type.invoice")
    return i18n.t("ai_panel.type.unknown")


def _active_extraction_profile(snapshot: PanelSnapshot) -> str | None:
    if snapshot.document_type == DocumentType.PAYMENT_CONFIRMATION.value:
        return "payment"
    if snapshot.document_type == DocumentType.INCOMING_INVOICE.value:
        return "invoice"
    return None


def _status(snapshot: PanelSnapshot) -> tuple[str, str]:
    if snapshot.error:
        return i18n.t("ai_panel.needs_review"), "error"
    if snapshot.extraction_done:
        return i18n.t("ai_panel.complete"), "complete"
    if snapshot.router_done:
        return i18n.t("ai_panel.extracting"), "running"
    if snapshot.reader_done:
        return i18n.t("ai_panel.routing"), "running"
    return i18n.t("ai_panel.reading"), "running"


def _extracted_rows(snapshot: PanelSnapshot) -> list[dict[str, str]]:
    """Format the small extraction result as a readable two-column table."""
    field_heading = i18n.t("ai_panel.column.field")
    value_heading = i18n.t("ai_panel.column.value")
    return [
        {field_heading: label_text, value_heading: formatted}
        for key, value in snapshot.extracted
        for label_text, formatted in (field(key, value),)
    ]


def _component_data(snapshot: PanelSnapshot, *, force_open: bool) -> dict:
    """Build the serializable presentation model consumed by the drawer."""
    label, status = _status(snapshot)
    steps: list[dict[str, str]] = []

    steps.append({
        "label": (i18n.t("ai_panel.reader_done") if snapshot.reader_done
                  else i18n.t("ai_panel.reading")),
        "state": "complete" if snapshot.reader_done else "running",
    })

    if snapshot.reader_done:
        router_step = {
            "label": (i18n.t("ai_panel.router_done") if snapshot.router_done
                      else i18n.t("ai_panel.routing")),
            "state": "complete" if snapshot.router_done else "running",
            "model": (
                _model(snapshot, "router") if snapshot.router_done
                else i18n.t(
                    "ai_panel.active_model",
                    model=_model(snapshot, "router"),
                )
            ),
        }
        if snapshot.router_done:
            router_step["detail"] = _document_type(snapshot)
        steps.append(router_step)

    extraction_profile = _active_extraction_profile(snapshot)
    if snapshot.router_done and extraction_profile:
        steps.append({
            "label": (i18n.t("ai_panel.extraction_done")
                      if snapshot.extraction_done
                      else i18n.t("ai_panel.extracting")),
            "state": "complete" if snapshot.extraction_done else "running",
            "model": (
                _model(snapshot, extraction_profile)
                if snapshot.extraction_done
                else i18n.t(
                    "ai_panel.active_model",
                    model=_model(snapshot, extraction_profile),
                )
            ),
        })

    field_heading = i18n.t("ai_panel.column.field")
    value_heading = i18n.t("ai_panel.column.value")
    rows = [
        {"field": row[field_heading], "value": row[value_heading]}
        for row in _extracted_rows(snapshot)
    ] if snapshot.extraction_done else []

    return {
        "initial_open": True,
        "force_open": force_open,
        "open_revision": snapshot.case_id,
        "document": i18n.t("ai_panel.document", filename=snapshot.filename),
        "status": {"label": label, "state": status},
        "steps": steps,
        "rows": rows,
        "error": (i18n.t("ai_panel.error", error=snapshot.error)
                  if snapshot.error else None),
        "labels": {
            "title": i18n.t("ai_panel.title"),
            "results": i18n.t("ai_panel.extracted_fields"),
            "field": field_heading,
            "value": value_heading,
            "expand": i18n.t("ai_panel.expand"),
            "collapse": i18n.t("ai_panel.collapse"),
        },
    }


def _next_component_key() -> str:
    """Return a key unique within the current Streamlit script run.

    A workflow can replace the drawer several times while a single script
    run is still active. Streamlit's element registry keeps every key seen in
    that run even when an ``st.empty`` placeholder is replaced, so each live
    update needs its own instance key.
    """
    sequence = st.session_state.get(SESSION_RENDER_SEQUENCE, 0) + 1
    st.session_state[SESSION_RENDER_SEQUENCE] = sequence
    return f"{COMPONENT_KEY}_{sequence}"


def render(slot, snapshot: PanelSnapshot, *, force_open: bool) -> None:
    """Render or replace the complete fixed-position drawer."""
    with slot.container():
        ai_status_drawer(
            _component_data(snapshot, force_open=force_open),
            key=_next_component_key(),
        )


def mount() -> None:
    """Reserve an app-wide slot and restore the last drawer snapshot."""
    # ``mount`` runs once at the start of every Streamlit script run. Reset
    # the live-update sequence so the component identity remains predictable
    # across reruns while still being unique within this run.
    st.session_state[SESSION_RENDER_SEQUENCE] = 0
    snapshot = st.session_state.get(SESSION_SNAPSHOT)
    slot = st.empty()
    st.session_state[SESSION_SLOT] = slot
    if snapshot:
        render(slot, snapshot, force_open=False)


def begin(state: dict) -> None:
    snapshot = snapshot_from_state(state)
    st.session_state[SESSION_SNAPSHOT] = snapshot
    slot = st.session_state.get(SESSION_SLOT)
    if slot is None:
        slot = st.empty()
    st.session_state[SESSION_SLOT] = slot
    render(slot, snapshot, force_open=True)


def update(state: dict) -> None:
    previous = st.session_state.get(SESSION_SNAPSHOT)
    snapshot = snapshot_from_state(state, previous)
    st.session_state[SESSION_SNAPSHOT] = snapshot
    slot = st.session_state.get(SESSION_SLOT)
    if slot is None:
        slot = st.empty()
    st.session_state[SESSION_SLOT] = slot
    render(slot, snapshot, force_open=True)


def fail(error: Exception) -> None:
    previous = st.session_state.get(SESSION_SNAPSHOT)
    if not previous:
        return
    snapshot = replace(previous, error=str(error))
    st.session_state[SESSION_SNAPSHOT] = snapshot
    slot = st.session_state.get(SESSION_SLOT)
    if slot is None:
        slot = st.empty()
    st.session_state[SESSION_SLOT] = slot
    render(slot, snapshot, force_open=True)
