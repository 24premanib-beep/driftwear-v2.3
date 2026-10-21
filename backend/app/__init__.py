"""DriftWear API package.

The ML engine lives in the top-level `ml/` package next to `backend/`. Docker sets
PYTHONPATH=/srv; for `uvicorn app.main:app` run from backend/ on a developer
machine, the repository root is added here so `import ml` works the same way.
"""
import sys
from pathlib import Path

__version__ = "2.3.0"

_REPO_ROOT = Path(__file__).resolve().parents[2]
if (_REPO_ROOT / "ml" / "__init__.py").exists() and str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))
