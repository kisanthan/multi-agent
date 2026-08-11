"""Synthetic test data: generator and SQLite schema.

`generate.py` is the only thing run directly (`python -m data.generate`);
everything it produces (`stammdaten.db`, `checkpoints.sqlite`, `eingang/`,
`manifest.json`) is seed-fixed and reproducible, and lives in this
directory without being committed.
"""
