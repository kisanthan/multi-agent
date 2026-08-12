"""Synthetic test data: generator and SQLite schema.

`generate.py` is the only thing run directly (`python -m data.generate`);
everything it produces (`masterdata.db`, `checkpoints.sqlite`, `inbox/`,
`manifest.json`) is seed-fixed and reproducible, and lives in this
directory without being committed.
"""
