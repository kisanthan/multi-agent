"""Per-process fragments of the case-detail view.

`ui/cases/detail.py` renders the shared shell (stepper, header, decision
form, document preview); this package holds what differs by process: the
approval form's extra input, the outcome texts, and the target-system
metric. One module per process (`payment_confirmation.py`,
`incoming_invoice.py`), each exporting the same three names.

Deliberately NOT an empty `__init__.py` like every other package in this
project -- here the registry itself is the content, so a separate
`agent_registry.py`-style module alongside two modules would add a file for nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import process_registry
from graph.effects import Effect
from ui.shared import i18n
from ui.cases.process_views import incoming_invoice, payment_confirmation

# Outcomes with no single owning process. `zugriff_verweigert` always has
# `process=None` -- the reader denies access before classification (and
# therefore process assignment) ever runs. `verworfen` can happen at either
# process's approval point.
SHARED_RESULT_TEXTS = {
    "verworfen": "Der Vorgang wurde abgelehnt. Es wurde nichts gebucht und "
                 "nichts abgelegt.",
    "zugriff_verweigert": "Der Beleg wurde nicht geöffnet: das Konto ist dazu "
                          "nicht berechtigt.",
}


@dataclass(frozen=True)
class ProcessView:
    key: str
    result_texts: Mapping[str, str]
    approval_inputs: Callable[..., dict]
    effect_metric: Callable[[Effect], tuple[str, str] | None]


VIEWS: dict[str, ProcessView] = {
    "A": ProcessView("A", payment_confirmation.RESULT_TEXTS,
                     payment_confirmation.approval_inputs,
                     payment_confirmation.effect_metric),
    "B": ProcessView("B", incoming_invoice.RESULT_TEXTS,
                     incoming_invoice.approval_inputs,
                     incoming_invoice.effect_metric),
}


def all_views() -> list[ProcessView]:
    """All views in stable order (mirrors process_registry.all_processes())."""
    return [VIEWS[k] for k in sorted(VIEWS)]


def for_process(key: str | None) -> ProcessView | None:
    return VIEWS.get(key) if key else None


def for_interrupt(kind: str | None) -> ProcessView | None:
    config = process_registry.for_interrupt(kind)
    return VIEWS.get(config.key) if config else None


def result_text(outcome: str, process: str | None) -> str:
    """Human-readable outcome text.

    Merges the shared texts with either one process's own (when the
    process is known) or all processes' (when it is not). This reproduces
    the pre-split flat lookup exactly: an outcome key exists in at most one
    process's `RESULT_TEXTS`, so merging "all of them" when the process is
    unknown can never pick the wrong one.

    `outcome` is the recorded value (`verbucht`, `archiviert`) and stays
    what it is; only the sentence built around it is translated. The German
    sentences above are the fallback, so an outcome a catalog has not
    caught up with still reads as a sentence.
    """
    texts = dict(SHARED_RESULT_TEXTS)
    views = [for_process(process)] if process else all_views()
    for view in views:
        if view:
            texts.update(view.result_texts)

    if outcome in texts:
        return i18n.t(f"result.{outcome}", default=texts[outcome])
    return i18n.t("result.unknown",
                  outcome=outcome or i18n.t("result.unknown.value"))
