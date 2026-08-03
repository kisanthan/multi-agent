"""Page 'Vorgang': the detail view of a single case.

Its own route with `?id=…` instead of session state: a case is thereby
linkable and survives a page reload. No entry in the sidebar -- one arrives
here from a list, not from the navigation.
"""

from __future__ import annotations

import streamlit as st

from ui.shared import style
from ui.shared.context import current_user, graph
from ui.cases import detail


def render() -> None:
    style.css()
    thread_id = st.query_params.get("id")

    if not thread_id:
        st.title("Vorgang")
        st.info("Kein Vorgang ausgewählt. Öffnen Sie einen Vorgang aus "
                "einer der Listen.")
        return

    app, _ = graph()
    st.title(thread_id.rsplit("-", 1)[0])
    st.caption("Vorgang", help=f"Kennung: {thread_id}")

    detail.render(app, thread_id, upn=current_user(), with_title=False)
