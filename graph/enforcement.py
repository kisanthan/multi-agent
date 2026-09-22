"""Enforce each registered graph step before its function runs."""
from governance import control
from governance.audit import Decision, log_entry
from governance.step_policy import PolicyDenied
from graph.nodes.shared import connection, case_reference, note
from contracts import CaseOutcome


def guarded(function, process: str, step: str):
    def execute(state):
        con = connection()
        try:
            control.authorize_read(con, state.get("case_id"), process, step, state.get("actor"))
            log_entry(con, actor=state["actor"], agent=step, action="schritt_angefordert",
                      decision=Decision.ALLOWED, reason="Registrierter Übergang und StepPolicy geprüft.",
                      reference=case_reference(state), outcome="authorized",
                      policy_version=control.POLICY_VERSION)
            con.commit()
        except PolicyDenied as error:
            return {"completed": True, "outcome": CaseOutcome.CONTROL_BLOCKED.value,
                    "error": str(error), "log": note(state, step, str(error))}
        finally:
            con.close()
        return function(state)
    return execute
