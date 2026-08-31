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

import streamlit as st

import process_registry
from config import INTAKE_DIR, MANIFEST_PATH
from graph.cases import overview
from ui.shared import i18n, user, style
from ui.shared.formatting import enumerate_list, file_size
from ui.shared.context import current_user, graph, open_case, connection
from ui.intake import intake
from ui.cases import list as case_list
from ui.cases.run import start

RECENT_COUNT = 5

# The widget key is also the CSS class Streamlit attaches to the container
# (`st-key-upload_documents`), and that is what styles the drop area -- see
# ui/shared/style.py. Renaming it here means renaming it there too.
UPLOADER_KEY = "upload_documents"


def _manifest() -> dict[str, dict]:
    """Expectations for the generated test documents, if present.

    Uploaded documents are not in the manifest -- the page must work just
    as well without a manifest entry.
    """
    if not MANIFEST_PATH.is_file():
        return {}
    return {d["filename"]: d
            for d in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))}


def _check_text(result) -> str:
    """The intake verdict, in the reader's language.

    Falls back to the recorded German reason for a result that predates the
    codes (see `ui/intake/intake.py::CheckResult`).
    """
    if not result.code:
        return result.reason
    return i18n.t(f"intake.{result.code}", default=result.reason,
                  **(result.params or {}))


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
    # class `st-key-upload_documents` to the container, and that is exactly
    # what styles the drop area. Wrapping a <div> around it via markdown
    # does not work -- Streamlit closes such blocks right away.
    files = st.file_uploader(
        i18n.t("upload.uploader_label"),
        type=["pdf"], accept_multiple_files=True, key=UPLOADER_KEY,
        label_visibility="collapsed",
    )

    if not files:
        return

    # What Streamlit lists below the area are the chosen files with a
    # remove button. Here, next to them, is something else: the result of
    # the intake check -- i.e. why a file passes or not.
    st.markdown(f"**{i18n.t('upload.intake_check')}**")
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
        columns[2].caption(("✓ " if result.ok else "✕ ") + _check_text(result))

    acceptable = [d for d, p in checked if p.ok]
    button_label = (i18n.t("upload.accept_one") if len(acceptable) == 1
                    else i18n.t("upload.accept_many", count=len(acceptable)))
    clicked = st.button(
        button_label if acceptable else i18n.t("upload.accept"),
        type="primary", disabled=not acceptable, width="stretch",
    )

    if clicked:
        con = connection()
        try:
            for file, result in checked:
                if result.ok:
                    intake.store(con, filename=file.name,
                                data=file.getvalue(), actor=person.upn)
                else:
                    # The recorded reason, not the displayed one: the trail
                    # keeps one wording regardless of who was looking.
                    intake.log_rejection(
                        con, filename=file.name, actor=person.upn,
                        reason=result.reason)
        finally:
            con.close()
        st.success(i18n.t("upload.accepted"))
        # Clear the widget, otherwise the same selection reappears after the rerun.
        st.session_state.pop(UPLOADER_KEY, None)
        st.rerun()


# ---------------------------------------------------------------- Document list

def _document_list(upn: str, app) -> None:
    documents = sorted(INTAKE_DIR.glob("*.pdf")) if INTAKE_DIR.is_dir() else []
    if not documents:
        st.info(i18n.t("upload.no_documents"))
        return

    manifest = _manifest()
    with st.expander(i18n.t("upload.ready", count=len(documents)),
                     expanded=not manifest):
        st.caption(i18n.t("upload.ready_caption"))
        for document in documents:
            entry = manifest.get(document.name, {})
            head, button_col = st.columns([5, 1])
            with head:
                st.markdown(f"**{document.name}**")
                if entry:
                    kind = process_registry.get_config(entry["process"])
                    special_case = (i18n.t("upload.special_case")
                                    if entry.get("incident") else "")
                    st.caption(f"{i18n.process_text(kind, 'document_kind')}"
                               f"{special_case}")
                else:
                    st.caption(file_size(document.stat().st_size))
            start_clicked = button_col.button(
                i18n.t("upload.start"), key=f"start_{document.name}",
                width="stretch")

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
    kinds = enumerate_list(i18n.document_kinds(), connector=i18n.t("word.or"))
    style.css(dropzone_hint=i18n.t("upload.dropzone.hint", kinds=kinds))

    st.title(i18n.t("upload.title"))
    st.caption(i18n.t("upload.caption"))

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
    st.markdown(f"### {i18n.t('upload.recent')}")
    from config import CHECKPOINT_PATH
    rows = overview(app, CHECKPOINT_PATH)

    if not rows:
        st.info(i18n.t("upload.no_cases"))
        return

    case_list.as_cards(rows[:RECENT_COUNT], key="upload")
    if len(rows) > RECENT_COUNT:
        st.caption(i18n.t("upload.recent_count",
                          shown=RECENT_COUNT, total=len(rows)))
