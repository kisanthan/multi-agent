"""The `.env` guard: a key no setting reads must not pass silently.

The failure this pins actually happened here. When the project's German
identifiers were renamed to English, `.env.example` was translated with
them -- but `.env` is gitignored, so every existing working copy kept the
old names. Pydantic matched none of them, `extra="ignore"` swallowed all
six, and every value fell back to the default in `config.py` while the file
on disk still looked like the configuration in force. The one key whose
value differed from its default (`OLLAMA_MODELL_VISION`) then pointed the
classification agent at a model that was never loaded, and the symptom
surfaced three layers away as a preflight error about model provisioning.

Hence the two halves of this file: that the guard fires, and that
`RENAMED_KEYS` cannot itself go stale the way the `.env` did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import (
    RENAMED_KEYS,
    Settings,
    UnknownSettingError,
    _env_file_keys,
    check_env_file,
)

KNOWN = {f.upper() for f in Settings.model_fields}


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


# ------------------------------------------------------------ The guard fires

def test_renamed_key_is_refused_and_names_its_replacement(tmp_path):
    """The exact regression: the old German name, silently ignored before."""
    with pytest.raises(UnknownSettingError) as e:
        check_env_file(_write(tmp_path, "OLLAMA_MODELL_VISION=qwen3:8b\n"), KNOWN)

    message = str(e.value)
    assert "OLLAMA_MODELL_VISION" in message
    # Naming the replacement is the whole reason this is not `extra="forbid"`.
    assert "OLLAMA_MODEL_VISION" in message


def test_every_renamed_key_is_recognised(tmp_path):
    """Not just the one that bit us -- all six of them."""
    body = "".join(f"{old}=x\n" for old in RENAMED_KEYS)

    with pytest.raises(UnknownSettingError) as e:
        check_env_file(_write(tmp_path, body), KNOWN)

    message = str(e.value)
    for old, new in RENAMED_KEYS.items():
        assert old in message
        assert new in message


def test_an_unrelated_unknown_key_is_refused_without_a_hint(tmp_path):
    """No entry in RENAMED_KEYS means no guess -- the key is still refused,
    but the message does not invent a replacement for it."""
    with pytest.raises(UnknownSettingError) as e:
        check_env_file(_write(tmp_path, "VOELLIG_UNBEKANNT=1\n"), KNOWN)

    assert "VOELLIG_UNBEKANNT" in str(e.value)
    assert "heisst jetzt" not in str(e.value)


def test_the_shipped_example_passes_its_own_guard():
    """`.env.example` is what the README tells people to copy. If it did not
    satisfy the guard, following the setup instructions would fail."""
    example = Path(__file__).parent.parent / ".env.example"

    check_env_file(example, KNOWN)  # must not raise


def test_a_valid_file_and_a_missing_file_both_pass(tmp_path):
    check_env_file(_write(tmp_path, "MODEL_MODE=lokal\nOLLAMA_MODEL_SMALL=qwen3:8b\n"),
                   KNOWN)
    check_env_file(tmp_path / "does-not-exist", KNOWN)


def test_lower_case_keys_are_accepted(tmp_path):
    """Pydantic matches environment names case-insensitively, so the guard
    must not refuse a spelling that would in fact have worked."""
    check_env_file(_write(tmp_path, "model_mode=lokal\n"), KNOWN)


# ------------------------------------------------------------ The small parser

def test_comments_blank_lines_and_export_are_not_keys(tmp_path):
    path = _write(tmp_path, "\n".join([
        "# MODELL_MODUS=lokal      <- a comment, not a setting",
        "",
        "   ",
        "export MODEL_MODE=lokal",
        "OLLAMA_BASE_URL=http://localhost:11434",
        "# trailing comment",
    ]) + "\n")

    assert _env_file_keys(path) == ["MODEL_MODE", "OLLAMA_BASE_URL"]


def test_a_value_containing_an_equals_sign_stays_in_the_value(tmp_path):
    """Only the first `=` separates; an URL or a key with padding must not
    be mistaken for a second assignment."""
    path = _write(tmp_path, "ANTHROPIC_API_KEY=abc==\nOLLAMA_BASE_URL=http://h:11434/x?a=b\n")

    assert _env_file_keys(path) == ["ANTHROPIC_API_KEY", "OLLAMA_BASE_URL"]


# --------------------------------------------- The map cannot itself go stale

def test_renamed_keys_point_at_real_settings():
    """Every replacement this promises must actually exist.

    Without this, the rename map could drift exactly the way `.env` did --
    and the error message would then confidently name a key that is just as
    dead as the one it replaces.
    """
    wrong = {old: new for old, new in RENAMED_KEYS.items() if new not in KNOWN}

    assert not wrong, (
        f"RENAMED_KEYS promises replacements that are not Settings fields: "
        f"{wrong}. Either the field was renamed again, or the map is wrong."
    )


def test_no_renamed_key_is_still_a_live_setting():
    """The reverse: an old name that became valid again would make the guard
    refuse a file that works."""
    live = [old for old in RENAMED_KEYS if old in KNOWN]

    assert not live, f"RENAMED_KEYS lists names that are live settings: {live}"
