"""Task-owned launcher for the local snapshot parse worker.

This file deliberately has a stable absolute path in the process command line so
the PowerShell supervisor can prove worker ownership without adopting another
project's bare ``python -m app.workers.log_parse_worker`` process.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


SNAPSHOT_DATABASE_URL = "postgresql+asyncpg://postgres@127.0.0.1:55432/sdk_prod_snapshot_20261018_001"
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"


def main() -> None:
    configured_database_url = os.environ.get("DATABASE_URL")
    if configured_database_url and configured_database_url != SNAPSHOT_DATABASE_URL:
        raise SystemExit("snapshot parse launcher refuses a non-snapshot DATABASE_URL")
    os.environ["DATABASE_URL"] = SNAPSHOT_DATABASE_URL
    os.environ.setdefault("DEBUG", "true")
    os.chdir(BACKEND_ROOT)
    sys.path.insert(0, str(BACKEND_ROOT))
    runpy.run_module("app.workers.log_parse_worker", run_name="__main__")


if __name__ == "__main__":
    main()
