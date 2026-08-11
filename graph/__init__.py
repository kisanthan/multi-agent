"""The LangGraph wiring: one compiled graph for both processes.

`workflow.py` builds and compiles it; `state.py` declares the shared state
schema; `cases.py` derives the case list and business status from the
checkpoint; `effects.py` reads what a completed case actually did in the
target systems. The graph's own node functions live one level down, in
`graph/nodes/`.
"""
