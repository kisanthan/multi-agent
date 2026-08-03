"""Page 'Upload': submitting documents -- the application's main action.

Layout deliberately split in two: the upload area on top carries the page
visually, clearly separated below it are the most recently submitted
cases. The full list with filters lives on the history page, so the upload
does not get buried in a table here.

An upload is not yet a case: processing takes minutes and the user starts
it deliberately.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

import process_registry
from config import INTAKE_DIR, MANIFEST_PATH
from graph.cases import overview
from ui.shared import user, style
from ui.shared.formatting import enumerate_list, file_size
from ui.shared.context import current_user, graph, open_case, connection
from ui.upload import intake
from ui.cases import list as case_list
from ui.cases.run import start

RECENT_COUNT = 5


def _manifest() -> dict[str, dict]:
    """Expectations for the generated test documents, if present.

    Uploaded documents are not in the manifest -- the page must work just
    as well without a manifest entry.
    """
    if not MANIFEST_PATH.is_file():
        return {}
    return {d["filename"]: d
            for d in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))}


# ------------------------------------------------------------- Upload area

def _upload_section(person) -> None:
    if not person.can_upload:
        # No error bar: the account is not broken, it just has a different task.
        st.info(person.upload_hint)
        return

    # The label is collapsed: the drop area carries its own usage hint (see
    # ui/shared/style.py), a heading next to it would say the same thing
    # twice.
    #
    # The key is not just a state key: Streamlit attaches it as the CSS
    # class `st-key-upload_belege` to the container, and that is exactly
    # what styles the drop area. Wrapping a <div> around it via markdown
    # does not work -- Streamlit closes such blocks right away.
    files = st.file_uploader(
        "Belege hierher ziehen oder auswählen",
        type=["pdf"], accept_multiple_files=True, key="upload_belege",
        label_visibility="collapsed",
    )

    if not files:
        return

    # What Streamlit lists below the area are the chosen files with a
    # remove button. Here, next to them, is something else: the result of
    # the intake check -- i.e. why a file passes or not.
    st.markdown("**Eingangsprüfung**")
    con = connection()
    try:
        checked = [(d, intake.check(con, filename=d.name, data=d.getvalue()))
                   for d in files]
    finally:
        con.close()

    for file, result in checked:
        columns = st.columns([4, 2, 4])
        columns[0].markdown(f"`{file.name}`")
        columns[1].caption(file_size(len(file.getvalue())))
        if result.ok:
            columns[2].caption("✓ " + result.reason)
        else:
            columns[2].caption("✕ " + result.reason)

    acceptable = [d for d, p in checked if p.ok]
    button_label = ("Beleg übernehmen" if len(acceptable) == 1
                    else f"{len(acceptable)} Belege übernehmen")
    clicked = st.button(
        button_label if acceptable else "Übernehmen",
        type="primary", disabled=not acceptable, use_container_width=True,
    )

    if clicked:
        con = connection()
        try:
            for file, result in checked:
                if result.ok:
                    intake.store(con, filename=file.name,
                                data=file.getvalue(), actor=person.upn)
                else:
                    intake.log_rejection(
                        con, filename=file.name, actor=person.upn,
                        reason=result.reason)
        finally:
            con.close()
        st.success("Übernommen. Die Verarbeitung starten Sie unten mit "
                   "„Starten“ – sie dauert ein bis drei Minuten.")
        # Clear the widget, otherwise the same selection reappears after the rerun.
        st.session_state.pop("upload_belege", None)
        st.rerun()


# ---------------------------------------------------------------- Document list

def _document_list(upn: str, app) -> None:
    documents = sorted(INTAKE_DIR.glob("*.pdf")) if INTAKE_DIR.is_dir() else []
    if not documents:
        st.info("Noch keine Belege vorhanden. Laden Sie oben ein PDF hoch.")
        return

    manifest = _manifest()
    with st.expander(f"Bereitliegende Belege ({len(documents)})", expanded=not manifest):
        st.caption("„Starten“ legt einen neuen Vorgang an. Derselbe Beleg kann "
                   "mehrfach verarbeitet werden.")
        for document in documents:
            entry = manifest.get(document.name, {})
            head, button_col = st.columns([5, 1])
            with head:
                st.markdown(f"**{document.name}**")
                if entry:
                    kind = process_registry.get_config(entry["process"])
                    special_case = (" · Sonderfall zum Ausprobieren"
                                    if entry.get("incident") else "")
                    st.caption(f"{kind.document_kind}{special_case}")
                else:
                    st.caption(file_size(document.stat().st_size))
            start_clicked = button_col.button("Starten", key=f"start_{document.name}",
                                              use_container_width=True)

            if start_clicked:
                con = connection()
                try:
                    upload = intake.for_file(con, document.name)
                finally:
                    con.close()
                thread_id = start(app, path=document, actor=upn,
                                  upload_id=upload.upload_id if upload else None)
                open_case(thread_id)


# ------------------------------------------------------------------- Page

def render() -> None:
    # The document kinds appear in the drop area itself -- right where the
    # file is headed, not just in a line above it.
    kinds = enumerate_list(process_registry.document_kinds(), connector="oder")
    style.css(dropzone_hint=f"{kinds} hierher ziehen oder auswählen")

    st.title("Upload")
    st.caption("Welche Belegart vorliegt, erkennt das System selbst und legt "
               "den Vorgang entsprechend an.")

    upn = current_user()
    app, _ = graph()

    con = connection()
    try:
        person = user.load(con, upn)
    finally:
        con.close()

    with st.container(border=True):
        _upload_section(person)

    _document_list(upn, app)

    st.divider()
    st.markdown("### Zuletzt hochgeladen")
    from config import CHECKPOINT_PATH
    rows = overview(app, CHECKPOINT_PATH)

    if not rows:
        st.info("Noch keine Vorgänge. Starten Sie oben einen Beleg.")
        return

    case_list.as_cards(rows[:RECENT_COUNT], key="upload")
    if len(rows) > RECENT_COUNT:
        st.caption(f"{RECENT_COUNT} von {len(rows)} Vorgängen. "
                   "Die vollständige Liste steht unter „Alle Vorgänge“.")
