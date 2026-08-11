"""In-process FastAPI stand-ins for the two target systems.

`navision.py` (ERP: books a payment, open -> paid) and `elo.py` (DMS:
tamper-evident archiving). Both are deliberately strict -- they check
their own business preconditions and log their own accept/reject
decisions, the way the real systems would, not a stub that accepts
everything.
"""
