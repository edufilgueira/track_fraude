from __future__ import annotations

import sys
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


@pytest.mark.skipif(sys.platform == "win32", reason="symlink requer privilégio no Windows")
def test_resolve_worker_python_keeps_venv_symlink_path(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    venv_bin = root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (root / "src" / "track_fraude").mkdir(parents=True)
    (root / "src" / "track_fraude" / "__init__.py").write_text("", encoding="utf-8")

    system_python = tmp_path / "usr" / "bin" / "python3.14"
    system_python.parent.mkdir(parents=True)
    system_python.write_text("", encoding="utf-8")

    venv_python = venv_bin / "python"
    venv_python.symlink_to(system_python)

    def fake_validate(python: Path, *, project_root: Path) -> bool:
        return python == venv_python

    monkeypatch.setattr(
        "server.services.worker_python._validate_worker_python",
        fake_validate,
    )
    monkeypatch.setattr("server.services.worker_python.sys.platform", "linux")

    resolved = resolve_worker_python(project_root=root, configured=venv_python)
    assert resolved == venv_python
    assert resolved.resolve() == system_python.resolve()
