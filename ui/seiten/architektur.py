"""Seite 'Architektur': Rollen, Autonomiestufen, Aufsicht.

Diese Seite *liest* die Registries, sie beschreibt sie nicht. Damit ist die
zentrale Aussage der Arbeit -- rollen- und risikobasierte Konfiguration, die
wirksam ist und nicht bloß dokumentiert -- direkt in der Oberfläche ablesbar,
ohne eine zweite Pflegestelle zu schaffen.

**Hier stehen die Fachbegriffe mit Absicht.** Alle Arbeitsansichten sind
bewusst frei von „Prozess A", „Human-in-the-loop" oder Sicherheitsgruppen --
ein Sachbearbeiter braucht sie nicht. Wer die Architektur beurteilen will,
braucht genau sie, und findet sie an dieser einen Stelle.
"""

from __future__ import annotations

import streamlit as st

import prozessregistry
from config import einstellungen
from governance import ad
from registry import REGISTRY, Aufsichtsmodus
from ui.shared import stil
from ui.vorgaenge.schritte import schritte_fuer


def seite() -> None:
    stil.css()
    st.title("Architektur")
    st.caption("Fachliche Sicht auf das System: welche Rolle handelt in "
               "welchem Schritt, mit welcher Autonomiestufe und unter welcher "
               "Aufsicht. Die Arbeitsansichten kommen bewusst ohne diese "
               "Begriffe aus.")

    for konfiguration in prozessregistry.alle():
        st.markdown(f"### Prozess {konfiguration.schluessel} · "
                    f"{konfiguration.bezeichnung}")
        st.write(konfiguration.beschreibung)
        # Alle Schritte neutral: hier wird der Ablauf erklaert, kein Vorgang.
        stil.stepper(schritte_fuer(konfiguration.schluessel, []))

        for schritt in konfiguration.schritte:
            if not schritt.agent_id:
                continue
            cfg = REGISTRY[schritt.agent_id]
            marke = "🔒 " if cfg.aufsicht is Aufsichtsmodus.HUMAN_IN_THE_LOOP else ""
            stufe = (f"Stufe {cfg.autonomiestufe.value}"
                     if cfg.autonomiestufe else "keine Stufe")
            st.markdown(
                f'<div class="feldzeile">{marke}<b>{schritt.titel}</b> — '
                f'{cfg.name} · {stufe} · {cfg.aufsicht.value} · '
                f'{cfg.modellklasse.value}</div>',
                unsafe_allow_html=True,
            )
        st.divider()

    st.markdown("### Agentenkonfiguration")
    st.caption("Aus `registry.py`. Eine Änderung dort ändert das "
               "Laufzeitverhalten – die Tabelle ist Durchsetzung, nicht "
               "Dokumentation.")
    st.dataframe(
        [{
            "Agent": cfg.name,
            "Typ": cfg.typ.value,
            "Autonomiestufe": cfg.autonomiestufe.value if cfg.autonomiestufe else "—",
            "Aufsicht": cfg.aufsicht.value,
            "Modellklasse": cfg.modellklasse.value,
            "Prozesse": ", ".join(cfg.prozesse),
            "Schreibrecht": "ja" if cfg.darf_schreiben else "nein",
        } for cfg in REGISTRY.values()],
        use_container_width=True, hide_index=True,
    )

    st.markdown("### Human-in-the-loop-Punkte")
    for cfg in REGISTRY.values():
        if cfg.aufsicht is Aufsichtsmodus.HUMAN_IN_THE_LOOP:
            st.warning(f"**{cfg.name}** — {cfg.beschreibung}")

    st.markdown("### Berechtigungen und Betrieb")
    st.markdown(
        f'<div class="feldzeile"><b>Belege einspeisen:</b> Mitglieder von '
        f'<code>{ad.READER_GRUPPE}</code> — geprüft im Reader-Tool, vor jedem '
        f'Dateizugriff (Least Privilege).</div>'
        f'<div class="feldzeile"><b>Freigaben erteilen:</b> Mitglieder von '
        f'<code>{ad.FREIGABE_GRUPPE}</code> — Vier-Augen-Prinzip an den '
        f'Human-in-the-loop-Punkten.</div>'
        f'<div class="feldzeile"><b>Modell-Modus:</b> '
        f'<code>{einstellungen.modell_modus.value}</code></div>',
        unsafe_allow_html=True,
    )
    st.caption("Diese Gruppennamen erscheinen nur hier. In den "
               "Arbeitsansichten steht stattdessen, was eine Person tun kann "
               "und was nicht.")
