"""Vorgangslisten -- eine Implementierung fuer alle Seiten.

Zwei Darstellungen, bewusst unterschiedlich eingesetzt:

- **Karten** dort, wo gehandelt wird (offene Freigaben, zuletzt Eingespeistes):
  mehr Kontext je Zeile und ein direkter Knopf.
- **Tabelle** dort, wo gesucht wird (Historie, abgeschlossene Vorgaenge):
  dicht und auf viele Zeilen ausgelegt.

Alle Ansichten speisen sich aus derselben Quelle (`graph.vorgaenge.uebersicht`)
und unterscheiden sich nur im Filter -- doppelte Listenlogik gibt es nicht.
"""

from __future__ import annotations

import streamlit as st

import prozessregistry
from graph.vorgaenge import Status, Vorgangsuebersicht
from ui.shared import stil
from ui.shared.filter import SEITENGROESSE, Filter, wende_an
from ui.shared.formate import beschriftung, datum, zeitpunkt
from ui.shared.kontext import oeffne_vorgang

def _belegart(schluessel: str | None) -> str:
    """Was fuer ein Dokument das ist -- nicht, wie der Prozess dazu heisst.

    In einer Vorgangsliste steht ein einzelnes Dokument; „Zahlungsbestätigung"
    sagt darueber mehr als „Zahlungseingang". Solange die Auswertung laeuft,
    steht die Art noch nicht fest.
    """
    if not schluessel:
        return "wird erkannt"
    return prozessregistry.konfiguration(schluessel).belegart


# ------------------------------------------------------------------ Filterleiste

def filterleiste(*, schluessel: str, prozess_fest: str | None = None) -> Filter:
    """Sammelt die Filtereingaben ein.

    Auf einer Prozessseite ist der Prozess bereits durch die Seite bestimmt --
    dann wird das Feld nicht angeboten, statt es sinnlos anzuzeigen.
    """
    oben = st.columns([3, 2, 2] if prozess_fest else [3, 2, 2, 2])
    suche = oben[0].text_input("Suche", key=f"suche_{schluessel}",
                               placeholder="Beleg, Person, Ergebnis …")

    spalte = 1
    prozesse: set[str] = set()
    if not prozess_fest:
        gewaehlt = oben[spalte].multiselect(
            "Belegart", [p.schluessel for p in prozessregistry.alle()],
            format_func=_belegart, key=f"proz_{schluessel}")
        prozesse = set(gewaehlt)
        spalte += 1

    stati = oben[spalte].multiselect(
        "Status", list(Status), format_func=lambda s: s.beschriftung,
        key=f"stat_{schluessel}")
    zeitraum = oben[spalte + 1].date_input(
        "Eingegangen zwischen", value=(), key=f"zeit_{schluessel}",
        help="Leer lassen, um alle Vorgänge zu sehen")

    von = bis = ""
    if isinstance(zeitraum, (tuple, list)) and len(zeitraum) == 2:
        von, bis = zeitraum[0].isoformat(), zeitraum[1].isoformat()

    return Filter(suche=suche, prozesse=frozenset(prozesse),
                  stati=frozenset(stati), von=von, bis=bis)


# ---------------------------------------------------------------------- Karten

def als_karten(zeilen: list[Vorgangsuebersicht], *, schluessel: str,
               mit_prozess: bool = True) -> None:
    for z in zeilen:
        with st.container(border=True):
            links, mitte, rechts = st.columns([4, 3, 1.4])
            with links:
                st.markdown(f"**{z.dateiname}**")
                teile = [f"von {z.akteur}"]
                if mit_prozess:
                    teile.insert(0, _belegart(z.prozess))
                st.caption(" · ".join(teile))
            with mitte:
                st.markdown(stil.badge(z.status), unsafe_allow_html=True)
                st.caption(f"Gestartet {zeitpunkt(z.gestartet_am)}")
            with rechts:
                if st.button("Öffnen", key=f"o_{schluessel}_{z.thread_id}",
                             use_container_width=True):
                    oeffne_vorgang(z.thread_id)


