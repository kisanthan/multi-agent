"""Agent code genuinely shared by both processes.

`schemas.py` (the Pydantic extraction schemas: `DocumentType`,
`Classification`) and `classification.py` (the classification & extraction
agent) sit here because neither belongs to one process more than the
other -- classification is what determines *which* process a case belongs
to, before that is even known. Everything that IS process-specific lives
under `agents/payment_confirmation/` or `agents/incoming_invoice/` instead.
"""
