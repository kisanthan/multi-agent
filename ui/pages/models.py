"""Page 'KI-Modelle': live, per-agent model configuration.

Deliberately its own page, separate from 'Architektur': that page *reads*
the risk-based default assignment (`agent_registry.py`) as an architectural
statement; this page lets an operator *override* it live, per agent, for
either a local (Ollama) or cloud (Anthropic) model -- without touching
`.env` or restarting. See `llm/model_overrides.py` for the precedence rule
(override always wins over the mode-based default) and
`llm/client.py::choose_model` for where it takes effect.
"""

from __future__ import annotations

import streamlit as st

from agent_registry import REGISTRY, ModelClass
from config import settings
from governance.audit import Decision, log_entry
from llm.client import choose_model
from llm.model_overrides import load_overrides, save_override, clear_override
from ui.shared import i18n, style
from ui.shared.context import current_user, connection

# Provider id -> catalog key. The id is what gets stored in the override
# file and written to the trail; the label is only what the operator reads.
PROVIDER_KEYS = {"ollama": "models.provider.ollama",
                 "anthropic": "models.provider.anthropic"}


def _provider_labels() -> dict[str, str]:
    return {p: i18n.t(key) for p, key in PROVIDER_KEYS.items()}


def _process_names(processes: tuple[str, ...]) -> str:
    import process_registry

    return " · ".join(i18n.process_text(process_registry.get_config(p), "name")
                      for p in processes)


def _agent_form(agent_id: str, cfg, overrides: dict) -> None:
    choice = choose_model(agent_id)
    override = overrides.get(agent_id)
    labels = _provider_labels()

    st.markdown(f"#### {i18n.agent_text(agent_id, 'name')}")
    st.caption(f"{_process_names(cfg.processes)} · "
               f"{i18n.t('models.model_class')}: "
               f"{i18n.enum_label('model_class', cfg.model_class.value)}")

    status = (i18n.t("models.overridden") if override is not None
              else i18n.t("models.default"))
    st.markdown(
        f'<div class="field-row"><b>{i18n.t("models.current")}:</b> '
        f'{choice.provider} / <code>{choice.model_id}</code> — {status}</div>',
        unsafe_allow_html=True,
    )

    with st.form(key=f"model_form_{agent_id}"):
        col1, col2 = st.columns([1, 2])
        with col1:
            provider = st.selectbox(
                i18n.t("models.provider"), list(labels),
                index=list(labels).index(choice.provider),
                format_func=lambda p: labels[p],
                key=f"provider_{agent_id}",
            )
        with col2:
            model_id = st.text_input(
                i18n.t("models.model_id"), value=choice.model_id,
                key=f"model_id_{agent_id}",
            )

        save_col, reset_col = st.columns([1, 1])
        saved = save_col.form_submit_button(i18n.t("models.save"))
        reset = reset_col.form_submit_button(
            i18n.t("models.reset"), disabled=override is None,
        )

    if saved:
        save_override(agent_id, provider, model_id)
        con = connection()
        try:
            log_entry(
                con, actor=current_user(), agent=agent_id,
                action="modell_konfiguration_geaendert",
                decision=Decision.INFO,
                reason=f"Modell manuell auf {provider}/{model_id} gesetzt.",
                payload={"anbieter": provider, "modell": model_id},
                outcome="ueberschrieben",
            )
            con.commit()
        finally:
            con.close()
        st.rerun()

    if reset:
        clear_override(agent_id)
        con = connection()
        try:
            log_entry(
                con, actor=current_user(), agent=agent_id,
                action="modell_konfiguration_geaendert",
                decision=Decision.INFO,
                reason="Modell auf Standard zurückgesetzt.",
                outcome="zurueckgesetzt",
            )
            con.commit()
        finally:
            con.close()
        st.rerun()


def render() -> None:
    style.css()
    st.title(i18n.t("models.title"))
    st.caption(i18n.t("models.caption"))
    st.markdown(
        f'<div class="field-row"><b>{i18n.t("models.global_mode")}:</b> '
        f'<code>{settings.model_mode.value}</code> — '
        f'{i18n.t("models.global_mode.text")}</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    overrides = load_overrides()
    for agent_id, cfg in REGISTRY.items():
        if cfg.model_class is ModelClass.NO_MODEL:
            continue
        _agent_form(agent_id, cfg, overrides)
        st.divider()
