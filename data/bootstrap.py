"""Install versioned demo seeds into writable runtime locations.

The bundle under ``data/demo`` is immutable repository content.  The app,
CLI and mocks write only to copies under ``data/`` so a demonstration never
changes a tracked PDF or SQLite file.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent
DEMO_DIR = DATA_DIR / "demo"


@dataclass(frozen=True)
class SeedBundle:
    database: Path = DEMO_DIR / "masterdata.seed.db"
    manifest: Path = DEMO_DIR / "manifest.json"
    pdfs: Path = DEMO_DIR / "pdfs"

    def missing(self) -> list[Path]:
        required = [self.database, self.manifest, self.pdfs]
        missing = [path for path in required if not path.exists()]
        if self.pdfs.is_dir() and not any(self.pdfs.glob("*.pdf")):
            missing.append(self.pdfs / "*.pdf")
        return missing


DEFAULT_BUNDLE = SeedBundle()


def _atomic_copy(source: Path, target: Path) -> None:
    """Copy a seed without exposing a partially written runtime file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_runtime(
    *,
    database: Path,
    manifest: Path,
    inbox: Path,
    bundle: SeedBundle = DEFAULT_BUNDLE,
    force: bool = False,
) -> list[str]:
    """Install missing demo files and return the names that changed.

    Existing runtime state wins unless ``force`` is explicitly requested.
    Even a forced reinstall touches only canonical seed filenames; nested
    user-upload directories remain intact.
    """
    missing = bundle.missing()
    if missing:
        rendered = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Demo-Seed unvollständig: {rendered}")

    changed: list[str] = []
    for label, source, target in (
        ("database", bundle.database, database),
        ("manifest", bundle.manifest, manifest),
    ):
        if force or not target.exists():
            _atomic_copy(source, target)
            changed.append(label)

    inbox.mkdir(parents=True, exist_ok=True)
    for source in sorted(bundle.pdfs.glob("*.pdf")):
        target = inbox / source.name
        if force or not target.exists():
            _atomic_copy(source, target)
            changed.append(source.name)

    return changed


def ensure_configured_runtime(*, force: bool = False) -> list[str]:
    """Install seeds at the paths currently selected in ``config``."""
    import config

    changed = ensure_runtime(
        database=config.DB_PATH,
        manifest=config.MANIFEST_PATH,
        inbox=config.INTAKE_DIR,
        force=force,
    )
    from data.migrations import connect
    with connect(config.DB_PATH) as con:
        from governance.ad import ensure_configuration_seed
        from governance.identity import ensure_portal_identities
        ensure_configuration_seed(con)
        ensure_portal_identities(con)
    return changed
