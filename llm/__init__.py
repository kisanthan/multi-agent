"""Provider-neutral language-model access.

`client.py` resolves the router, payment and invoice profiles and provides
adapters for Ollama, Google, Anthropic and OpenAI behind one interface.
`extraction.py` adds schema validation with a bounded retry before
escalating to a human (risk R1). `preflight.py` checks whether the
configured models are actually reachable, without loading anything
itself.
"""
