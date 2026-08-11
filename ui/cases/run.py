"""Starting and resuming cases -- with visible progress.

Blocking, and deliberately so: a run with a local model takes one to three
minutes, and during that time it should be visible what is happening. A
silent spinner would look like a crash. The operational limit is documented
in docs/grenzen.md (L8).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st


def _stream_run(app, thread: dict, payload, title: str) -> bool:
    """Runs the graph and shows every node as soon as it finishes.

    Returns whether the run ended without an exception. An error is
    displayed instead of raised: the case stays in the checkpoint and is
    then visible in the list -- a page crash would only make it
    unfindable.
    """
    shown = 0
    with st.status(title, expanded=True) as box:
        try:
            for state in app.stream(payload, thread, stream_mode="values"):
                log = state.get("log", []) if isinstance(state, dict) else []
                for entry in log[shown:]:
                    st.write(f"**{entry['node']}** — {entry['text']}")
                shown = max(shown, len(log))
        except Exception as e:  # noqa: BLE001 - the user should see the reason
            box.update(label=f"Vorgang abgebrochen: {e}", state="error")
            st.exception(e)
            return False
        box.update(label="Verarbeitung beendet", state="complete")
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
        "log": [],
    }, f"Vorgang läuft: {filename}")

    return thread_id


def resume(app, *, thread_id: str, response: dict) -> None:
    """Resumes a waiting case after the decision."""
    from langgraph.types import Command

    _stream_run(app, {"configurable": {"thread_id": thread_id}},
               Command(resume=response), "Entscheidung wird verarbeitet")
