"""Stylesheet and visual building blocks.

Knows Streamlit, but no business logic: what a status *means* lives in
`graph/cases.py`; here is only which color it gets. The words it draws are
already translated when they arrive -- this module never looks a text up
itself.
"""

from __future__ import annotations

import streamlit as st

from graph.cases import Status
from ui.shared import i18n
from ui.shared.formatting import field
from ui.cases.steps import Step, StepStatus

# Foreground/background per status. The colors never carry the meaning
# alone -- every badge also contains the text (accessibility).
STATUS_COLORS = {
    Status.RUNNING: ("#0b5cad", "#e3f0fb"),
    Status.WAITING_FOR_APPROVAL: ("#8a5a00", "#fdf3e0"),
    Status.COMPLETED: ("#1a6b3c", "#e6f4ec"),
    Status.REJECTED: ("#5a5a5a", "#eeeeee"),
    Status.DENIED: ("#a3231f", "#fbeaea"),
    Status.FAILED: ("#a3231f", "#fbeaea"),
}

SYMBOLS = {
    StepStatus.DONE: "✓",
    StepStatus.ACTIVE: "●",
    StepStatus.OPEN: "○",
    StepStatus.SKIPPED: "–",
    StepStatus.FAILED: "✕",
}

_CSS = """
<style>
  .badge {display:inline-block; padding:2px 10px; border-radius:11px;
          font-size:0.78rem; font-weight:600; white-space:nowrap;}
  .stepper {display:flex; flex-wrap:wrap; gap:6px; margin:14px 0 6px 0;}
  .step {flex:1 1 130px; min-width:130px; border-top:3px solid #d6d6d6;
         padding:8px 10px 10px 0;}
  .step .sym {font-size:0.95rem; font-weight:700; margin-right:6px;}
  .step .title {font-size:0.82rem; line-height:1.25; display:inline;}
  .step .hint {display:block; font-size:0.72rem; opacity:0.7; margin-top:3px;}
  .step.done {border-top-color:#1a6b3c;} .step.done .sym {color:#1a6b3c;}
  .step.active {border-top-color:#c47f00;} .step.active .sym {color:#c47f00;}
  .step.failed {border-top-color:#a3231f;} .step.failed .sym {color:#a3231f;}
  .step.open {opacity:0.55;}
  .step.skipped {opacity:0.5; border-top-style:dashed;}
  .field-row {font-size:0.88rem; margin:2px 0;}
  .field-row b {font-weight:600;}
  .card {border:1px solid rgba(128,128,128,0.25); border-radius:9px;
         padding:14px 16px; margin-bottom:10px;}

  /* The upload is the main point of the start page and must look like it.
     Streamlit's dropzone is by default a narrow row with a button; here it
     becomes a large, centered drop area.

     Only the documented `data-testid`s are targeted -- the Emotion classes
     next to them change with every Streamlit version. */
  .st-key-upload_documents [data-testid="stFileUploaderDropzone"] {
      display:flex; flex-direction:column; align-items:center;
      justify-content:center; gap:0.55rem; text-align:center;
      min-height:210px; padding:30px 20px;
      border:2px dashed rgba(120,130,145,0.45); border-radius:14px;
      background:rgba(120,130,145,0.03);
      transition:border-color .15s ease, background .15s ease;
  }
  .st-key-upload_documents [data-testid="stFileUploaderDropzone"]:hover,
  .st-key-upload_documents [data-testid="stFileUploaderDropzone"]:focus-within {
      border-color:#0b5cad; background:rgba(11,92,173,0.06);
  }

  /* Dropzone icon. Purely decorative -- the usage hints are text below it,
     so the area stays understandable even without the image. */
  .st-key-upload_documents [data-testid="stFileUploaderDropzone"]::before {
      content:""; order:1; width:30px; height:30px; opacity:0.75;
      background-repeat:no-repeat; background-position:center;
      background-size:contain;
      background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23475569' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 16V4'/%3E%3Cpath d='m7 9 5-5 5 5'/%3E%3Cpath d='M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2'/%3E%3C/svg%3E");
  }

  .st-key-upload_documents [data-testid="stFileUploaderDropzoneInstructions"] {
      order:2; display:flex; flex-direction:column; gap:0.15rem;
      color:inherit;
  }
  .st-key-upload_documents
  [data-testid="stFileUploaderDropzoneInstructions"]::before {
      content:"__DROPZONE_HINT__";
      font-size:1rem; font-weight:600;
  }
  .st-key-upload_documents
  [data-testid="stFileUploaderDropzoneInstructions"] span {
      font-size:0.8rem; opacity:0.7;
  }

  /* The button sits inside a <span> -- that is the flex element, not the
     button itself. An `order` on the button would have no effect. */
  .st-key-upload_documents [data-testid="stFileUploaderDropzone"] > span {
      order:3; margin-top:0.4rem;
  }
  /* The button by default carries the same arrow icon as the area above it
     -- once is enough. */
  .st-key-upload_documents [data-testid="stFileUploaderDropzone"] button
  [data-testid="stIconMaterial"] {
      display:none;
  }
  .section-title {font-size:0.78rem; font-weight:700; letter-spacing:0.09em;
                  text-transform:uppercase; opacity:0.6; margin:6px 0 2px 0;}

  /* The sign-in area as a set-off card: who is currently signed in and what
     that account may do governs every button in the app -- it must not
     disappear as a pale line. */
  /* Status card as ONE single, raw-rendered HTML block (a single
     st.markdown() call) instead of a Streamlit container with multiple
     children. Reason: Streamlit measures the height of multi-element
     containers via JS/ResizeObserver and fixes it -- also with
     `!important`, via a class that could not be reliably overridden via
     CSS. A multi-line sentence in small type was sized too tightly there
     and overflowed the card's edge. A single <div>, natively sized by the
     browser, does not have this problem at all: it is always exactly as
     tall as its content. */
  .status-card {
      border:1px solid rgba(120,130,145,0.30); border-radius:12px;
      padding:11px 13px; margin:2px 0 10px 0;
      background:rgba(120,130,145,0.06);
  }
  .account-upn {font-size:0.74rem; opacity:0.65; margin-bottom:8px;
                word-break:break-all;}
  .rights {display:inline-flex; align-items:center; gap:6px;
           padding:4px 11px; border-radius:11px;
           font-size:0.79rem; font-weight:600;}
  .rights .dot {width:7px; height:7px; border-radius:50%;
                background:currentColor; flex:none;}
  .rights-sentence {font-size:0.76rem; opacity:0.75; line-height:1.4;
                    margin:7px 0 0 0;}
</style>
"""


