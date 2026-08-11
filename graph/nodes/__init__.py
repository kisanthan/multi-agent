"""Graph node functions, one module per process plus a shared one.

`shared.py` holds the common intake stretch (reader, classification,
orchestrator routing) and the helpers every node uses.
`payment_confirmation.py` and `incoming_invoice.py` hold process A's and
process B's own nodes. `graph/workflow.py` imports all three modules and
wires them into the single compiled graph -- it does not define any node
itself.
"""
