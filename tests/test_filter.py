"""Tests of the list filters.

The same data source feeds the upload page, history, and both process
pages -- they only differ in the filter. Whatever is wrong here shows up
wrong on every page.
"""

from __future__ import annotations

from graph.cases import Status, CaseOverview
from ui.shared import filter as filters


def _row(**fields) -> CaseOverview:
    defaults = {
        "thread_id": "t1", "filename": "A_zahlung_ok_01.pdf",
        "actor": "m.keller@chg-meridian.com", "status": Status.COMPLETED,
        "process": "A", "started_at": "2026-07-30T12:00:00+00:00",
        "outcome": "verbucht", "approved_by": None,
    }
    return CaseOverview(**{**defaults, **fields})


ROWS = [
    _row(thread_id="a", status=Status.WAITING_FOR_APPROVAL, process="A",
         started_at="2026-07-30T12:00:00+00:00", outcome=None),
    _row(thread_id="b", status=Status.COMPLETED, process="B",
         filename="B_rechnung_ok_01.pdf", outcome="archiviert",
         started_at="2026-07-29T09:00:00+00:00"),
    _row(thread_id="c", status=Status.RUNNING, process=None,
         filename="unbekannt.pdf", outcome=None,
         started_at="2026-07-28T08:00:00+00:00"),
]


def test_empty_filter_returns_everything():
    assert len(filters.apply(ROWS, filters.Filter())) == 3


def test_empty_filter_recognizes_itself():
    assert filters.Filter().is_empty
    assert not filters.Filter(search="x").is_empty


def test_sorting_newest_first():
    result = filters.apply(ROWS, filters.Filter())
    assert [z.thread_id for z in result] == ["a", "b", "c"]


def test_search_matches_filename():
    matches = filters.apply(ROWS, filters.Filter(search="rechnung"))
    assert [z.thread_id for z in matches] == ["b"]


def test_search_matches_status_and_outcome():
    assert filters.apply(ROWS, filters.Filter(search="archiviert"))
    assert filters.apply(ROWS, filters.Filter(search="Wartet"))


def test_process_filter():
    matches = filters.apply(ROWS, filters.Filter(processes=frozenset({"B"})))
    assert [z.thread_id for z in matches] == ["b"]


def test_status_filter():
    matches = filters.apply(
        ROWS, filters.Filter(statuses=frozenset({Status.RUNNING})))
    assert [z.thread_id for z in matches] == ["c"]


def test_date_range_is_inclusive():
    matches = filters.apply(
        ROWS, filters.Filter(date_from="2026-07-29", date_to="2026-07-30"))
    assert {z.thread_id for z in matches} == {"a", "b"}


def test_case_without_start_time_is_never_filtered_out():
    """Runs from older states have no timestamp.

    Making them invisible would be worse than keeping them in the date
    filter -- the user would simply no longer find them.
    """
    old = _row(thread_id="alt", started_at="")
    matches = filters.apply([old], filters.Filter(date_from="2026-01-01", date_to="2026-01-02"))
    assert [z.thread_id for z in matches] == ["alt"]


def test_open_cases_show_approval_needed_first():
    open_ = filters.open_cases(ROWS)
    assert [z.thread_id for z in open_] == ["a", "c"]


def test_closed_cases_contain_no_open_ones():
    assert [z.thread_id for z in filters.closed_cases(ROWS)] == ["b"]


def test_for_process_restricts():
    assert [z.thread_id for z in filters.for_process(ROWS, "A")] == ["a"]


def test_counts():
    counts = filters.counts(ROWS)
    assert counts == {"pending": 1, "running": 1, "completed": 1,
                      "failed": 0}


def test_counts_count_denied_as_not_successful():
    """A denied AD check is not a success -- but also not an open case."""
    rows = [_row(status=Status.DENIED, outcome="zugriff_verweigert")]
    assert filters.counts(rows)["failed"] == 1
