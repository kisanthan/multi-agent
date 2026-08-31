"""Stylesheet and visual building blocks.

Knows Streamlit, but no business logic: what a status *means* lives in
`graph/cases.py`; here is only which color it gets. The words it draws are
already translated when they arrive -- this module never looks a text up
itself.
"""

from __future__ import annotations

import html

import streamlit as st

from graph.cases import Status
from ui.shared import i18n, theme
from ui.shared.formatting import field
from ui.cases.steps import Step, StepStatus

STATUS_BADGE_COLORS = {
    Status.RUNNING: "blue",
    Status.WAITING_FOR_APPROVAL: "orange",
    Status.COMPLETED: "green",
    Status.REJECTED: "gray",
    Status.DENIED: "red",
    Status.FAILED: "red",
}

SYMBOLS = {
    StepStatus.DONE: "✓",
    StepStatus.ACTIVE: "●",
    StepStatus.OPEN: "○",
    StepStatus.SKIPPED: "–",
    StepStatus.FAILED: "✕",
}

_LIGHT_THEME = """
  :root {
      color-scheme:light;
      --app-background:#ffffff;
      --app-surface:#f6f8fb;
      --app-surface-raised:#ffffff;
      --app-control:#ffffff;
      --app-control-hover:#eef2f7;
      --app-text:#1f2937;
      --app-muted:#667085;
      --app-border:#d6dbe3;
      --app-accent:#0b5cad;
      --app-success:#1a6b3c;
      --app-warning:#c47f00;
      --app-danger:#a3231f;
      --app-shadow:0 14px 40px rgba(15,23,42,0.12);
      --app-header:rgba(255,255,255,0.92);
      --app-link:#0b5cad;
      --app-code-background:#f2f4f7;
      --app-code-text:#1f2937;
      --app-nav-active-background:rgba(11,92,173,0.10);
      --app-nav-active-text:#084b8a;
      --app-modal-overlay:rgba(15,23,42,0.30);
      --app-data-color-scheme:light;
      --app-upload-icon-filter:none;
      --app-badge-running-text:#0b5cad;
      --app-badge-running-background:#e3f0fb;
      --app-badge-waiting-text:#8a5a00;
      --app-badge-waiting-background:#fdf3e0;
      --app-badge-completed-text:#1a6b3c;
      --app-badge-completed-background:#e6f4ec;
      --app-badge-neutral-text:#5a5a5a;
      --app-badge-neutral-background:#eeeeee;
      --app-badge-danger-text:#a3231f;
      --app-badge-danger-background:#fbeaea;
  }
"""

_DARK_THEME = """
  :root {
      color-scheme:dark;
      --app-background: #0e1117;
      --app-surface:#171d27;
      --app-surface-raised:#1c2430;
      --app-control:#202735;
      --app-control-hover:#2a3445;
      --app-text:#f1f5f9;
      --app-muted:#aab4c3;
      --app-border:#3b4658;
      --app-accent:#69b3ff;
      --app-success:#63d297;
      --app-warning:#ffc261;
      --app-danger:#ff8580;
      --app-shadow:0 18px 46px rgba(0,0,0,0.45);
      --app-header:rgba(14,17,23,0.92);
      --app-link:#79bbff;
      --app-code-background:#111722;
      --app-code-text:#d9e6f2;
      --app-nav-active-background:rgba(105,179,255,0.16);
      --app-nav-active-text:#9dceff;
      --app-modal-overlay:rgba(2,6,12,0.72);
      --app-data-color-scheme:dark;
      --app-upload-icon-filter:invert(0.85);
      --app-badge-running-text:#8ac7ff;
      --app-badge-running-background:#14314b;
      --app-badge-waiting-text:#ffd080;
      --app-badge-waiting-background:#3a2b12;
      --app-badge-completed-text:#7ee2aa;
      --app-badge-completed-background:#123527;
      --app-badge-neutral-text:#d1d7e0;
      --app-badge-neutral-background:#303744;
      --app-badge-danger-text:#ff9b97;
      --app-badge-danger-background:#431c22;
  }
"""

