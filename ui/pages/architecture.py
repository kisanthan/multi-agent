"""Page 'Architektur': roles, autonomy levels, oversight.

This page *reads* the registries, it does not describe them. That way the
thesis's central claim -- role- and risk-based configuration that is
effective, not merely documented -- is directly readable in the UI, without
creating a second place to maintain.

**Domain jargon belongs here on purpose.** Every working view is
deliberately free of "Prozess A", "Human-in-the-loop", or security groups --
a case worker does not need them. Whoever wants to assess the architecture
needs exactly them, and finds them in this one place. That holds in either
language: the English catalog translates the vocabulary, it does not drop
it.
"""

from __future__ import annotations

import streamlit as st

import process_registry
from agent_registry import REGISTRY, OversightMode
from config import settings
from governance import ad
from ui.shared import i18n, style
from ui.cases.steps import steps_for


def render() -> None:
    style.css()
    st.title(i18n.t("architecture.title"))
    st.caption(i18n.t("architecture.caption"))

    for config in process_registry.all_processes():
        st.markdown("### " + i18n.t("architecture.process_heading",
                                    key=config.key,
                                    name=i18n.process_text(config, "name")))
        st.write(i18n.process_text(config, "description"))
        # All steps shown neutrally: this explains the flow, not a case.
        style.stepper(steps_for(config.key, []))

        for step in config.steps:
            if not step.agent_id:
                continue
            cfg = REGISTRY[step.agent_id]
            marker = "🔒 " if cfg.oversight is OversightMode.HUMAN_IN_THE_LOOP else ""
            level = (i18n.t("architecture.level", level=cfg.autonomy_level.value)
                     if cfg.autonomy_level else i18n.t("architecture.no_level"))
            st.markdown(
                f'<div class="field-row">{marker}'
                f'<b>{i18n.step_title(step.node)}</b> — '
                f'{i18n.agent_text(step.agent_id, "name")} · {level} · '
                f'{i18n.enum_label("oversight", cfg.oversight.value)} · '
                f'{i18n.enum_label("model_class", cfg.model_class.value)}</div>',
                unsafe_allow_html=True,
            )
        st.divider()

    st.markdown(f"### {i18n.t('architecture.agent_config')}")
    st.caption(i18n.t("architecture.agent_config.caption"))
    column = {k: i18n.t(f"architecture.column.{k}") for k in
              ("agent", "type", "autonomy", "oversight", "model_class",
               "processes", "write")}
    st.dataframe(
        [{
            column["agent"]: i18n.agent_text(agent_id, "name"),
            column["type"]: i18n.enum_label("type", cfg.type.value),
            # `str(...)`, not the bare int: components without an autonomy
            # level (reader, policy, audit) render "—" here, and a column
            # mixing int and str has no Arrow type -- st.dataframe then
            # fails to serialize it and the whole page raises.
            column["autonomy"]: (str(cfg.autonomy_level.value)
                                 if cfg.autonomy_level else "—"),
            column["oversight"]: i18n.enum_label("oversight", cfg.oversight.value),
            column["model_class"]: i18n.enum_label("model_class",
                                                   cfg.model_class.value),
            column["processes"]: ", ".join(cfg.processes),
            column["write"]: i18n.t("word.yes" if cfg.can_write else "word.no"),
        } for agent_id, cfg in REGISTRY.items()],
        use_container_width=True, hide_index=True,
    )

    st.markdown(f"### {i18n.t('architecture.hitl_points')}")
    for agent_id, cfg in REGISTRY.items():
        if cfg.oversight is OversightMode.HUMAN_IN_THE_LOOP:
            st.warning(f"**{i18n.agent_text(agent_id, 'name')}** — "
                       f"{i18n.agent_text(agent_id, 'description')}")

    st.markdown(f"### {i18n.t('architecture.permissions')}")
    st.markdown(
        f'<div class="field-row"><b>{i18n.t("architecture.feed")}:</b> '
        f'{i18n.t("architecture.feed.text", group=ad.READER_GROUP)}</div>'
        f'<div class="field-row"><b>{i18n.t("architecture.approve")}:</b> '
        f'{i18n.t("architecture.approve.text", group=ad.APPROVAL_GROUP)}</div>'
        f'<div class="field-row"><b>{i18n.t("architecture.model_mode")}:</b> '
        f'<code>{settings.model_mode.value}</code></div>',
        unsafe_allow_html=True,
    )
    st.caption(i18n.t("architecture.footer"))
