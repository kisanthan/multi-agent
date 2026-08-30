"""Domain agents.

`shared/` holds what genuinely serves both processes (the document router
and shared schemas). `payment_confirmation/` and `incoming_invoice/` each
hold their own extraction agent and the deterministic downstream agents.
"""
