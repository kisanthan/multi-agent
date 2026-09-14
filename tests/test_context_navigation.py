"""Regression tests for navigation that carries a selected case."""

from __future__ import annotations

from ui.shared import context


def _capture_switch(monkeypatch):
    target_page = object()
    calls = []
    monkeypatch.setattr(context, "get_page", lambda _name: target_page)
    monkeypatch.setattr(
        context.st,
        "switch_page",
        lambda page, **kwargs: calls.append((page, kwargs)),
    )
    return target_page, calls


def test_open_case_carries_id_into_target_page(monkeypatch):
    target_page, calls = _capture_switch(monkeypatch)

    context.open_case("case-123")

    assert calls == [(target_page, {"query_params": {"id": "case-123"}})]


def test_show_audit_carries_case_filter_into_target_page(monkeypatch):
    target_page, calls = _capture_switch(monkeypatch)

    context.show_audit_for("case-123")

    assert calls == [(target_page, {"query_params": {"case": "case-123"}})]