# -------------------------------------------------------------------- Tabelle

def als_tabelle(zeilen: list[Vorgangsuebersicht], *, schluessel: str,
                konfiguration=None) -> None:
    """Dichte Ansicht mit schrittweisem Nachladen.

    Nachladen statt Blaettern: Streamlit rendert bei jeder Interaktion neu, und
    eine Seitenzahl im Sitzungszustand waere ein zusaetzlicher Zustand, der mit
    Filtern konsistent gehalten werden muesste.
    """
    grenze_key = f"anzahl_{schluessel}"
    grenze = st.session_state.get(grenze_key, SEITENGROESSE)
    sichtbar = zeilen[:grenze]

    spalten = ["Beleg", "Belegart", "Status", "Hochgeladen von",
               "Eingegangen", "Ergebnis"]
    if konfiguration:
        spalten.remove("Belegart")

    st.dataframe(
        [{
            "Beleg": z.dateiname,
            **({} if konfiguration else
               {"Belegart": _belegart(z.prozess)}),
            "Status": z.status.beschriftung,
            "Hochgeladen von": z.akteur,
            "Eingegangen": datum(z.gestartet_am),
            "Ergebnis": z.ergebnis or "—",
        } for z in sichtbar],
        column_order=spalten, use_container_width=True, hide_index=True,
    )

    if len(zeilen) > grenze:
        if st.button(f"Weitere {min(SEITENGROESSE, len(zeilen) - grenze)} anzeigen",
                     key=f"mehr_{schluessel}"):
            st.session_state[grenze_key] = grenze + SEITENGROESSE
            st.rerun()
        st.caption(f"{len(sichtbar)} von {len(zeilen)} Vorgängen")

    # Aus einer Tabelle heraus laesst sich nicht klicken -- die Auswahl daher
    # ueber ein Feld, damit auch historische Vorgaenge erreichbar bleiben.
    auswahl = st.selectbox(
        "Vorgang öffnen", ["—", *[z.thread_id for z in sichtbar]],
        format_func=lambda t: t if t == "—" else next(
            (f"{z.dateiname} · {zeitpunkt(z.gestartet_am)}"
             for z in sichtbar if z.thread_id == t), t),
        key=f"wahl_{schluessel}",
    )
    if auswahl != "—":
        oeffne_vorgang(auswahl)


# ------------------------------------------------------------------ Leerzustand

def leerzustand(text: str, *, filter_aktiv: bool, schluessel: str) -> None:
    if filter_aktiv:
        st.info("Keine Vorgänge passen zu Ihrer Suche.")
        if st.button("Suche zurücksetzen", key=f"reset_{schluessel}"):
            for praefix in ("suche_", "proz_", "stat_", "zeit_"):
                st.session_state.pop(f"{praefix}{schluessel}", None)
            st.rerun()
    else:
        st.info(text)


# ------------------------------------------------------- Zusammengesetzte Sicht

def abschnitt(zeilen: list[Vorgangsuebersicht], *, titel: str, schluessel: str,
              darstellung: str = "tabelle", leer: str = "Keine Vorgänge.",
              konfiguration=None, filter_aktiv: bool = False) -> None:
    """Ein beschrifteter Listenabschnitt."""
    stil.bereichstitel(titel)
    if not zeilen:
        leerzustand(leer, filter_aktiv=filter_aktiv, schluessel=schluessel)
        return
    if darstellung == "karten":
        als_karten(zeilen, schluessel=schluessel, mit_prozess=konfiguration is None)
    else:
        als_tabelle(zeilen, schluessel=schluessel, konfiguration=konfiguration)


def gefiltert(zeilen: list[Vorgangsuebersicht], f: Filter) -> list[Vorgangsuebersicht]:
    return wende_an(zeilen, f)


__all__ = ["abschnitt", "als_karten", "als_tabelle", "filterleiste", "gefiltert",
           "leerzustand", "beschriftung"]
