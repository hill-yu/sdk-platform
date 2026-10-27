"""Local admin utilities plus the repository-level migration scripts.

The backend test runner starts with ``backend`` on ``sys.path``. Extending
this package path keeps existing ``scripts.<migration>`` test imports pointed
at the repository-level scripts while allowing backend-only utilities here.
"""

from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[2] / "scripts"))
