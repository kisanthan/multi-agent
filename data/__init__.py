"""Synthetic demo data, runtime bootstrap, generator and SQLite schema.

``data/demo`` contains the versioned immutable bundle. ``bootstrap.py``
installs writable runtime copies; ``generate.py`` reproducibly rebuilds
either the runtime files or, with ``--seed-bundle``, the tracked seeds.
"""
