"""Task-owned local CSV export worker launcher.

The launcher fixes both the snapshot database and local-only export directory;
it never sends export output to an external destination.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


SNAPSHOT_DATABASE_URL = "postgresql+asyncpg://postgres@127.0.0.1:55432/sdk_prod_snapshot_20261018_001"
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
EXPORT_ROOT = REPO_ROOT / ".local-run" / "exports"


def main() -> None:
    configured_database_url = os.environ.get("DATABASE_URL")
    if configured_database_url and configured_database_url != SNAPSHOT_DATABASE_URL:
        raise SystemExit("snapshot export launcher refuses a non-snapshot DATABASE_URL")
    os.environ["DATABASE_URL"] = SNAPSHOT_DATABASE_URL
    os.environ["LOG_EXPORT_DIR"] = str(EXPORT_ROOT)
    os.environ.setdefault("DEBUG", "true")
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    os.chdir(BACKEND_ROOT)
    sys.path.insert(0, str(BACKEND_ROOT))
    runpy.run_module("app.workers.log_export_worker", run_name="__main__")


if __name__ == "__main__":
    main()
