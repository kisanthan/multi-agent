"""Tests for installing immutable demo seeds into writable runtime paths."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from data.bootstrap import DEFAULT_BUNDLE, SeedBundle, ensure_runtime


def _bundle(tmp_path: Path) -> SeedBundle:
    seed = tmp_path / "seeds"
    pdfs = seed / "pdfs"
    pdfs.mkdir(parents=True)
    (seed / "masterdata.seed.db").write_bytes(b"seed-db")
    (seed / "manifest.json").write_text('[{"demo": true}]', encoding="utf-8")
    (pdfs / "example.pdf").write_bytes(b"%PDF-demo")
    return SeedBundle(
        database=seed / "masterdata.seed.db",
        manifest=seed / "manifest.json",
        pdfs=pdfs,
    )


def test_missing_runtime_is_installed_from_seed_bundle(tmp_path):
    bundle = _bundle(tmp_path)
    runtime = tmp_path / "runtime"

    changed = ensure_runtime(
        bundle=bundle,
        database=runtime / "masterdata.db",
        manifest=runtime / "manifest.json",
        inbox=runtime / "inbox",
    )

    assert set(changed) == {"database", "manifest", "example.pdf"}
    assert (runtime / "masterdata.db").read_bytes() == b"seed-db"
    assert (runtime / "manifest.json").read_text(encoding="utf-8") == '[{"demo": true}]'
    assert (runtime / "inbox" / "example.pdf").read_bytes() == b"%PDF-demo"


def test_existing_runtime_data_is_never_overwritten_by_default(tmp_path):
    bundle = _bundle(tmp_path)
    runtime = tmp_path / "runtime"
    inbox = runtime / "inbox"
    inbox.mkdir(parents=True)
    (runtime / "masterdata.db").write_bytes(b"changed-db")
    (runtime / "manifest.json").write_text("changed", encoding="utf-8")
    (inbox / "example.pdf").write_bytes(b"changed-pdf")

    changed = ensure_runtime(
        bundle=bundle,
        database=runtime / "masterdata.db",
        manifest=runtime / "manifest.json",
        inbox=inbox,
    )

    assert changed == []
    assert (runtime / "masterdata.db").read_bytes() == b"changed-db"
    assert (runtime / "manifest.json").read_text(encoding="utf-8") == "changed"
    assert (inbox / "example.pdf").read_bytes() == b"changed-pdf"


def test_force_reinstalls_only_the_canonical_seed_files(tmp_path):
    bundle = _bundle(tmp_path)
    runtime = tmp_path / "runtime"
    inbox = runtime / "inbox"
    upload = inbox / "upload-123" / "own.pdf"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"user-upload")
    (runtime / "masterdata.db").write_bytes(b"changed-db")
    (runtime / "manifest.json").write_text("changed", encoding="utf-8")
    (inbox / "example.pdf").write_bytes(b"changed-pdf")

    ensure_runtime(
        bundle=bundle,
        database=runtime / "masterdata.db",
        manifest=runtime / "manifest.json",
        inbox=inbox,
        force=True,
    )

    assert (runtime / "masterdata.db").read_bytes() == b"seed-db"
    assert (inbox / "example.pdf").read_bytes() == b"%PDF-demo"
    assert upload.read_bytes() == b"user-upload"


def test_repository_seed_bundle_is_complete_and_pristine():
    assert DEFAULT_BUNDLE.missing() == []

    manifest = json.loads(DEFAULT_BUNDLE.manifest.read_text(encoding="utf-8"))
    pdf_names = {path.name for path in DEFAULT_BUNDLE.pdfs.glob("*.pdf")}
    assert pdf_names == {document["filename"] for document in manifest}

    con = sqlite3.connect(DEFAULT_BUNDLE.database)
    try:
        assert con.execute("SELECT count(*) FROM invoices").fetchone()[0] == 50
        assert con.execute(
            "SELECT count(*) FROM invoices WHERE status = 'offen'"
        ).fetchone()[0] == 50
        assert con.execute("SELECT count(*) FROM audit").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM uploads").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM archive").fetchone()[0] == 0
    finally:
        con.close()
