"""Streamlit-UI: die Freigabe-Queue (Human-in-the-loop).

Zeigt die Vorgaenge, die an einem HITL-Punkt haengen, und setzt sie nach der
Entscheidung des Menschen ueber den LangGraph-Checkpoint fort. Die UI ist damit
kein Beiwerk, sondern der sichtbare Beleg fuer den Aufsichtsmodus: was hier
liegt, laeuft ohne Menschen nicht weiter.

Die Freigabeberechtigung wird geprueft (Vier-Augen-Prinzip) -- ein Nutzer ohne
Mitgliedschaft in SG-CHG-Freigabe kann hier nichts entscheiden.

Start:  streamlit run ui/app.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_PFAD, einstellungen  # noqa: E402
from governance import ad  # noqa: E402
from governance.audit import lies_alle, verify_chain  # noqa: E402
from governance.policy import pruefe_freigabe  # noqa: E402

st.set_page_config(page_title="CHG-MERIDIAN Freigabe-Queue", layout="wide")


@st.cache_resource
def _graph():
    from graph.workflow import kompiliere
    return kompiliere()


def _con() -> sqlite3.Connection:
    return sqlite3.connect(DB_PFAD)


def _pruefer_auswahl(con: sqlite3.Connection) -> str:
    """Wer ist angemeldet? Im Prototyp eine Auswahl statt echter Authentifizierung."""
    nutzer = con.execute(
        "SELECT upn, anzeigename FROM ad_nutzer ORDER BY anzeigename"
    ).fetchall()
    labels = {f"{name} ({upn})": upn for upn, name in nutzer}
    wahl = st.sidebar.selectbox("Angemeldet als", list(labels))
    return labels[wahl]


def main() -> None:
    st.title("Freigabe-Queue")
    st.caption("Human-in-the-loop-Punkte des Multiagentensystems. "
               "Vorgaenge hier laufen ohne menschliche Entscheidung nicht weiter.")

    con = _con()
    try:
        upn = _pruefer_auswahl(con)
        berechtigt = pruefe_freigabe(con, akteur=upn, agent_id="kostenstelle")

        st.sidebar.markdown("---")
        st.sidebar.write(f"**Modell-Modus:** `{einstellungen.modell_modus.value}`")
        st.sidebar.write(f"**Freigabegruppe:** `{ad.FREIGABE_GRUPPE}`")

        if berechtigt.erlaubt:
            st.sidebar.success(berechtigt.begruendung)
        else:
            st.sidebar.error(berechtigt.begruendung)

        tab_queue, tab_audit = st.tabs(["Offene Freigaben", "Audit-Trail"])

        with tab_queue:
            _zeige_queue(upn, berechtigt.erlaubt)

        with tab_audit:
            _zeige_audit(con)
    finally:
        con.close()


def _zeige_queue(upn: str, berechtigt: bool) -> None:
    from langgraph.types import Command

    app, _ = _graph()

    # LangGraph fuehrt keine globale Liste offener Threads -- die Thread-IDs
    # muessen von aussen kommen. Der Prototyp liest sie aus der
    # Checkpoint-Datenbank.
    threads = _offene_threads()

    if not threads:
        st.info("Keine offenen Freigaben. Vorgaenge starten mit "
                "`python demo.py --szenario 2` (oder 3/4).")
        return

    if not berechtigt:
        st.warning("Der angemeldete Nutzer ist nicht freigabeberechtigt. "
                   "Vier-Augen-Prinzip: bitte als Pruefer anmelden.")

    for thread_id in threads:
        cfg = {"configurable": {"thread_id": thread_id}}
        zustand = app.get_state(cfg)
        if not zustand.interrupts:
            continue

        anfrage = zustand.interrupts[0].value
        with st.container(border=True):
            st.subheader(f"{anfrage.get('dateiname', thread_id)}")
            st.write(f"**Art:** {anfrage.get('art')}")

            spalte_a, spalte_b = st.columns(2)
            with spalte_a:
                for k in ("grund", "befund", "nummer", "lieferant", "referenz"):
                    if anfrage.get(k):
                        st.write(f"**{k}:** {anfrage[k]}")
            with spalte_b:
                for k in ("betrag_eur", "soll_betrag_eur", "begruendung"):
                    if anfrage.get(k) not in (None, ""):
                        st.write(f"**{k}:** {anfrage[k]}")

            if anfrage.get("positionen"):
                st.write("**Positionen:**")
                for p in anfrage["positionen"]:
                    st.write(f"- {p}")

            kostenstelle_id = None
            if anfrage.get("art") == "kostenstellen_freigabe":
                katalog = anfrage.get("katalog") or []
                optionen = [k["id"] for k in katalog] or _alle_kostenstellen()
                labels = {k["id"]: f"{k['id']} — {k['bezeichnung']} ({k['referenz']})"
                          for k in katalog}
                st.warning("Keine Kostenstellenreferenz auf dem Beleg -- bitte "
                           "Kostenstelle waehlen.")
                kostenstelle_id = st.selectbox(
                    "Kostenstelle", optionen,
                    format_func=lambda o: labels.get(o, o), key=f"k{thread_id}")

            links, rechts = st.columns(2)
            with links:
                if st.button("Freigeben", key=f"f{thread_id}", type="primary",
                             disabled=not berechtigt, use_container_width=True):
                    antwort = {"entscheidung": "freigegeben", "pruefer": upn,
                               "nummer": anfrage.get("nummer")}
                    if kostenstelle_id:
                        antwort["kostenstelle_id"] = kostenstelle_id
                    app.invoke(Command(resume=antwort), cfg)
                    st.rerun()
            with rechts:
                if st.button("Verwerfen", key=f"v{thread_id}", disabled=not berechtigt,
                             use_container_width=True):
                    app.invoke(
                        Command(resume={"entscheidung": "verworfen", "pruefer": upn}), cfg
                    )
                    st.rerun()


def _offene_threads() -> list[str]:
    """Liest die Thread-IDs aus der Checkpoint-Datenbank."""
    from config import CHECKPOINT_PFAD

    if not Path(CHECKPOINT_PFAD).is_file():
        return []
    con = sqlite3.connect(CHECKPOINT_PFAD)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        ).fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def _alle_kostenstellen() -> list[str]:
    con = _con()
    try:
        return [r[0] for r in con.execute(
            "SELECT id FROM kostenstellen ORDER BY id").fetchall()]
    finally:
        con.close()


def _zeige_audit(con: sqlite3.Connection) -> None:
    ergebnis = verify_chain(con)
    if ergebnis.gueltig:
        st.success(str(ergebnis))
    else:
        st.error(str(ergebnis))

    eintraege = lies_alle(con)
    if not eintraege:
        st.info("Noch keine Audit-Eintraege.")
        return

    st.dataframe(
        [{"#": e.id, "Zeit": e.ts[:19], "Entscheidung": e.entscheidung.value,
          "Akteur": e.akteur, "Agent": e.agent or "-", "Aktion": e.aktion,
          "Begruendung": e.begruendung, "Hash": e.hash[:12] + "..."}
         for e in reversed(eintraege)],
        use_container_width=True, hide_index=True,
    )


main()
