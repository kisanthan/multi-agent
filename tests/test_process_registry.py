"""Pins process_registry.step_title() against a call site that -- by
design, per ui/pages/audit.py -- passes it an audit agent ID instead of a
graph node name.

`ui/pages/audit.py::_step_name` calls `step_title(agent_id)` because, for
every step but one, an agent's ID and its node name are the same string.
The one exception is process A's exception-case step: `node="klaerfall"`,
but `agent_id="buchung"` (see process_registry.py, process A's
`own_steps`) -- the same agent_id the "buchung" step itself carries.
`step_title()` matches by `.node`, so `step_title("buchung")` still
resolves to the "buchung" step ("Zahlung verbuchen"), not the "klaerfall"
step ("Bestätigung durch eine Person"), because "klaerfall"'s *node* is
"klaerfall", not "buchung".

This works today, but only as a coincidence of which field is matched --
not a guarantee. A tempting "fix" (a `step_title_for_agent()` that matches
by `.agent_id` instead) would break it: "klaerfall" comes before "buchung"
in process A's `own_steps`, so matching by agent_id would hit "klaerfall"
first and mislabel every booking log entry as an approval decision. This
test exists so that trap is caught here, in a small test, rather than in a
wrongly labeled audit row.
"""

from __future__ import annotations

import process_registry


def test_step_title_resolves_the_shared_booking_agent_id_correctly():
    """Pins ui/pages/audit.py::_step_name's exact call: step_title() given
    an *agent ID* ("buchung"), not a node name, still returns the booking
    step's title -- not the exception-case step's, even though both steps
    share this agent_id."""
    assert process_registry.step_title("buchung") == "Zahlung verbuchen"


def test_klaerfall_and_buchung_share_an_agent_id_but_not_a_node():
    """Documents the exact shape of the coincidence the test above relies
    on -- if this ever stops being true, the test above stops testing
    anything meaningful and ui/pages/audit.py would need a real fix, not
    just a pinning test."""
    config = process_registry.get_config("A")
    klaerfall = next(s for s in config.own_steps if s.node == "klaerfall")
    buchung = next(s for s in config.own_steps if s.node == "buchung")
    assert klaerfall.agent_id == buchung.agent_id == "buchung"
    assert klaerfall.node != buchung.node
