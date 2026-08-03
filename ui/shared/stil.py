"""Stylesheet und visuelle Bausteine.

Kennt Streamlit, aber keine Fachlichkeit: was ein Status *bedeutet*, steht in
`graph/vorgaenge.py`; hier steht nur, welche Farbe er bekommt.
"""

from __future__ import annotations

import streamlit as st

from graph.vorgaenge import Status
from ui.shared.formate import feld
from ui.vorgaenge.schritte import Schritt, Schrittstatus

# Vorder-/Hintergrund je Status. Die Farben tragen die Aussage nie allein --
# jedes Badge enthaelt zusaetzlich den Text (Barrierefreiheit).
STATUS_FARBEN = {
    Status.LAEUFT: ("#0b5cad", "#e3f0fb"),
    Status.WARTET_AUF_FREIGABE: ("#8a5a00", "#fdf3e0"),
    Status.ABGESCHLOSSEN: ("#1a6b3c", "#e6f4ec"),
    Status.VERWORFEN: ("#5a5a5a", "#eeeeee"),
    Status.ABGEWIESEN: ("#a3231f", "#fbeaea"),
    Status.FEHLGESCHLAGEN: ("#a3231f", "#fbeaea"),
}

SYMBOLE = {
    Schrittstatus.ERLEDIGT: "✓",
    Schrittstatus.AKTIV: "●",
    Schrittstatus.OFFEN: "○",
    Schrittstatus.UEBERSPRUNGEN: "–",
    Schrittstatus.GESCHEITERT: "✕",
}

