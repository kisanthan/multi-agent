"""CLI runner for the five demonstration scenarios.

Runs a case through the graph and shows every step along with an audit
excerpt. At HITL points the graph pauses; in the CLI the approval decision
is either supplied via --pruefer/--entscheidung or asked for interactively.
The Streamlit UI (ui/app.py) uses the same mechanism.

Usage:
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
from datetime import datetime, timezone

from config import DB_PATH, INTAKE_DIR, MANIFEST_PATH, settings
from contracts import InterruptKind
from data.bootstrap import ensure_configured_runtime
from governance.audit import read_all, verify_chain
from graph.effects import read_effect

# Approver accounts from the AD mock (members of SG-CHG-Freigabe).
DEFAULT_APPROVER = "s.hofmann@chg-meridian.com"


def _manifest() -> list[dict]:
    if not MANIFEST_PATH.is_file():
        sys.exit("Testdaten fehlen. Zuerst ausfuehren:  python -m data.generate")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _separator(text: str = "") -> None:
    print(f"\n{'=' * 78}")
    if text:
        print(text)
        print("=" * 78)


def list_documents() -> None:
    print("Verfuegbare Dokumente:\n")
    for d in _manifest():
        incident = f"  [Stoerfall: {d['incident']}]" if d["incident"] else ""
        print(f"  {d['scenario']:28s} {d['filename']:36s} Prozess {d['process']}{incident}")
        print(f"  {'':28s} Erwartung: {d['expectation']}")
        print()


def _response_to(request: dict, approver: str, decision: str) -> dict:
    """Builds the approval response for an interrupt."""
    kind = request.get("kind")
    if kind == InterruptKind.COST_CENTER_APPROVAL.value:
        # If the document reference is missing, the approver picks from the
        # catalog. In the non-interactive run we take the first catalog
        # entry.
        catalog = request.get("catalog") or []
        cost_center_id = catalog[0]["id"] if catalog else None
        return {"decision": decision, "approver": approver, "cost_center_id": cost_center_id}
    return {"decision": decision, "approver": approver,
            "number": request.get("number")}


def run_case(doc: dict, *, approver: str, decision: str, interactive: bool) -> None:
    from langgraph.types import Command

    from graph.workflow import compile_graph

    app, cp_con = compile_graph()
    case_id = f"{doc['filename']}-{uuid.uuid4().hex[:8]}"
    thread = {"configurable": {"thread_id": case_id}}

    _separator(f"SZENARIO {doc['scenario']}  |  {doc['filename']}")
    print(f"Einspeiser: {doc['submitter']}")
    print(f"Erwartung:  {doc['expectation']}")
    if doc["incident"]:
        print(f"Stoerfall:  {doc['incident']}")
    print(f"Konfiguration: Revision {settings.configuration_revision}")
    for profile_id, profile in settings.profile_snapshot().items():
        print(f"  {profile_id:9s} {profile['provider']} / {profile['model_id']}")
    print("-" * 78)

    try:
        state = app.invoke(
            {"path": str(INTAKE_DIR / doc["filename"]), "actor": doc["submitter"],
             "case_id": case_id,
             "started_at": datetime.now(timezone.utc).isoformat(),
             "configuration_revision": settings.configuration_revision,
             "model_profiles": settings.profile_snapshot(), "log": []},
            thread,
        )

        # As long as the graph is stuck at a HITL point, keep asking for a decision.
        while "__interrupt__" in state:
            request = state["__interrupt__"][0].value
            print(f"\n  >>> HUMAN-IN-THE-LOOP: {request.get('kind')}")
            for k, v in request.items():
                if k != "kind" and v not in (None, [], ""):
                    print(f"      {k}: {v}")

            if interactive:
                answer = input(f"\n      Freigeben? [j/n] (als {approver}): ").strip().lower()
                dec = "freigegeben" if answer in ("j", "ja", "y", "") else "verworfen"
            else:
                dec = decision
                print(f"\n      -> automatisch '{dec}' durch {approver}")

            state = app.invoke(
                Command(resume=_response_to(request, approver, dec)), thread
            )

        print("\n  Ablauf:")
        for s in state.get("log", []):
            print(f"    [{s['node']:12s}] {s['text']}")

        print(f"\n  ERGEBNIS: {state.get('outcome', 'unbekannt')}")
        if state.get("error"):
            print(f"  FEHLER:   {state['error']}")
        _show_effect(doc, state)
    finally:
        cp_con.close()


def _show_effect(doc: dict, state: dict) -> None:
    """Shows the effect in the target system -- the actual evidence."""
    con = sqlite3.connect(DB_PATH)
    try:
        # The UI's confirmation card uses the same query.
        effect = read_effect(con, state)
        if effect.navision_status:
            print(f"  NAVISION: {effect.navision_number} -> "
                  f"Status '{effect.navision_status}'")
        if effect.elo_archive_id:
            print(f"  ELO:      {effect.elo_archive_id} "
                  "(revisionssicher, Prozessende B)")

        entries = read_all(con)
        print(f"\n  Audit-Trail (letzte Eintraege dieses Laufs):")
        for e in entries[-6:]:
            print(f"    #{e.id:03d} [{e.decision.value:10s}] {e.agent or '-':14s} "
                  f"{e.action:26s} {e.reason[:60]}")
        print(f"  {verify_chain(con)}")
    finally:
        con.close()


def show_audit() -> None:
    con = sqlite3.connect(DB_PATH)
    try:
        _separator("AUDIT-TRAIL (vollstaendig)")
        for e in read_all(con):
            print(f"#{e.id:03d} {e.ts[:19]} [{e.decision.value:10s}] "
                  f"{e.actor:34s} {e.agent or '-':14s} {e.action:26s}")
            print(f"     {e.reason}")
            print(f"     hash={e.hash[:16]}...  prev={e.prev_hash[:16]}...")
        print()
        print(verify_chain(con))
    finally:
        con.close()


def check_models() -> bool:
    """Shows the deployment status. Loads nothing -- `ollama pull` does that."""
    from llm.preflight import check

    readiness = check()
    _separator("MODELL-BEREITSTELLUNG")
    print(readiness.report())
    return readiness.ready


def main() -> None:
    p = argparse.ArgumentParser(description="Demo des CHG-MERIDIAN Multiagentensystems")
    p.add_argument("--liste", action="store_true", help="verfuegbare Dokumente zeigen")
    p.add_argument("--szenario", help="Szenario-Nummer (1,2,3,4,5) oder Dateiname")
    p.add_argument("--alle", action="store_true", help="alle Szenarien nacheinander")
    p.add_argument("--audit", action="store_true", help="Audit-Trail ausgeben")
    p.add_argument("--check", action="store_true",
                   help="Modell-Bereitstellung pruefen (Ollama-Verbindung/Modelle)")
    p.add_argument("--pruefer", default=DEFAULT_APPROVER, help="UPN fuer Freigaben")
    p.add_argument("--entscheidung", default="freigegeben",
                   choices=["freigegeben", "verworfen"])
    p.add_argument("--interaktiv", action="store_true", help="Freigaben abfragen")
    args = p.parse_args()

    if not args.check:
        try:
            ensure_configured_runtime()
        except FileNotFoundError as error:
            sys.exit(str(error))

    if args.liste:
        return list_documents()
    if args.audit:
        return show_audit()
    if args.check:
        sys.exit(0 if check_models() else 1)

    docs = _manifest()
    if args.alle:
        for d in docs:
            run_case(d, approver=args.pruefer, decision=args.entscheidung,
                     interactive=args.interaktiv)
        return
    if not args.szenario:
        return p.print_help()

    matches = [d for d in docs
               if d["scenario"].startswith(args.szenario) or d["filename"] == args.szenario]
    if not matches:
        sys.exit(f"Kein Dokument zu {args.szenario!r}. `--liste` zeigt alle.")

    # Scenario 5 ends at the AD check and needs no model -- the governance
    # demo should not fail just because no Ollama instance is available.
    needs_model = any(d["scenario"] != "5_ad_check_verweigert" for d in matches)
    if needs_model and not check_models():
        print("\nHinweis: Szenario 5 (Governance-Demo) laeuft auch ohne Modell:")
        print("  python demo.py --szenario 5")
        sys.exit(1)

    for d in matches:
        run_case(d, approver=args.pruefer, decision=args.entscheidung,
                 interactive=args.interaktiv)


if __name__ == "__main__":
    main()
