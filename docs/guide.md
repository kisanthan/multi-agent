# Operator's guide

Step-by-step guide for setting up, running, and configuring the prototype.
The README covers the same ground more tersely and links here for the
details; this document adds nothing architectural -- for that, see
[architecture.md](architecture.md) and [limitations.md](limitations.md).

## 1. Prerequisites

- Python 3.12+ (tested on 3.14).
- For local models: [Ollama](https://ollama.com), running as a service or
  reachable over the network.
- For cloud models: an Anthropic API key. Not needed for `MODEL_MODE=lokal`
  (the default).

## 2. Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m data.generate        # synthetic master data + PDFs
```

`.env` is where every runtime switch lives: amount tolerance, model
provisioning, which PDF parser, and the two mock target-system URLs. The
prototype reads it once at startup (`config.py`); a changed `.env` needs a
restart to take effect. The one exception is per-agent model overrides --
see section 4 below, which take effect immediately, no restart needed.

## 3. Running it

Start the two target-system mocks (needed for any scenario that writes):

```bash
.venv/bin/uvicorn mocks.navision:app --port 8001 &
.venv/bin/uvicorn mocks.elo:app --port 8002 &
```

Then either the CLI:

```bash
.venv/bin/python demo.py --check      # is the model provisioning ready?
.venv/bin/python demo.py --liste      # all documents + expectations
.venv/bin/python demo.py --szenario 1 # run one scenario
.venv/bin/python demo.py --alle       # all five in sequence
```

or the UI:

```bash
.venv/bin/streamlit run ui/app.py
```

The UI's navigation follows the question a user currently has -- upload,
history, the two process views, the audit trail ("Protokoll" / "Record"),
the architecture view, and the model configuration described next. A single
run takes one to three minutes with a local model; approvals from a second
browser tab work independently, because the case state lives in the
LangGraph checkpoint, not in the tab.

The topmost control in the sidebar switches the interface between **Deutsch**
and **English**; it takes effect immediately, including the navigation
itself. What was *recorded* -- the run log's entries and the audit trail's
reasons and outcomes -- deliberately stays in the language it was written
in, so an exported trail reads the same regardless of who was looking at
the screen. Adding a third language means one more file in `ui/locales/`
and one more entry in `ui/shared/i18n.py::LANGUAGES`; `tests/test_i18n.py`
then reports every key that file is still missing.

## 4. Configuring AI models per agent

Every step in the workflow that calls a language model at all -- routing
(`orchestrator`), classification & extraction (`klassifikation`, shared by
both processes), booking (`buchung`, process A / payment confirmation), and
archiving (`elo`, process B / incoming invoice) -- can be pointed at a
specific model, live, from the UI's **KI-Modelle** page. This sits
deliberately apart from the **Architektur** page: Architektur reads the
static, risk-based default assignment (`agent_registry.py` -- a thesis
architectural claim); KI-Modelle lets an operator override that default per
agent, per instance, without editing `.env` or restarting the app.

**How the default is derived** (unchanged, see
[architecture.md](architecture.md)): each agent has a risk/model class in
`agent_registry.py` (none, local/small, vision-capable, frontier), and
`.env`'s `MODEL_MODE` decides how that class maps to a concrete
provider/model --

- `lokal` -- everything via Ollama.
- `cloud` -- everything via the Anthropic API.
- `hybrid` -- reading/uncritical roles stay local (data sovereignty),
  risk-bearing roles get a frontier cloud model.

**Overriding one agent:** open **KI-Modelle** in the UI. Each agent shows
its current effective provider and model id, and a small form: pick
"Lokal (Ollama)" or "Cloud (Anthropic)", enter the model id (any name your
Ollama instance has loaded, or any Anthropic model id), and press
"Speichern". The change is written to `data/model_overrides.json` and
applies to the very next call that agent makes -- no restart, and it also
takes effect for `demo.py` and `demo.py --check`, since both go through the
same `llm/client.py::choose_model` that the UI does. Press
"Auf Standard zurücksetzen" to drop the override and fall back to the
mode-derived default again.

An override always wins over `MODEL_MODE` for that one agent; every other
agent without an override keeps following the global mode as before. Every
override change is written to the audit trail ("Protokoll" page), the same
tamper-evident chain everything else in the system is recorded in.

**Local models still have to be loaded outside the app** -- overriding an
agent to a local model id it does not have loaded yet will fail with the
same actionable "model not loaded" message `llm/client.py` already
produces:

```bash
ollama serve
ollama pull <model>
```

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Keine Verbindung zu Ollama" | `OLLAMA_BASE_URL` unreachable | `ollama serve`, or fix the URL in `.env` |
| "Modell ... ist ... nicht geladen" | Model not pulled on that Ollama instance | `ollama pull <model>`, or point the agent at a model that is loaded (KI-Modelle page, or `OLLAMA_MODEL_SMALL`/`OLLAMA_MODEL_VISION` in `.env`) |
| "ANTHROPIC_API_KEY ist nicht gesetzt" | `MODEL_MODE=hybrid`/`cloud` (or a cloud override) without a key | Set `ANTHROPIC_API_KEY` in `.env`, or switch back to a local override/mode |
| `demo.py --check` reports "NICHT BEREIT" | Any of the above | Read its message list -- it names exactly which model is missing where |