_CSS = """
<style>
  .badge {display:inline-block; padding:2px 10px; border-radius:11px;
          font-size:0.78rem; font-weight:600; white-space:nowrap;}
  .stepper {display:flex; flex-wrap:wrap; gap:6px; margin:14px 0 6px 0;}
  .step {flex:1 1 130px; min-width:130px; border-top:3px solid #d6d6d6;
         padding:8px 10px 10px 0;}
  .step .sym {font-size:0.95rem; font-weight:700; margin-right:6px;}
  .step .titel {font-size:0.82rem; line-height:1.25; display:inline;}
  .step .hinweis {display:block; font-size:0.72rem; opacity:0.7; margin-top:3px;}
  .step.erledigt {border-top-color:#1a6b3c;} .step.erledigt .sym {color:#1a6b3c;}
  .step.aktiv {border-top-color:#c47f00;} .step.aktiv .sym {color:#c47f00;}
  .step.gescheitert {border-top-color:#a3231f;} .step.gescheitert .sym {color:#a3231f;}
  .step.offen {opacity:0.55;}
  .step.uebersprungen {opacity:0.5; border-top-style:dashed;}
  .feldzeile {font-size:0.88rem; margin:2px 0;}
  .feldzeile b {font-weight:600;}
  .karte {border:1px solid rgba(128,128,128,0.25); border-radius:9px;
          padding:14px 16px; margin-bottom:10px;}

  /* Der Upload ist die Hauptsache der Startseite und muss das auch aussehen.
     Streamlits Dropzone ist von Haus aus eine schmale Zeile mit Knopf; hier
     wird daraus eine grosse, mittig gesetzte Ablageflaeche.

     Angesprochen werden ausschliesslich die dokumentierten `data-testid`s --
     die Emotion-Klassen daneben wechseln mit jeder Streamlit-Version. */
  .st-key-upload_belege [data-testid="stFileUploaderDropzone"] {
      display:flex; flex-direction:column; align-items:center;
      justify-content:center; gap:0.55rem; text-align:center;
      min-height:210px; padding:30px 20px;
      border:2px dashed rgba(120,130,145,0.45); border-radius:14px;
      background:rgba(120,130,145,0.03);
      transition:border-color .15s ease, background .15s ease;
  }
  .st-key-upload_belege [data-testid="stFileUploaderDropzone"]:hover,
  .st-key-upload_belege [data-testid="stFileUploaderDropzone"]:focus-within {
      border-color:#0b5cad; background:rgba(11,92,173,0.06);
  }

  /* Ablage-Symbol. Rein dekorativ -- die Bedienhinweise stehen als Text
     darunter, damit die Flaeche auch ohne Bild verstaendlich bleibt. */
  .st-key-upload_belege [data-testid="stFileUploaderDropzone"]::before {
      content:""; order:1; width:30px; height:30px; opacity:0.75;
      background-repeat:no-repeat; background-position:center;
      background-size:contain;
      background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23475569' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 16V4'/%3E%3Cpath d='m7 9 5-5 5 5'/%3E%3Cpath d='M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2'/%3E%3C/svg%3E");
  }

  .st-key-upload_belege [data-testid="stFileUploaderDropzoneInstructions"] {
      order:2; display:flex; flex-direction:column; gap:0.15rem;
      color:inherit;
  }
  .st-key-upload_belege [data-testid="stFileUploaderDropzoneInstructions"]::before {
      content:"__ABLAGEHINWEIS__";
      font-size:1rem; font-weight:600;
  }
  .st-key-upload_belege [data-testid="stFileUploaderDropzoneInstructions"] span {
      font-size:0.8rem; opacity:0.7;
  }

  /* Der Knopf steckt in einem <span> -- das ist das Flex-Element, nicht der
     Knopf selbst. Ein `order` am Knopf bliebe wirkungslos. */
  .st-key-upload_belege [data-testid="stFileUploaderDropzone"] > span {
      order:3; margin-top:0.4rem;
  }
  /* Der Knopf traegt von Haus aus dasselbe Pfeilsymbol wie die Flaeche
     darueber -- einmal genuegt. */
  .st-key-upload_belege [data-testid="stFileUploaderDropzone"] button
  [data-testid="stIconMaterial"] {
      display:none;
  }
  .bereichstitel {font-size:0.78rem; font-weight:700; letter-spacing:0.09em;
                  text-transform:uppercase; opacity:0.6; margin:6px 0 2px 0;}

  /* Der Anmeldebereich als abgesetzte Karte: wer gerade angemeldet ist und
     was dieses Konto darf, entscheidet ueber jede Schaltflaeche der App --
     das darf nicht als blasse Zeile untergehen. */
  /* Statuskarte als EIN einzelner, roh gerenderter HTML-Block (ein einziger
     st.markdown()-Aufruf) statt eines Streamlit-Containers mit mehreren
     Kindern. Grund: Streamlit misst die Hoehe mehrelementiger Container per
     JS/ResizeObserver und setzt sie -- ebenfalls mit `!important`, ueber eine
     Klasse, die sich per CSS nicht zuverlaessig uebersteuern liess -- fest.
     Ein mehrzeiliger Satz in kleiner Schrift wurde dabei zu knapp bemessen
     und ragte ueber den Kartenrand hinaus. Ein einzelnes <div>, das der
     Browser nativ sized, hat dieses Problem grundsaetzlich nicht: es ist
     immer genau so hoch wie sein Inhalt. */
  .statuskarte {
      border:1px solid rgba(120,130,145,0.30); border-radius:12px;
      padding:11px 13px; margin:2px 0 10px 0;
      background:rgba(120,130,145,0.06);
  }
  .konto-upn {font-size:0.74rem; opacity:0.65; margin-bottom:8px;
              word-break:break-all;}
  .rechte {display:inline-flex; align-items:center; gap:6px;
           padding:4px 11px; border-radius:11px;
           font-size:0.79rem; font-weight:600;}
  .rechte .punkt {width:7px; height:7px; border-radius:50%;
                  background:currentColor; flex:none;}
  .rechte-satz {font-size:0.76rem; opacity:0.75; line-height:1.4;
                margin:7px 0 0 0;}
</style>
"""


STANDARD_ABLAGEHINWEIS = "Beleg hierher ziehen oder auswählen"


def css(ablagehinweis: str = STANDARD_ABLAGEHINWEIS) -> None:
    """Injiziert das Stylesheet. Einmal pro Seitenaufruf aufrufen.

    Der Bedienhinweis der Ablageflaeche steckt in einer CSS-Regel -- Streamlit
    laesst den Text der Dropzone nicht anders setzen. Er wird deshalb von aussen
    hereingereicht, statt hier die Belegarten zu kennen: dieses Modul gestaltet,
    es weiss nichts von Prozessen.
    """
    st.markdown(_CSS.replace("__ABLAGEHINWEIS__", ablagehinweis),
                unsafe_allow_html=True)


