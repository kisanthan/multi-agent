"""The interface's language -- German and English.

Two rules govern what is translated here, and they are the reason this is
not simply a German dictionary mirrored into English:

- **The interface is translated.** Headings, buttons, labels, column names,
  explanations -- everything the system says *about* a case. It has no home
  outside the interface, so the catalogs under `ui/locales/` are that home.
- **The record is not.** What the run log and the audit trail wrote down
  stays in the wording it was written in. Rephrasing a recorded reason for
  display would mean rewriting the evidence, and the trail is precisely
  what makes the system's steps reconstructible. `tests/test_ui_language.py`
  already draws that same line for domain jargon; this module keeps to it.

Text that has a canonical home *outside* the interface -- process names in
`process_registry.py`, agent names in `agent_registry.py`, status labels in
`graph/cases.py` -- is deliberately **not** copied into `de.json`. It is
passed in as `default=` and only the catalogs of other languages carry a
translation. German therefore lives in exactly one place per string, and
`tests/test_i18n.py` pins that English covers all of it.

German is both the default language and the fallback for a missing English
key: an untranslated string stays readable instead of turning up blank.

Streamlit is imported lazily so this module stays usable from pure modules
(`ui/shared/filter.py`, `ui/shared/formatting.py`) and from tests without a
running app.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

LOCALES_DIR = Path(__file__).parent.parent / "locales"

DEFAULT_LANGUAGE = "de"

# Code -> the language's own name. Endonyms on purpose: someone looking for
# the English interface looks for "English", not for "Englisch".
LANGUAGES: dict[str, str] = {"de": "Deutsch", "en": "English"}

SESSION_LANGUAGE = "ui_language"

# Used only where there is no Streamlit session: tests, `demo.py`, a module
# imported outside a script run. Inside the app the session value always
# wins, so one browser session's choice can never leak into another's.
_fallback_language = DEFAULT_LANGUAGE


@functools.lru_cache(maxsize=None)
def catalog(code: str) -> dict[str, str]:
    """The flat key -> text table of one language.

    Flat dotted keys rather than nested objects: it makes the coverage
    check in `tests/test_i18n.py` a set comparison instead of a tree walk.
    """
    path = LOCALES_DIR / f"{code}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _in_script_run() -> bool:
    """Is a Streamlit script actually running right now?

    Asked directly rather than inferred from an exception, because Streamlit
    does not raise outside a script run: `st.session_state` still hands back
    a state object there, but a throwaway one that is discarded again after
    every call. A write to it would look like it worked and change nothing --
    which is exactly what a test or `demo.py` would run into.
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        try:
            from streamlit.runtime.scriptrunner_utils.script_run_context import (
                get_script_run_ctx,
            )
        except ImportError:
            return False
    # `suppress_warning`: without it Streamlit logs "missing ScriptRunContext"
    # on *every* call, and this one is called once per translated string --
    # a `demo.py` run or a test would drown in it. Asking is not a mistake
    # here; outside a script run is a normal place for this code to be.
    try:
        try:
            ctx = get_script_run_ctx(suppress_warning=True)
        except TypeError:  # older Streamlit without the keyword
            ctx = get_script_run_ctx()
        return ctx is not None
    except Exception:      # noqa: BLE001 - unknown version, assume not
        return False


def _session():
    """Streamlit's session state, or `None` outside a script run."""
    if not _in_script_run():
        return None
    import streamlit as st

    return st.session_state


def language() -> str:
    """The active language code."""
    session = _session()
    if session is not None:
        code = session.get(SESSION_LANGUAGE)
        if code in LANGUAGES:
            return code
    return _fallback_language


def set_language(code: str) -> None:
    """Switches the language. Unknown code = programming error."""
    global _fallback_language

    if code not in LANGUAGES:
        raise ValueError(f"Unknown language {code!r}. Known: {sorted(LANGUAGES)}")

    session = _session()
    if session is not None:
        session[SESSION_LANGUAGE] = code
        return
    _fallback_language = code


def t(key: str, /, default: str | None = None, **params) -> str:
    """The text behind a key, in the active language.

    Resolution order: active language -> German -> `default` -> the key
    itself. The key as a last resort is deliberate: a missing entry then
    shows up on screen as `list.open` instead of as an empty button.

    `params` are substituted with `str.format`. Without params no
    formatting happens at all, so a text containing braces (CSS, JSON
    samples) passes through untouched.
    """
    text = catalog(language()).get(key)
    if text is None and language() != DEFAULT_LANGUAGE:
        text = catalog(DEFAULT_LANGUAGE).get(key)
    if text is None:
        text = default if default is not None else key
    return text.format(**params) if params else text


# --- Text with a canonical home outside the interface -----------------------
# These read the German original from its own module and look up only the
# translation. See the module docstring: German is never duplicated into a
# catalog.

def process_text(config, attribute: str) -> str:
    """A process's display text (`name`, `document_kind`, `description`, …)."""
    return t(f"process.{config.key}.{attribute}",
             default=getattr(config, attribute))


def document_kinds() -> list[str]:
    """The document kinds the system processes, in the active language."""
    import process_registry

    return [process_text(p, "document_kind")
            for p in process_registry.all_processes()]


def document_kinds_plural() -> list[str]:
    """Plural forms of the document kinds.

    German builds them by rule (`ui/shared/formatting.pluralize`); English
    is irregular often enough that the catalog states the form outright.
    """
    import process_registry
    from ui.shared.formatting import pluralize

    return [t(f"process.{p.key}.document_kind_plural",
              default=pluralize(p.document_kind))
            for p in process_registry.all_processes()]


def step_title(node: str) -> str:
    """Business label of a flow step, in the active language."""
    import process_registry

    return t(f"step.{node}.title", default=process_registry.step_title(node))


def status_label(status) -> str:
    """Business status of a case, in the active language."""
    return t(f"status.{status.value}", default=status.label)


def agent_text(agent_id: str, attribute: str) -> str:
    """An agent's `name` or `description` from `agent_registry.py`."""
    from agent_registry import REGISTRY

    return t(f"agent.{agent_id}.{attribute}",
             default=getattr(REGISTRY[agent_id], attribute))


def enum_label(group: str, value: str) -> str:
    """A registry enum's display value (agent type, oversight, model class).

    These carry the thesis's own vocabulary and appear only on the
    architecture page, which explains them. Translated all the same -- an
    English reader of that page should not meet "vision-faehig".
    """
    return t(f"enum.{group}.{value}", default=value)


# --- Language picker --------------------------------------------------------

def picker(label_key: str = "app.language") -> None:
    """Language setting. Writes straight into the session, so the rerun that
    follows the selection already renders in the new language."""
    import streamlit as st

    codes = list(LANGUAGES)
    current = language()
    st.selectbox(
        t(label_key), codes, index=codes.index(current),
        format_func=lambda c: LANGUAGES[c], key=SESSION_LANGUAGE,
    )
