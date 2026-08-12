"""Pins the translation catalogs against the code that reads them.

Two failure modes are worth a test, because neither shows up as an
exception -- both show up as a blank or German label in an English
interface, in some corner of a page nobody opened during review:

1. A key added to one catalog and forgotten in the other.
2. A process, step, agent, or status added to a registry, whose German
   comes along for free (the registry *is* the German source, see
   `ui/shared/i18n.py`) but whose English does not exist anywhere.

The second is the one that actually happens: adding a third process is
meant to be one entry in `process_registry.py`, and nothing in that file
suggests a JSON file elsewhere also needs a line.

The split between the two is computed, not guessed by key prefix: keys like
`process.A.name` (derived from a registry) and `process.flow.footer` (plain
interface text) share a prefix but follow opposite rules.
"""

from __future__ import annotations

import pytest

import agent_registry
import process_registry
from agent_registry import AgentType, ModelClass, OversightMode
from graph.cases import Status
from ui.cases.process_views import SHARED_RESULT_TEXTS, all_views
from ui.shared import i18n
from ui.shared.formatting import LABELS

# The codes `ui/intake/intake.py::check` can return. Listed rather than
# derived: they are branches of a function, not entries in a table.
INTAKE_CODES = ("wrong_type", "no_extension", "empty", "too_large",
                "not_a_pdf", "duplicate", "ok")


@pytest.fixture(autouse=True)
def _german_again():
    """Every test leaves the language as it found it."""
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)


def _registry_keys() -> set[str]:
    """Keys whose German lives in a registry that the interface reads."""
    keys = set()
    for config in process_registry.all_processes():
        for attribute in ("name", "document_kind", "document_kind_plural",
                          "description", "target_system", "process_end"):
            keys.add(f"process.{config.key}.{attribute}")
        for step in config.steps:
            keys.add(f"step.{step.node}.title")
    for agent_id in agent_registry.REGISTRY:
        keys.add(f"agent.{agent_id}.name")
        keys.add(f"agent.{agent_id}.description")
    for status in Status:
        keys.add(f"status.{status.value}")
    for key in LABELS:
        keys.add(f"field.{key}")
    return keys


def _derived_keys() -> set[str]:
    """Every key whose German has a home outside `de.json`.

    Beyond the registries: the registry enums (their `.value` is the German
    original), the intake check's own wording, and the outcome sentences in
    `ui/cases/process_views/`.
    """
    keys = _registry_keys()
    for group, enum in (("type", AgentType), ("oversight", OversightMode),
                        ("model_class", ModelClass)):
        keys |= {f"enum.{group}.{member.value}" for member in enum}
    keys |= {f"intake.{code}" for code in INTAKE_CODES}

    outcomes = dict(SHARED_RESULT_TEXTS)
    for view in all_views():
        outcomes.update(view.result_texts)
    keys |= {f"result.{outcome}" for outcome in outcomes}
    return keys


def _chrome_keys(code: str) -> set[str]:
    return set(i18n.catalog(code)) - _derived_keys()


def test_every_language_has_a_catalog():
    for code in i18n.LANGUAGES:
        assert i18n.catalog(code), f"{code}.json is missing or empty"


@pytest.mark.parametrize(
    "code", [c for c in i18n.LANGUAGES if c != i18n.DEFAULT_LANGUAGE])
def test_interface_keys_are_identical_across_languages(code):
    """Interface text has no home outside the catalogs -- so every language
    must carry every key, or the missing one silently falls back to German."""
    reference = _chrome_keys(i18n.DEFAULT_LANGUAGE)
    missing = reference - _chrome_keys(code)
    extra = _chrome_keys(code) - reference

    assert not missing, f"{code}.json is missing: {sorted(missing)}"
    assert not extra, f"{code}.json has keys no other language has: {sorted(extra)}"


@pytest.mark.parametrize(
    "code", [c for c in i18n.LANGUAGES if c != i18n.DEFAULT_LANGUAGE])
def test_translations_cover_everything_the_registries_declare(code):
    """A third process must not silently stay German in the English UI."""
    missing = sorted(_derived_keys() - set(i18n.catalog(code)))

    assert not missing, (
        f"{code}.json does not translate: {missing}. A new process, step, "
        f"agent, status field, or outcome needs a line per language here."
    )


def test_german_is_never_duplicated_into_a_catalog():
    """The registries are the German source; `de.json` must not shadow them.

    Two copies of the same sentence drift, and the one in the JSON would
    win silently.
    """
    duplicated = sorted(_registry_keys() & set(i18n.catalog("de")))

    assert not duplicated, (
        f"de.json repeats text that already lives in a registry: "
        f"{duplicated}. German belongs in exactly one place."
    )


def test_unknown_key_falls_back_to_the_key_itself():
    """Visibly broken beats invisibly empty."""
    assert i18n.t("no.such.key") == "no.such.key"
    assert i18n.t("no.such.key", default="Fallback") == "Fallback"


def test_missing_english_key_falls_back_to_german():
    i18n.set_language("en")

    assert i18n.t("filter.search") == "Search"
    assert i18n.t("nope", default="Deutscher Text") == "Deutscher Text"


def test_switching_language_changes_what_the_registries_read_as():
    config = process_registry.get_config("A")

    assert i18n.process_text(config, "name") == "Zahlungsbestätigung"
    assert i18n.status_label(Status.COMPLETED) == "Abgeschlossen"
    assert i18n.step_title("buchung") == "Zahlung verbuchen"

    i18n.set_language("en")

    assert i18n.process_text(config, "name") == "Payment confirmation"
    assert i18n.status_label(Status.COMPLETED) == "Completed"
    assert i18n.step_title("buchung") == "Post the payment"


def test_set_language_works_without_a_running_app():
    """Outside a script run Streamlit hands out a throwaway session state --
    a switch that landed there would be discarded and `language()` would
    keep answering German. See `i18n._in_script_run`."""
    i18n.set_language("en")
    assert i18n.language() == "en"

    i18n.set_language("de")
    assert i18n.language() == "de"


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError):
        i18n.set_language("fr")


def test_number_and_date_formats_follow_the_language():
    """Translating the labels alone is not enough: '1.341,96' and
    '1,341.96' are different numbers to different readers."""
    from ui.shared import formatting

    assert formatting.format_euro(1341.96) == "1.341,96 €"
    assert formatting.date_only("2026-08-12T09:30:00") == "12.08.2026"

    i18n.set_language("en")

    assert formatting.format_euro(1341.96) == "€1,341.96"
    assert formatting.date_only("2026-08-12T09:30:00") == "2026-08-12"


def test_document_kind_plurals_exist_in_every_language():
    """German builds the plural by rule, English states it -- both must end
    up with a form for every process."""
    for code in i18n.LANGUAGES:
        i18n.set_language(code)
        plurals = i18n.document_kinds_plural()
        assert len(plurals) == len(process_registry.all_processes())
        assert all(plurals), f"{code} has an empty plural form"


def test_parameters_are_substituted():
    assert "5" in i18n.t("list.show_more", count=5)


def test_text_without_parameters_is_passed_through_unformatted():
    """A text containing braces must survive -- `t()` only formats when it
    is given something to substitute."""
    assert i18n.t("unknown.braces", default="a {brace} stays") == "a {brace} stays"