_SURFACE_THEME = """
  html, body, .stApp, [data-testid="stAppViewContainer"],
  [data-testid="stMain"], [data-testid="stMainBlockContainer"] {
      background-color:var(--app-background) !important;
      color:var(--app-text) !important;
  }
  [data-testid="stHeader"] {
      background-color:var(--app-header) !important;
      border-bottom:1px solid var(--app-border);
  }
  [data-testid="stToolbar"], [data-testid="stDecoration"] {
      color:var(--app-text) !important;
  }
  [data-testid="stSidebar"],
  [data-testid="stSidebarContent"],
  [data-testid="stSidebarHeader"] {
      background-color:var(--app-surface) !important;
      color:var(--app-text) !important;
  }
  [data-testid="stSidebar"] {border-right:1px solid var(--app-border);}
  [data-testid="stSidebarNavLink"],
  [data-testid="stSidebarNavLinkContainer"] {
      color:var(--app-text) !important;
      border-radius:8px;
  }
  [data-testid="stSidebarNavLink"]:hover,
  [data-testid="stSidebarNavLinkContainer"]:hover {
      background-color:var(--app-control-hover) !important;
  }
  [data-testid="stSidebarNavLink"][aria-current="page"],
  [data-testid="stSidebarNavLinkContainer"]:has([aria-current="page"]) {
      background-color:var(--app-nav-active-background) !important;
      color:var(--app-nav-active-text) !important;
  }
  [data-testid="stMarkdownContainer"] p,
  [data-testid="stMarkdownContainer"] li,
  [data-testid="stMarkdownContainer"] blockquote,
  .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5,
  .stApp label, [data-testid="stCaptionContainer"],
  [data-testid="stWidgetLabel"], [data-testid="stMetricLabel"],
  [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
      color:var(--app-text) !important;
  }
  [data-testid="stCaptionContainer"] {opacity:0.76;}
  .stApp a {color:var(--app-link);}
  .stApp hr {border-color:var(--app-border) !important;}
  [data-testid="stCodeBlock"], code, pre {
      background-color:var(--app-code-background) !important;
      color:var(--app-code-text) !important;
      border-color:var(--app-border) !important;
  }
  [data-baseweb="select"] > div,
  [data-baseweb="input"] > div,
  [data-baseweb="textarea"] > div,
  [data-baseweb="base-input"],
  [data-testid="stNumberInput"] input,
  [data-testid="stTextInput"] input,
  [data-testid="stTextArea"] textarea,
  [data-testid="stDateInput"] input,
  [data-testid="stSelectbox"] > div > div {
      background-color:var(--app-control) !important;
      border-color:var(--app-border) !important;
      color:var(--app-text) !important;
  }
  input::placeholder, textarea::placeholder {color:var(--app-muted) !important;}
  [data-baseweb="popover"], [data-testid="stPopover"],
  [role="listbox"], [role="menu"], [role="option"],
  [role="tooltip"], [data-baseweb="tooltip"],
  [data-baseweb="calendar"], [data-baseweb="calendar"] > div {
      background-color:var(--app-surface-raised) !important;
      color:var(--app-text) !important;
      border-color:var(--app-border) !important;
      box-shadow:var(--app-shadow);
  }
  [role="option"]:hover, [role="menuitem"]:hover {
      background-color:var(--app-control-hover) !important;
  }
  [data-testid="stBaseButton-secondary"],
  [data-testid="stBaseButton-tertiary"],
  [data-testid="stDownloadButton"] button {
      background-color:var(--app-control) !important;
      border-color:var(--app-border) !important;
      color:var(--app-text) !important;
  }
  [data-testid="stBaseButton-secondary"]:hover,
  [data-testid="stBaseButton-tertiary"]:hover,
  [data-testid="stDownloadButton"] button:hover {
      background-color:var(--app-control-hover) !important;
      border-color:var(--app-accent) !important;
  }
  [data-testid="stTabs"] {color:var(--app-text) !important;}
  button[data-baseweb="tab"] {
      color:var(--app-muted) !important;
      border-color:var(--app-border) !important;
  }
  button[data-baseweb="tab"][aria-selected="true"] {
      color:var(--app-text) !important;
  }
  [data-testid="stExpander"], [data-testid="stForm"],
  [data-testid="stVerticalBlockBorderWrapper"],
  [data-testid="stStatusWidget"] {
      background-color:var(--app-surface) !important;
      color:var(--app-text) !important;
      border-color:var(--app-border) !important;
  }
  [data-testid="stExpander"] details,
  [data-testid="stExpander"] summary {
      background-color:transparent !important;
      color:var(--app-text) !important;
  }
  [data-testid="stAlert"] {
      background-color:var(--app-surface-raised) !important;
      color:var(--app-text) !important;
      border:1px solid var(--app-border);
  }
  [data-testid="stDialog"], [role="dialog"],
  [data-baseweb="modal"] > div {
      background-color:var(--app-surface-raised) !important;
      color:var(--app-text) !important;
      border-color:var(--app-border) !important;
      box-shadow:var(--app-shadow);
  }
  [data-baseweb="modal"] {
      background-color:var(--app-modal-overlay) !important;
  }
  [data-testid="stMetric"] {
      background-color:var(--app-surface) !important;
      border:1px solid var(--app-border);
      border-radius:10px;
      padding:0.65rem 0.8rem;
  }
  [data-testid="stFileUploaderDropzone"] {
      background-color:var(--app-surface) !important;
      border-color:var(--app-border) !important;
      color:var(--app-text) !important;
  }
  [data-testid="stDataFrame"], [data-testid="stTable"] {
      background-color:var(--app-surface) !important;
      border:1px solid var(--app-border) !important;
      border-radius:9px;
      color-scheme:var(--app-data-color-scheme);
  }
  [data-testid="stToast"], [data-testid="stNotification"] {
      background-color:var(--app-surface-raised) !important;
      color:var(--app-text) !important;
      border-color:var(--app-border) !important;
  }
  .st-key-upload_documents [data-testid="stFileUploaderDropzone"]::before {
      filter:var(--app-upload-icon-filter);
  }
"""

