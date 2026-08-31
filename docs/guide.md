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
```

Synthetic PDFs, their manifest and a pristine SQLite database are already
versioned under `data/demo/`. On the first UI/CLI/mock access they are copied
atomically to the ignored runtime paths under `data/`. Existing runtime data
is never overwritten automatically.

Reset the writable runtime explicitly with `python -m data.generate`. After
an intentional change to the fixture definitions, maintainers update the
repository bundle with `python -m data.generate --seed-bundle`.

`.env` is where every runtime switch lives: amount tolerance, model
provisioning, which PDF parser, and the two mock target-system URLs. Changes
made on the **Agentenkonfiguration** page are validated, written atomically
and activated immediately without a restart.

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

The language control under **System → Einstellungen** switches the
interface between **Deutsch** and **English**; it
takes effect immediately, including the navigation itself. What was
*recorded* -- the run log's entries and the audit trail's
reasons and outcomes -- deliberately stays in the language it was written
in, so an exported trail reads the same regardless of who was looking at
the screen. Adding a third language means one more file in `ui/locales/`
and one more entry in `ui/shared/i18n.py::LANGUAGES`; `tests/test_i18n.py`
then reports every key that file is still missing.

The **Dunkelmodus / Dark mode** switch on the same page changes the whole
interface between a light and dark appearance for the current browser
session. Navigation, forms, cards, document upload, and process views all
use the same central theme.

## 4. Configuring AI models per agent

Open **System → Agentenkonfiguration**. The page has one independent area
for each real model call:

- **Document type detection** selects the shared router provider and model.
- **Payment confirmation** selects the payment-field extraction provider and model.
- **Incoming invoice** selects the invoice-field extraction provider and model.

In each area, first select Ollama, Google, Anthropic or OpenAI. Only the
parameters relevant to that provider are shown: the Ollama host address,
the cloud API key, or the supported account/workspace fields. Credentials
are central and reused when two profiles select the same provider.

Press **Check connection & load models** to make a non-billable model-list
request. The page then shows a connected/not-connected status and offers the
discovered models in a selector. A custom model id remains possible. Save the
agent configuration before running the separately labelled structured test;
that test performs a model call and may incur provider cost.

All changes are written to `.env`, revisioned and audited without secrets.
Cases already started retain their provider/model snapshot. `MODEL_MODE`
remains only as a backwards-compatible default until explicit profiles have
been saved.

**Local models still have to be loaded outside the app:**

```bash
ollama serve
ollama pull <model>
```

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Keine Verbindung zu Ollama" | `OLLAMA_BASE_URL` unreachable | `ollama serve`, or fix the URL in `.env` |
| "Modell ... ist ... nicht geladen" | Model not pulled on that Ollama instance | `ollama pull <model>`, then reload the model list on the Agentenkonfiguration page |
| "ANTHROPIC_API_KEY ist nicht gesetzt" | `MODEL_MODE=hybrid`/`cloud` (or a cloud override) without a key | Set `ANTHROPIC_API_KEY` in `.env`, or switch back to a local override/mode |
| `demo.py --check` reports "NICHT BEREIT" | Any of the above | Read its message list -- it names exactly which model is missing where |
