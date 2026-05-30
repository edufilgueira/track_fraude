from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from server.settings import PROJECT_ROOT


def _validate_worker_python(python: Path, *, project_root: Path) -> bool:
    if not python.is_file():
        return False
    try:
        result = subprocess.run(
            [
                str(python),
                "-c",
                "import pyarrow; import track_fraude",
            ],
            capture_output=True,
            timeout=20,
            cwd=str(project_root),
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def resolve_worker_python(
    *,
    project_root: Path | None = None,
    configured: Path | str | None = None,
) -> Path:
    """Python com track-fraude + pyarrow (worker), não o venv mínimo do painel."""
    root = Path(project_root) if project_root else PROJECT_ROOT

    candidates: list[Path] = []
    if configured:
        configured_path = Path(configured)
        if not configured_path.is_absolute():
            configured_path = (root / configured_path).resolve()
        candidates.append(configured_path)

    if sys.platform == "win32":
        candidates.append(root / ".venv" / "Scripts" / "python.exe")
    else:
        candidates.append(root / ".venv" / "bin" / "python")

    candidates.append(Path(sys.executable))

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if _validate_worker_python(candidate, project_root=root):
            return candidate.resolve()

    raise RuntimeError(
        "Python do worker não encontrado (falta pyarrow/track_fraude). "
        "Na raiz do projeto execute: "
        "python -m venv .venv && .venv\\Scripts\\activate && "
        'pip install -e ".[track]"'
    )
