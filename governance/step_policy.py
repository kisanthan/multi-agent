"""Thesis tables 12, 13, 19b: deterministic, closed-world step contracts."""
from dataclasses import dataclass
import sqlite3
from agent_registry import get_config
from governance import ad

POLICY_VERSION = "THESIS-20260914-v2"


@dataclass(frozen=True)
class StepPolicy:
    process: str
    step: str
    component: str
    action: str
    tool: str
    target: str
    level: int
    reversible: bool
    oversight: str
    approval: str
    data_class: str = "internal_financial"
    purpose: str = "document_processing"
    audit_required: bool = True
    version: str = POLICY_VERSION


POLICIES = {
    ("shared", "reader"): StepPolicy("shared", "reader", "reader", "dokument_einspeisen", "reader.pdf", "local", 1, True, "on_loop", "never"),
    ("shared", "klassifikation"): StepPolicy("shared", "klassifikation", "klassifikation", "belegart_bestimmen", "model.local", "local", 2, True, "proposal_only", "before_effect"),
    ("A", "extraktion_zahlung"): StepPolicy("A", "extraktion_zahlung", "extraktion_zahlung", "felder_extrahieren", "model.local", "local", 2, True, "proposal_only", "before_effect"),
    ("B", "extraktion_rechnung"): StepPolicy("B", "extraktion_rechnung", "extraktion_rechnung", "felder_extrahieren", "model.local", "local", 2, True, "proposal_only", "before_effect"),
    ("A", "abgleich"): StepPolicy("A", "abgleich", "abgleich", "nummer_abgleichen", "invoices.read", "local", 1, True, "on_loop", "never"),
    ("B", "kostenstelle"): StepPolicy("B", "kostenstelle", "kostenstelle", "kostenstelle_zuordnen", "cost_centers.read", "local", 1, True, "on_loop", "never"),
    ("A", "buchung"): StepPolicy("A", "buchung", "buchung", "zahlung_verbuchen", "navision.book", "navision", 4, False, "in_loop", "always"),
    ("B", "elo"): StepPolicy("B", "elo", "elo", "dokument_archivieren", "elo.archive", "elo", 3, True, "on_loop", "exception"),
}


class PolicyDenied(PermissionError):
    pass


def evaluate(con: sqlite3.Connection, request: dict) -> StepPolicy:
    required = {"case_id", "process", "step", "component", "action", "tool", "data_class",
                "purpose", "level", "reversible", "oversight", "audit_required"}
    if not required <= request.keys() or any(request[k] is None for k in required):
        raise PolicyDenied("default_deny: Pflichtattribute fehlen.")
    if not request["case_id"]:
        raise PolicyDenied("default_deny: Vorgangsreferenz fehlt.")
    p = POLICIES.get((request["process"], request["step"]))
    if p is None:
        raise PolicyDenied("default_deny: Prozessschritt nicht registriert.")
    for name in required - {"case_id", "process", "step"}:
        if request[name] != getattr(p, name):
            raise PolicyDenied(f"step_policy: Unzulässiges Attribut {name}.")
    cfg = get_config(p.component)
    if not cfg.active or not cfg.sponsor:
        raise PolicyDenied("identity: Dienst gesperrt oder ohne Sponsor.")
    if p.tool not in cfg.allowed_tools or p.data_class not in cfg.data_classes:
        raise PolicyDenied("least_privilege: Werkzeug oder Datenklasse nicht freigegeben.")
    if p.level > (cfg.autonomy_level or 1) or (p.level >= 3 and not cfg.can_write):
        raise PolicyDenied("least_privilege: Rollenmaximum unterschritten.")
    if p.process != "shared" and p.process not in cfg.processes:
        raise PolicyDenied("least_privilege: Prozess nicht freigegeben.")
    # A stronger runtime registry cannot silently remove required human oversight.
    from agent_registry import OversightMode
    if p.approval == "always" and cfg.oversight is not OversightMode.HUMAN_IN_THE_LOOP:
        raise PolicyDenied("oversight: Erforderliche Aufsicht fehlt.")
    if con.execute("SELECT 1 FROM policy_overrides WHERE policy_version=? AND disabled=1", (p.version,)).fetchone():
        raise PolicyDenied("policy_revoked: Regelversion deaktiviert.")
    return p


def check(con: sqlite3.Connection, process: str, step: str, case_id: str) -> StepPolicy:
    from dataclasses import asdict
    p = POLICIES.get((process, step))
    if not p:
        raise PolicyDenied("default_deny: Unbekannter Schritt.")
    return evaluate(con, {**asdict(p), "case_id": case_id})
