from __future__ import annotations

from pathlib import Path

import pytest

from server.services.worker_python import resolve_worker_python


def test_resolve_worker_python_prefers_root_venv(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "src" / "track_fraude").mkdir(parents=True)
    (root / "src" / "track_fraude" / "__init__.py").write_text("", encoding="utf-8")

    worker = Path(r"C:\fake\worker\python.exe")

    def fake_validate(python: Path, *, project_root: Path) -> bool:
        return python == worker

    monkeypatch.setattr(
        "server.services.worker_python._validate_worker_python",
        fake_validate,
    )
    monkeypatch.setattr(
        "server.services.worker_python.sys.executable",
        str(tmp_path / "server-python.exe"),
    )

    resolved = resolve_worker_python(project_root=root, configured=worker)
    assert resolved == worker
