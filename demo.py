"""CLI-Runner fuer die fuenf Demonstrationsszenarien.

Faehrt einen Vorgang durch den Graphen und zeigt jeden Schritt samt
Audit-Auszug. An HITL-Punkten haelt der Graph an; im CLI wird die
Freigabeentscheidung entweder per --pruefer/--entscheidung mitgegeben oder
interaktiv erfragt. Die Streamlit-UI (ui/app.py) nutzt denselben Mechanismus.

Aufruf:
    python demo.py --liste
    python demo.py --szenario 1
    python demo.py --szenario 5
    python demo.py --alle
    python demo.py --audit
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

from config import DB_PFAD, EINGANG_DIR, MANIFEST_PFAD, einstellungen
from governance.audit import lies_alle, verify_chain

# Prueferkonten aus dem AD-Mock (Mitglieder von SG-CHG-Freigabe).
STANDARD_PRUEFER = "s.hofmann@chg-meridian.com"


def _manifest() -> list[dict]:
    if not MANIFEST_PFAD.is_file():
        sys.exit("Testdaten fehlen. Zuerst ausfuehren:  python -m data.generate")
    return json.loads(MANIFEST_PFAD.read_text(encoding="utf-8"))


def _trenner(text: str = "") -> None:
    print(f"\n{'=' * 78}")
    if text:
        print(text)
        print("=" * 78)


def liste() -> None:
    print("Verfuegbare Dokumente:\n")
    for d in _manifest():
        stoer = f"  [Stoerfall: {d['stoerfall']}]" if d["stoerfall"] else ""
        print(f"  {d['szenario']:28s} {d['dateiname']:36s} Prozess {d['prozess']}{stoer}")
        print(f"  {'':28s} Erwartung: {d['erwartung']}")
        print()


def _antwort_auf(anfrage: dict, pruefer: str, entscheidung: str) -> dict:
    """Baut die Freigabeantwort fuer einen Interrupt."""
    art = anfrage.get("art")
    if art == "kostenstellen_freigabe":
        # Ist der Vorschlag mehrdeutig, entscheidet der Mensch aktiv; sonst
        # bestaetigt er den Vorschlag.
        kst = anfrage.get("vorschlag")
        if not kst:
            alternativen = anfrage.get("alternativen") or []
            kst = alternativen[0] if alternativen else None
        return {"entscheidung": entscheidung, "pruefer": pruefer, "kostenstelle_id": kst}
    return {"entscheidung": entscheidung, "pruefer": pruefer,
            "nummer": anfrage.get("nummer")}


def fuehre_aus(dok: dict, *, pruefer: str, entscheidung: str, interaktiv: bool) -> None:
    from langgraph.types import Command

    from graph.workflow import kompiliere

    app, cp_con = kompiliere()
    thread = {"configurable": {"thread_id": f"{dok['dateiname']}-{uuid.uuid4().hex[:8]}"}}

    _trenner(f"SZENARIO {dok['szenario']}  |  {dok['dateiname']}")
    print(f"Einspeiser: {dok['einspeiser']}")
    print(f"Erwartung:  {dok['erwartung']}")
    if dok["stoerfall"]:
        print(f"Stoerfall:  {dok['stoerfall']}")
    print(f"Modus:      MODELL_MODUS={einstellungen.modell_modus.value}, "
          f"Schwelle={einstellungen.buchung_schwelle_eur:.0f} EUR")
    print("-" * 78)

    try:
        zustand = app.invoke(
            {"pfad": str(EINGANG_DIR / dok["dateiname"]), "akteur": dok["einspeiser"],
             "protokoll": []},
            thread,
        )

        # Solange der Graph an einem HITL-Punkt haengt, entscheiden lassen.
        while "__interrupt__" in zustand:
            anfrage = zustand["__interrupt__"][0].value
            print(f"\n  >>> HUMAN-IN-THE-LOOP: {anfrage.get('art')}")
            for k, v in anfrage.items():
                if k != "art" and v not in (None, [], ""):
                    print(f"      {k}: {v}")

            if interaktiv:
                eingabe = input(f"\n      Freigeben? [j/n] (als {pruefer}): ").strip().lower()
                ent = "freigegeben" if eingabe in ("j", "ja", "y", "") else "verworfen"
            else:
                ent = entscheidung
                print(f"\n      -> automatisch '{ent}' durch {pruefer}")

            zustand = app.invoke(
                Command(resume=_antwort_auf(anfrage, pruefer, ent)), thread
            )

        print("\n  Ablauf:")
        for s in zustand.get("protokoll", []):
            print(f"    [{s['knoten']:12s}] {s['text']}")

        print(f"\n  ERGEBNIS: {zustand.get('ergebnis', 'unbekannt')}")
        if zustand.get("fehler"):
            print(f"  FEHLER:   {zustand['fehler']}")
        _zeige_wirkung(dok, zustand)
    finally:
        cp_con.close()


def _zeige_wirkung(dok: dict, zustand: dict) -> None:
    """Zeigt die Wirkung im Zielsystem -- der eigentliche Nachweis."""
    con = sqlite3.connect(DB_PFAD)
    try:
        if zustand.get("nummer"):
            row = con.execute("SELECT status, bezahlt_am FROM rechnungen WHERE nummer = ?",
                              (zustand["nummer"],)).fetchone()
            if row:
                print(f"  NAVISION: {zustand['nummer']} -> Status '{row[0]}'")
        if zustand.get("archiv_id"):
            print(f"  ELO:      {zustand['archiv_id']} (revisionssicher, Prozessende B)")

        eintraege = lies_alle(con)
        print(f"\n  Audit-Trail (letzte Eintraege dieses Laufs):")
        for e in eintraege[-6:]:
            print(f"    #{e.id:03d} [{e.entscheidung.value:10s}] {e.agent or '-':14s} "
                  f"{e.aktion:26s} {e.begruendung[:60]}")
        print(f"  {verify_chain(con)}")
    finally:
        con.close()


def zeige_audit() -> None:
    con = sqlite3.connect(DB_PFAD)
    try:
        _trenner("AUDIT-TRAIL (vollstaendig)")
        for e in lies_alle(con):
            print(f"#{e.id:03d} {e.ts[:19]} [{e.entscheidung.value:10s}] "
                  f"{e.akteur:34s} {e.agent or '-':14s} {e.aktion:26s}")
            print(f"     {e.begruendung}")
            print(f"     hash={e.hash[:16]}...  prev={e.prev_hash[:16]}...")
        print()
        print(verify_chain(con))
    finally:
        con.close()


def pruefe_modelle() -> bool:
    """Zeigt den Bereitstellungsstatus. Laedt nichts -- das macht `ollama pull`."""
    from llm.preflight import pruefe

    befund = pruefe()
    _trenner("MODELL-BEREITSTELLUNG")
    print(befund.bericht())
    return befund.bereit


def main() -> None:
    p = argparse.ArgumentParser(description="Demo des CHG-MERIDIAN Multiagentensystems")
    p.add_argument("--liste", action="store_true", help="verfuegbare Dokumente zeigen")
    p.add_argument("--szenario", help="Szenario-Nummer (1,2,3,4,5) oder Dateiname")
    p.add_argument("--alle", action="store_true", help="alle Szenarien nacheinander")
    p.add_argument("--audit", action="store_true", help="Audit-Trail ausgeben")
    p.add_argument("--check", action="store_true",
                   help="Modell-Bereitstellung pruefen (Ollama-Verbindung/Modelle)")
    p.add_argument("--pruefer", default=STANDARD_PRUEFER, help="UPN fuer Freigaben")
    p.add_argument("--entscheidung", default="freigegeben",
                   choices=["freigegeben", "verworfen"])
    p.add_argument("--interaktiv", action="store_true", help="Freigaben abfragen")
    args = p.parse_args()

    if args.liste:
        return liste()
    if args.audit:
        return zeige_audit()
    if args.check:
        sys.exit(0 if pruefe_modelle() else 1)

    docs = _manifest()
    if args.alle:
        for d in docs:
            fuehre_aus(d, pruefer=args.pruefer, entscheidung=args.entscheidung,
                       interaktiv=args.interaktiv)
        return
    if not args.szenario:
        return p.print_help()

    treffer = [d for d in docs
               if d["szenario"].startswith(args.szenario) or d["dateiname"] == args.szenario]
    if not treffer:
        sys.exit(f"Kein Dokument zu {args.szenario!r}. `--liste` zeigt alle.")

    # Szenario 5 endet am AD-Check und braucht kein Modell -- dafuer soll die
    # Governance-Demo nicht an einer fehlenden Ollama-Instanz scheitern.
    braucht_modell = any(d["szenario"] != "5_ad_check_verweigert" for d in treffer)
    if braucht_modell and not pruefe_modelle():
        print("\nHinweis: Szenario 5 (Governance-Demo) laeuft auch ohne Modell:")
        print("  python demo.py --szenario 5")
        sys.exit(1)

    for d in treffer:
        fuehre_aus(d, pruefer=args.pruefer, entscheidung=args.entscheidung,
                   interaktiv=args.interaktiv)


if __name__ == "__main__":
    main()
