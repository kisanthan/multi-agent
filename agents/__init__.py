"""Domain agents.

`shared/` holds what genuinely serves both processes (the extraction
schemas and the classification & extraction agent). `payment_confirmation/`
and `incoming_invoice/` hold each process's own agents -- reconciliation
and booking for process A, cost-center assignment and archiving for
process B.
"""
