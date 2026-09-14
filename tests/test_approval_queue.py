"""Personal approval queue derived from checkpoints and governance policy."""

from __future__ import annotations

from types import SimpleNamespace

from graph.approval_queue import available_from_cases
from graph.cases import CaseOverview, Status

APPROVER = "pruefer@chg-meridian.com"
SUBMITTER = "einspeiser@chg-meridian.com"


def _case(thread_id: str, actor: str, status=Status.WAITING_FOR_APPROVAL):
    return CaseOverview(
        thread_id=thread_id,
        filename=f"{thread_id}.pdf",
        actor=actor,
        status=status,
        process="A",
        started_at="2026-09-01T10:00:00+00:00",
        outcome=None,
        approved_by=None,
    )


class FakeApp:
    def __init__(self, requests: dict[str, dict]):
        self.requests = requests

    def get_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        request = self.requests.get(thread_id)
        interrupts = () if request is None else (SimpleNamespace(value=request),)
        return SimpleNamespace(interrupts=interrupts)


def test_queue_contains_only_cases_this_person_may_approve(con):
    cases = [
        _case("other", SUBMITTER),
        _case("own", APPROVER),
        _case("running", SUBMITTER, Status.RUNNING),
        _case("unknown", SUBMITTER),
    ]
    app = FakeApp({
        "other": {"kind": "klaerfall"},
        "own": {"kind": "klaerfall"},
        "running": {"kind": "klaerfall"},
        "unknown": {"kind": "not-a-process"},
    })

    tasks = available_from_cases(app, con, actor=APPROVER, cases=cases)

    assert [task.case.thread_id for task in tasks] == ["other"]
    assert tasks[0].agent_id == "buchung"


def test_queue_is_empty_without_approval_permission(con):
    cases = [_case("waiting", APPROVER)]
    app = FakeApp({"waiting": {"kind": "klaerfall"}})

    tasks = available_from_cases(app, con, actor=SUBMITTER, cases=cases)

    assert tasks == []
