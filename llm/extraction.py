"""Validated, structured extraction with retry and HITL escalation.

This module is the answer to risk R1 (docs/limitations.md): local models do not
reliably honor a supplied JSON schema -- for Ollama this is an open,
documented bug (ollama/ollama#15540, as of April 2026).

The countermeasure, however, is not a workaround but a claim of the thesis
in its own right: the model's unreliability is *caught* by a deterministic
layer instead of *promised away* by the model. If validation still fails
after the retry, nothing is guessed and no work continues with partial data
-- the case goes to a human. That makes a model failure an approval case,
not a silent data error.

No benefit of the doubt for the model: even the cloud response goes through
the same validation.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from config import ProfileId
from governance.audit import NO_REFERENCE, CaseReference, Decision, log_entry
from llm.client import LLMUnreachable, client_for

MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class ExtractionResult:
    """Result of one extraction attempt.

    `data is None` and `escalation is not None` are equivalent and mean:
    exception case. The caller must never access a field without first
    checking `succeeded`.
    """

    data: BaseModel | None
    attempts: int
    model: str
    provider: str
    escalation: str | None = None
    raw: str = ""
    profile_id: str = "legacy"
    configuration_revision: int = 1
    unreachable: bool = False

    @property
    def succeeded(self) -> bool:
        return self.data is not None


def _error_text(e: ValidationError) -> str:
    """Translates a Pydantic error into a correction instruction for the model."""
    lines = []
    for f in e.errors():
        path = ".".join(str(t) for t in f["loc"]) or "(Wurzel)"
        lines.append(f"- Feld {path}: {f['msg']}")
    return "\n".join(lines)


def extract(
    con: sqlite3.Connection,
    *,
    agent_id: str,
    actor: str,
    system: str,
    prompt: str,
    schema: type[BaseModel],
    reference: CaseReference = NO_REFERENCE,
    profile_id: ProfileId | str | None = None,
    profile_snapshot: dict[str, dict[str, str]] | None = None,
) -> ExtractionResult:
    """Calls the model and validates the response against `schema`.

    On a schema violation, exactly one follow-up attempt with the concrete
    validation error. Escalation follows after that -- no third attempt,
    because a model that fails the same schema twice does not understand
    the schema, and another pass only costs money and latency.
    """
    client, choice = client_for(
        agent_id, profile_id=profile_id, snapshot=profile_snapshot)
    current_prompt = prompt
    last_error = ""
    raw = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = client.ask_json(system=system, prompt=current_prompt, schema=schema)
        except LLMUnreachable as e:
            # Transport error: do not retry, make it visible instead.
            log_entry(
                con, actor=actor, agent=agent_id, action="llm_aufruf",
                decision=Decision.DENIED,
                reason=f"Modell nicht erreichbar: {e}",
                payload={"modell": choice.model_id, "anbieter": choice.provider,
                         "profil": choice.profile_id,
                         "konfigurationsrevision": choice.configuration_revision},
                reference=reference, outcome="modell_nicht_erreichbar",
            )
            con.commit()
            return ExtractionResult(
                None, attempt, choice.model_id, choice.provider,
                escalation=f"Modell nicht erreichbar: {e}",
                profile_id=choice.profile_id,
                configuration_revision=choice.configuration_revision,
                unreachable=True,
            )

        try:
            data = schema.model_validate_json(raw)
        except ValidationError as e:
            last_error = _error_text(e)
            log_entry(
                con, actor=actor, agent=agent_id, action="llm_schemaverletzung",
                decision=Decision.INFO,
                reason=f"Versuch {attempt}/{MAX_ATTEMPTS} verletzt das Schema.",
                payload={"modell": choice.model_id, "anbieter": choice.provider,
                         "profil": choice.profile_id,
                         "konfigurationsrevision": choice.configuration_revision,
                         "fehler": last_error},
                reference=reference, outcome="schemaverletzung",
            )
            con.commit()
            current_prompt = (
                f"{prompt}\n\n"
                f"Dein vorheriger Versuch war ungueltig:\n{raw}\n\n"
                f"Diese Felder waren falsch:\n{last_error}\n\n"
                "Antworte erneut, ausschliesslich mit gueltigem JSON nach dem Schema."
            )
            continue

        log_entry(
            con, actor=actor, agent=agent_id, action="llm_extraktion",
            decision=Decision.INFO,
            reason=f"Extraktion gelungen in Versuch {attempt}.",
            payload={"modell": choice.model_id, "anbieter": choice.provider,
                     "profil": choice.profile_id,
                     "konfigurationsrevision": choice.configuration_revision,
                     "ergebnis": json.loads(data.model_dump_json())},
            reference=reference, outcome=f"extrahiert (Versuch {attempt})",
        )
        con.commit()
        return ExtractionResult(
            data, attempt, choice.model_id, choice.provider, raw=raw,
            profile_id=choice.profile_id,
            configuration_revision=choice.configuration_revision,
        )

    # Both attempts failed -> exception case instead of guessing.
    escalation = (
        f"Das Modell {choice.model_id} hat das Schema in {MAX_ATTEMPTS} Versuchen "
        f"nicht eingehalten. Letzte Fehler:\n{last_error}"
    )
    log_entry(
        con, actor=actor, agent=agent_id, action="llm_eskalation",
        decision=Decision.DENIED, reason=escalation,
        payload={"modell": choice.model_id, "anbieter": choice.provider,
                 "profil": choice.profile_id,
                 "konfigurationsrevision": choice.configuration_revision,
                 "roh": raw[:2000]},
        reference=reference, outcome="eskaliert",
    )
    con.commit()
    return ExtractionResult(
        None, MAX_ATTEMPTS, choice.model_id, choice.provider,
        escalation=escalation, raw=raw, profile_id=choice.profile_id,
        configuration_revision=choice.configuration_revision,
    )
