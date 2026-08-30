"""Agent code genuinely shared by both processes.

`schemas.py` defines the structured contracts and `classification.py`
contains the shared document router. The router decides only *which*
process owns a case; process-specific extraction lives below
`agents/payment_confirmation/` and `agents/incoming_invoice/`.
"""
