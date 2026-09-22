"""Starting and resuming cases -- with visible progress.

Blocking, and deliberately so: a run with a local model takes one to three
minutes, and during that time it should be visible what is happening. A
silent spinner would look like a crash. The operational limit is documented
in docs/limitations.md (L8).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from config import settings
from ui.cases import live_ai_panel
from ui.shared import i18n


def _stream_run(app, thread: dict, payload, title: str, *, show_ai: bool = False) -> bool:
    """Runs the graph and shows every node as soon as it finishes.

    Returns whether the run ended without an exception. An error is
    displayed instead of raised: the case stays in the checkpoint and is
    then visible in the list -- a page crash would only make it
    unfindable.
    """
    shown = 0
    if show_ai and isinstance(payload, dict):
        live_ai_panel.begin(payload)
    with st.status(title, expanded=True) as box:
        try:
            from governance.identity import session
            with session(st.session_state.get("auth_token", "")):
                for state in app.stream(payload, thread, stream_mode="values"):
                    if show_ai and isinstance(state, dict):
                        live_ai_panel.update(state)
                    log = state.get("log", []) if isinstance(state, dict) else []
                    for entry in log[shown:]:
                        st.write(f"**{entry['node']}** — {entry['text']}")
                    shown = max(shown, len(log))
        except Exception as e:  # noqa: BLE001 - the user should see the reason
            if show_ai:
                live_ai_panel.fail(e)
            box.update(label=i18n.t("run.aborted", error=e), state="error")
            st.exception(e)
            return False
        box.update(label=i18n.t("run.finished"), state="complete")
    return True


def start(app, *, path: Path | str, actor: str, upload_id: str | None = None) -> str:
    """Creates a case and runs it up to the first stop."""
    filename = Path(path).name
    thread_id = f"{filename}-{uuid.uuid4().hex[:8]}"

    _stream_run(app, {"configurable": {"thread_id": thread_id}}, {
        "path": str(path),
        "actor": actor,
        "upload_id": upload_id,
        "case_id": thread_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "configuration_revision": settings.configuration_revision,
        "model_profiles": settings.profile_snapshot(),
        "log": [],
    }, i18n.t("run.running", filename=filename), show_ai=True)

    return thread_id


def resume(app, *, thread_id: str, response: dict) -> None:
    """Resumes a waiting case after the decision."""
    from langgraph.types import Command

    _stream_run(app, {"configurable": {"thread_id": thread_id}},
               Command(resume=response), i18n.t("run.deciding"))
