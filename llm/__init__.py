"""Provider-neutral language-model access.

`client.py` chooses a model (Ollama or Anthropic) from an agent's risk
class and the deployment mode, and wraps the call behind one interface.
`extraction.py` adds schema validation with a bounded retry before
escalating to a human (risk R1). `preflight.py` checks whether the
configured models are actually reachable, without loading anything
itself.
"""
