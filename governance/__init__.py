"""Deterministic governance: no language model, no exception.

`ad.py` (AD group membership), `policy.py` (write-action approval rules),
`audit.py` (the hash-chained, append-only trail). Every decision here is a
plain function call, reproducible in a unit test without any model --
`tests/test_layer_boundaries.py` enforces that no module in this package
can even import one.
"""