def css(dropzone_hint: str | None = None) -> None:
    """Injects the stylesheet. Call once per page render.

    The dropzone's usage hint sits in a CSS rule -- Streamlit does not let
    the dropzone text be set any other way. It is therefore passed in from
    outside instead of this module knowing the document kinds: this module
    designs, it knows nothing about processes.
    """
    if dropzone_hint is None:
        dropzone_hint = i18n.t("upload.dropzone.default")
    st.markdown(_CSS.replace("__DROPZONE_HINT__", dropzone_hint),
                unsafe_allow_html=True)


def badge(status: Status) -> str:
    """Status chip as HTML (for embedding in markdown blocks)."""
    color, background = STATUS_COLORS[status]
    return (f'<span class="badge" style="color:{color}; background:{background};">'
            f'{i18n.status_label(status)}</span>')


def stepper(steps: list[Step]) -> None:
    """Draws the process bar."""
    parts = ['<div class="stepper">']
    for s in steps:
        hint = f'<span class="hint">{s.hint}</span>' if s.hint else ""
        parts.append(
            f'<div class="step {s.status.value}">'
            f'<span class="sym">{SYMBOLS[s.status]}</span>'
            f'<span class="title">{s.title}</span>{hint}</div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def fields(data: dict, keys) -> None:
    """Renders selected fields as labeled rows."""
    for k in keys:
        if k not in data or data[k] in (None, "", []):
            continue
        lbl, value = field(k, data[k])
        st.markdown(f'<div class="field-row"><b>{lbl}:</b> {value}</div>',
                    unsafe_allow_html=True)


def section_title(text: str) -> None:
    """Small heading to structure a page."""
    st.markdown(f'<div class="section-title">{text}</div>', unsafe_allow_html=True)


def _rights_colors(person) -> tuple[str, str]:
    """Foreground/background of the rights badge.

    Green means can act, gray means can only watch -- the same logic as for
    case statuses. The text always sits next to it; color alone never
    carries the meaning.
    """
    if person.can_upload and person.can_confirm:
        return "#1a6b3c", "#e6f4ec"
    if person.can_upload or person.can_confirm:
        return "#0b5cad", "#e3f0fb"
    return "#5a5a5a", "#e8e8e8"


def rights_badge(person) -> str:
    """Status badge for an account's rights, usable standalone."""
    color, background = _rights_colors(person)
    return (f'<span class="rights" style="color:{color}; background:{background};">'
            f'<span class="dot"></span>{person.rights_short}</span>')


def status_card_html(person, *, upn: str | None = None) -> str:
    """Builds the sign-in card as a single HTML block.

    Kept as a pure function separate from Streamlit, so the cohesion of
    frame, badge, and sentence can be tested without a running app.
    """
    color, background = _rights_colors(person)
    upn_row = (f'<div class="account-upn">{upn}</div>' if upn else "")
    return (
        f'<div class="status-card">'
        f'{upn_row}'
        f'<span class="rights" style="color:{color}; background:{background};">'
        f'<span class="dot"></span>{person.rights_short}</span>'
        f'<div class="rights-sentence">{person.capabilities}</div>'
        f'</div>'
    )


def status_card(person, *, upn: str | None = None) -> None:
    """The sign-in card: account, rights badge, and the full sentence.

    Deliberately ONE single `st.markdown()` call instead of several
    elements in a Streamlit container -- only that way is it guaranteed
    that the frame fits exactly around the actual content, even when the
    sentence wraps to two lines. A Streamlit container measures its own
    height via JS and fixes it; with multi-line text that missed the mark.
    """
    st.markdown(status_card_html(person, upn=upn), unsafe_allow_html=True)