def badge(status: Status) -> str:
    """Statuschip als HTML (zur Einbettung in Markdown-Bloecke)."""
    farbe, hintergrund = STATUS_FARBEN[status]
    return (f'<span class="badge" style="color:{farbe}; background:{hintergrund};">'
            f'{status.beschriftung}</span>')


def stepper(schritte: list[Schritt]) -> None:
    """Zeichnet die Prozessleiste."""
    teile = ['<div class="stepper">']
    for s in schritte:
        hinweis = f'<span class="hinweis">{s.hinweis}</span>' if s.hinweis else ""
        teile.append(
            f'<div class="step {s.status.value}">'
            f'<span class="sym">{SYMBOLE[s.status]}</span>'
            f'<span class="titel">{s.titel}</span>{hinweis}</div>'
        )
    teile.append("</div>")
    st.markdown("".join(teile), unsafe_allow_html=True)


def felder(daten: dict, schluessel) -> None:
    """Gibt ausgewaehlte Felder als beschriftete Zeilen aus."""
    for k in schluessel:
        if k not in daten or daten[k] in (None, "", []):
            continue
        label, wert = feld(k, daten[k])
        st.markdown(f'<div class="feldzeile"><b>{label}:</b> {wert}</div>',
                    unsafe_allow_html=True)


def bereichstitel(text: str) -> None:
    """Kleine Ueberschrift zur Gliederung innerhalb einer Seite."""
    st.markdown(f'<div class="bereichstitel">{text}</div>', unsafe_allow_html=True)


def _rechte_farben(person) -> tuple[str, str]:
    """Vorder-/Hintergrund des Rechte-Abzeichens.

    Gruen heisst handlungsfaehig, grau heisst zusehen -- dieselbe Logik wie
    bei den Vorgangsstatus. Der Text steht immer daneben, die Farbe allein
    traegt die Aussage nie.
    """
    if person.darf_hochladen and person.darf_bestaetigen:
        return "#1a6b3c", "#e6f4ec"
    if person.darf_hochladen or person.darf_bestaetigen:
        return "#0b5cad", "#e3f0fb"
    return "#5a5a5a", "#e8e8e8"


def rechte_abzeichen(person) -> str:
    """Statusabzeichen zu den Rechten eines Kontos, einzeln einsetzbar."""
    farbe, hintergrund = _rechte_farben(person)
    return (f'<span class="rechte" style="color:{farbe}; background:{hintergrund};">'
            f'<span class="punkt"></span>{person.rechte_kurz}</span>')


def statuskarte_html(person, *, upn: str | None = None) -> str:
    """Baut die Anmeldekarte als einen einzelnen HTML-Block.

    Als reine Funktion von Streamlit getrennt, damit sich die Zusammengehoerigkeit
    von Rahmen, Abzeichen und Satz ohne laufende App pruefen laesst.
    """
    farbe, hintergrund = _rechte_farben(person)
    upn_zeile = (f'<div class="konto-upn">{upn}</div>' if upn else "")
    return (
        f'<div class="statuskarte">'
        f'{upn_zeile}'
        f'<span class="rechte" style="color:{farbe}; background:{hintergrund};">'
        f'<span class="punkt"></span>{person.rechte_kurz}</span>'
        f'<div class="rechte-satz">{person.faehigkeiten}</div>'
        f'</div>'
    )


def statuskarte(person, *, upn: str | None = None) -> None:
    """Die Anmeldekarte: Konto, Rechte-Abzeichen und der ausformulierte Satz.

    Absichtlich EIN einzelner `st.markdown()`-Aufruf statt mehrerer Elemente
    in einem Streamlit-Container -- nur so ist garantiert, dass der Rahmen
    exakt um den tatsaechlichen Inhalt passt, auch wenn der Satz auf zwei
    Zeilen umbricht. Ein Streamlit-Container misst seine Hoehe selbst per JS
    und setzt sie fest; bei mehrzeiligem Text traf das daneben.
    """
    st.markdown(statuskarte_html(person, upn=upn), unsafe_allow_html=True)