_CSS = """
<style>
  __THEME__
  __SURFACE_THEME__
  .stepper {display:flex; flex-wrap:wrap; gap:6px; margin:14px 0 6px 0;}
  .step {flex:1 1 130px; min-width:130px; border-top:3px solid var(--app-border);
         padding:8px 10px 10px 0;}
  .step .sym {font-size:0.95rem; font-weight:700; margin-right:6px;}
  .step .title {font-size:0.82rem; line-height:1.25; display:inline;}
  .step .hint {display:block; font-size:0.72rem; opacity:0.7; margin-top:3px;}
  .step.done {border-top-color:var(--app-success);} .step.done .sym {color:var(--app-success);}
  .step.active {border-top-color:var(--app-warning);} .step.active .sym {color:var(--app-warning);}
  .step.failed {border-top-color:var(--app-danger);} .step.failed .sym {color:var(--app-danger);}
  .step.open {opacity:0.55;}
  .step.skipped {opacity:0.5; border-top-style:dashed;}
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
      border-color:var(--app-accent); background:rgba(11,92,173,0.06);
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
    theme_rules = _DARK_THEME if theme.is_dark() else _LIGHT_THEME
    stylesheet = (_CSS.replace("__THEME__", theme_rules)
                       .replace("__SURFACE_THEME__", _SURFACE_THEME)
                       .replace("__DROPZONE_HINT__", dropzone_hint))
    st.markdown(stylesheet,
                unsafe_allow_html=True)


def badge_color(status: Status) -> str:
    """Native Streamlit badge color for a case status."""
    return STATUS_BADGE_COLORS[status]


def dataframe(data, **kwargs):
    """Render a dataframe; colors come from Streamlit's light/dark theme."""
    return st.dataframe(data, **kwargs)


def stepper(steps: list[Step]) -> None:
    """Draws the process bar."""
    parts = ['<div class="stepper">']
    for s in steps:
        hint = (f'<span class="hint">{html.escape(str(s.hint))}</span>'
                if s.hint else "")
        parts.append(
            f'<div class="step {s.status.value}">'
            f'<span class="sym">{SYMBOLS[s.status]}</span>'
            f'<span class="title">{html.escape(str(s.title))}</span>{hint}</div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def fields(data: dict, keys) -> None:
    """Renders selected fields as labeled rows."""
    for k in keys:
        if k not in data or data[k] in (None, "", []):
            continue
        lbl, value = field(k, data[k])
        value_row(lbl, value)


def value_row(label: str, value) -> None:
    """Render a label/value pair without injecting dynamic HTML."""
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"**{label}:**")
        st.write(value)


def section_title(text: str) -> None:
    """Small heading to structure a page."""
    st.caption(text)


def status_card(person, *, upn: str | None = None) -> None:
    """Render account identity and rights with native Streamlit elements."""
    with st.container(border=True):
        if upn:
            st.caption(upn)
        st.badge(person.rights_short, color=(
            "green" if person.can_upload and person.can_confirm
            else "blue" if person.can_upload or person.can_confirm
            else "gray"
        ))
        st.caption(person.capabilities)
