"""Page 'Architektur': roles, autonomy levels, oversight.

This page *reads* the registries, it does not describe them. That way the
thesis's central claim -- role- and risk-based configuration that is
effective, not merely documented -- is directly readable in the UI, without
creating a second place to maintain.

**Domain jargon belongs here on purpose.** Every working view is
deliberately free of "Prozess A", "Human-in-the-loop", or security groups --
a case worker does not need them. Whoever wants to assess the architecture
needs exactly them, and finds them in this one place.
"""

from __future__ import annotations

import streamlit as st

import process_registry
from agent_registry import REGISTRY, OversightMode
from config import settings
from governance import ad
from ui.shared import style
from ui.cases.steps import steps_for


def render() -> None:
    style.css()
    st.title("Architektur")
    st.caption("Fachliche Sicht auf das System: welche Rolle handelt in "
               "welchem Schritt, mit welcher Autonomiestufe und unter welcher "
               "Aufsicht. Die Arbeitsansichten kommen bewusst ohne diese "
               "Begriffe aus.")

    for config in process_registry.all_processes():
        st.markdown(f"### Prozess {config.key} · "
                    f"{config.name}")
        st.write(config.description)
        # All steps shown neutrally: this explains the flow, not a case.
        style.stepper(steps_for(config.key, []))

        for step in config.steps:
            if not step.agent_id:
                continue
            cfg = REGISTRY[step.agent_id]
            marker = "🔒 " if cfg.oversight is OversightMode.HUMAN_IN_THE_LOOP else ""
            level = (f"Stufe {cfg.autonomy_level.value}"
                    if cfg.autonomy_level else "keine Stufe")
            st.markdown(
                f'<div class="feldzeile">{marker}<b>{step.title}</b> — '
                f'{cfg.name} · {level} · {cfg.oversight.value} · '
                f'{cfg.model_class.value}</div>',
                unsafe_allow_html=True,
            )
        st.divider()

    st.markdown("### Agentenkonfiguration")
    st.caption("Aus `agent_registry.py`. Eine Änderung dort ändert das "
               "Laufzeitverhalten – die Tabelle ist Durchsetzung, nicht "
               "Dokumentation.")
    st.dataframe(
        [{
            "Agent": cfg.name,
            "Typ": cfg.type.value,
            # `str(...)`, not the bare int: components without an autonomy
            # level (reader, policy, audit) render "—" here, and a column
            # mixing int and str has no Arrow type -- st.dataframe then
            # fails to serialize it and the whole page raises.
            "Autonomiestufe": (str(cfg.autonomy_level.value)
                               if cfg.autonomy_level else "—"),
            "Aufsicht": cfg.oversight.value,
            "Modellklasse": cfg.model_class.value,
            "Prozesse": ", ".join(cfg.processes),
            "Schreibrecht": "ja" if cfg.can_write else "nein",
        } for cfg in REGISTRY.values()],
        use_container_width=True, hide_index=True,
    )

    st.markdown("### Human-in-the-loop-Punkte")
    for cfg in REGISTRY.values():
        if cfg.oversight is OversightMode.HUMAN_IN_THE_LOOP:
            st.warning(f"**{cfg.name}** — {cfg.description}")

    st.markdown("### Berechtigungen und Betrieb")
    st.markdown(
        f'<div class="feldzeile"><b>Belege einspeisen:</b> Mitglieder von '
        f'<code>{ad.READER_GROUP}</code> — geprüft im Reader-Tool, vor jedem '
        f'Dateizugriff (Least Privilege).</div>'
        f'<div class="feldzeile"><b>Freigaben erteilen:</b> Mitglieder von '
        f'<code>{ad.APPROVAL_GROUP}</code> — Vier-Augen-Prinzip an den '
        f'Human-in-the-loop-Punkten.</div>'
        f'<div class="feldzeile"><b>Modell-Modus:</b> '
        f'<code>{settings.model_mode.value}</code></div>',
        unsafe_allow_html=True,
    )
    st.caption("Diese Gruppennamen erscheinen nur hier. In den "
               "Arbeitsansichten steht stattdessen, was eine Person tun kann "
               "und was nicht.")
