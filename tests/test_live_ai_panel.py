"""Tests for the live AI status overview shown in the right drawer."""

from __future__ import annotations

import pytest

from agents.shared.schemas import DocumentType
from ui.cases.ai_drawer_component import _CSS, _JS
from ui.cases.live_ai_panel import (
    PanelSnapshot,
    _component_data,
    _extracted_rows,
    snapshot_from_state,
)

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402


PROFILES = {
    "router": {"provider": "ollama", "model_id": "qwen2.5vl:7b"},
    "payment": {"provider": "ollama", "model_id": "qwen2.5vl:7b"},
    "invoice": {"provider": "ollama", "model_id": "qwen2.5vl:7b"},
}
RENDER_TIMEOUT = 30


def test_drawer_is_fixed_to_the_right_and_can_slide_in_and_out():
    assert "position: fixed" in _CSS
    assert "right: 0" in _CSS
    assert "transform: translateX(100%)" in _CSS
    assert ".ai-drawer-shell[data-open=\"true\"]" in _CSS
    assert "transform: translateX(0)" in _CSS


def test_drawer_uses_the_streamlit_v2_renderer_contract():
    assert "export default function(component)" in _JS
    assert "parentElement" in _JS
    assert "window.Streamlit" not in _JS
    assert "setComponentValue" not in _JS


def _state(**updates) -> dict:
    state = {
        "case_id": "case-1",
        "path": "C:/runtime/A_payment_ok_01.pdf",
        "model_profiles": PROFILES,
        "log": [],
    }
    state.update(updates)
    return state


def test_snapshot_follows_payment_model_steps_and_values():
    initial = snapshot_from_state(_state())
    assert initial.filename == "A_payment_ok_01.pdf"
    assert not initial.reader_done

    routed = snapshot_from_state(_state(
        filename="A_payment_ok_01.pdf",
        document_type=DocumentType.PAYMENT_CONFIRMATION.value,
        log=[{"node": "reader"}, {"node": "klassifikation"}],
    ), initial)
    assert routed.reader_done and routed.router_done
    assert not routed.extraction_done

    extracted = snapshot_from_state(_state(
        filename="A_payment_ok_01.pdf",
        document_type=DocumentType.PAYMENT_CONFIRMATION.value,
        number="RE-2026-4203",
        amount_eur=1341.96,
        log=[{"node": "reader"}, {"node": "klassifikation"},
             {"node": "extraktion_zahlung"}],
    ), routed)
    assert extracted.extraction_profile == "payment"
    assert dict(extracted.extracted) == {
        "number": "RE-2026-4203", "amount_eur": 1341.96
    }


def test_snapshot_keeps_missing_invoice_values_visible():
    snapshot = snapshot_from_state(_state(
        path="C:/runtime/B_invoice_ok_01.pdf",
        document_type=DocumentType.INCOMING_INVOICE.value,
        number=None,
        amount_eur=9570.0,
        supplier="Deutsche Telekom AG",
        line_items=["Mobilfunk"],
        cost_center_reference="KTR-TELCO",
        log=[{"node": "reader"}, {"node": "klassifikation"},
             {"node": "extraktion_rechnung"}],
    ))

    assert snapshot.extraction_profile == "invoice"
    assert dict(snapshot.extracted)["number"] is None
    assert dict(snapshot.extracted)["cost_center_reference"] == "KTR-TELCO"


def test_extracted_values_are_formatted_for_the_compact_table():
    snapshot = PanelSnapshot(
        case_id="case-1",
        filename="A_payment_ok_01.pdf",
        profiles=PROFILES,
        extracted=(("number", "RE-2026-4203"), ("amount_eur", 1341.96)),
    )

    assert _extracted_rows(snapshot) == [
        {"Feld": "Rechnungsnummer", "Erkannter Wert": "RE-2026-4203"},
        {"Feld": "Betrag auf dem Beleg", "Erkannter Wert": "1.341,96 €"},
    ]


def test_completed_drawer_data_contains_filename_model_and_extracted_fields():
    snapshot = PanelSnapshot(
        case_id="case-1",
        filename="A_payment_ok_01.pdf",
        profiles=PROFILES,
        reader_done=True,
        router_done=True,
        extraction_done=True,
        document_type=DocumentType.PAYMENT_CONFIRMATION.value,
        extraction_profile="payment",
        extracted=(("number", "RE-2026-4203"), ("amount_eur", 1341.96)),
    )
    data = _component_data(snapshot, force_open=True)

    assert data["document"] == "PDF: A_payment_ok_01.pdf"
    assert data["force_open"] is True
    assert data["open_revision"] == "case-1"
    assert data["status"] == {
        "label": "KI-Auswertung abgeschlossen",
        "state": "complete",
    }
    assert [step["label"] for step in data["steps"]] == [
        "PDF-Inhalt gelesen",
        "Belegart erkannt",
        "Daten extrahiert",
    ]
    assert data["steps"][1]["model"] == "ollama · qwen2.5vl:7b"
    assert data["steps"][2]["model"] == "ollama · qwen2.5vl:7b"
    assert data["rows"] == [
        {"field": "Rechnungsnummer", "value": "RE-2026-4203"},
        {"field": "Betrag auf dem Beleg", "value": "1.341,96 €"},
    ]


def test_begin_mounts_live_overview_outside_the_left_sidebar():
    source = f"""
import streamlit as st
import ui.cases.live_ai_panel as panel

def show_drawer_data(data, *, key):
    st.write(data["document"])
    st.write(f"force_open={{data['force_open']}}")

panel.ai_status_drawer = show_drawer_data

st.write("Upload page content")
panel.begin({{
    "case_id": "case-1",
    "path": "C:/runtime/A_payment_ok_01.pdf",
    "model_profiles": {PROFILES!r},
    "log": [],
}})
"""
    at = AppTest.from_string(source, default_timeout=RENDER_TIMEOUT).run()

    assert not at.exception
    assert not at.sidebar.markdown
    visible = " ".join(str(item.value) for item in at.markdown)
    assert "PDF: A_payment_ok_01.pdf" in visible
    assert "force_open=True" in visible


def test_live_updates_use_unique_component_keys_within_one_script_run():
    source = f"""
import streamlit as st
import ui.cases.live_ai_panel as panel

def keyed_drawer(data, *, key):
    st.button(data["status"]["label"], key=key)

panel.ai_status_drawer = keyed_drawer
panel.mount()

base = {{
    "case_id": "case-1",
    "path": "C:/runtime/A_payment_ok_01.pdf",
    "model_profiles": {PROFILES!r},
    "log": [],
}}
panel.begin(base)
panel.update({{**base, "log": [{{"node": "reader"}}]}})
panel.update({{
    **base,
    "document_type": "payment_confirmation",
    "log": [{{"node": "reader"}}, {{"node": "klassifikation"}}],
}})
panel.fail(RuntimeError("model stopped"))
"""
    at = AppTest.from_string(source, default_timeout=RENDER_TIMEOUT).run()

    assert not at.exception
    assert len(at.button) == 1
    assert at.button[0].key == "live_ai_status_drawer_4"
