from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from server.dependencies import get_pipeline_run_repo, get_settings
from server.services.video_storage import format_date_br, list_raw_import_dates
from server.services.worker_python import resolve_worker_python

_lock = threading.Lock()
_running: dict[int, subprocess.Popen] = {}


def _log_path(project_root: Path, store_db_id: int, date: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return (
        project_root
        / "data"
        / "logs"
        / f"pipeline_{store_db_id}_{date}_{stamp}.log"
    )


def _terminate_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def _watch_process(store_db_id: int, proc: subprocess.Popen, run_id: int) -> None:
    proc.wait()
    with _lock:
        _running.pop(store_db_id, None)
    repo = get_pipeline_run_repo()
    if repo.get_running_for_store(store_db_id) is not None:
        repo.finish_run(run_id, ok=False)


def is_store_running_locally(store_db_id: int) -> bool:
    with _lock:
        proc = _running.get(store_db_id)
        if proc is None:
            return False
        if proc.poll() is not None:
            _running.pop(store_db_id, None)
            return False
        return True


def start_daily_pipeline(
    *,
    project_root: Path,
    store_db_id: int,
    group_code: str,
    store_id: str,
    date: str,
) -> int:
    repo = get_pipeline_run_repo()
    if repo.is_store_running(store_db_id) or is_store_running_locally(store_db_id):
        raise RuntimeError("Pipeline já em execução para esta loja")

    raw_dates = list_raw_import_dates(group_code=group_code, store_id=store_id)
    if date not in raw_dates:
        raise FileNotFoundError(
            f"Nenhum vídeo importado em data/raw/{group_code}/{store_id}/{date}/"
        )

    settings = get_settings()
    worker_python = resolve_worker_python(
        project_root=project_root,
        configured=settings.pipeline_python,
    )

    run_id = repo.start_run(store_db_id, date)

    db_path = str(settings.database_path)
    script = project_root / "jobs" / "run_daily_pipeline.py"
    command = [
        str(worker_python),
        str(script),
        "--date",
        date,
        "--store-id",
        store_id,
        "--group-code",
        group_code,
        "--db",
        db_path,
        "--run-id",
        str(run_id),
    ]

    log_file_path = _log_path(project_root, store_db_id, date)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_file_path.open("a", encoding="utf-8")
    log_handle.write(f"\n--- pipeline iniciado {datetime.now().isoformat()} ---\n")
    log_handle.write(f"python: {worker_python}\n")
    log_handle.flush()

    kwargs: dict = {
        "cwd": str(project_root),
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        log_handle.write(f"Falha ao iniciar subprocesso: {exc}\n")
        log_handle.close()
        repo.cancel_run(run_id)
        raise RuntimeError(f"Não foi possível iniciar o pipeline: {exc}") from exc

    with _lock:
        _running[store_db_id] = proc

    watcher = threading.Thread(
        target=_watch_process,
        args=(store_db_id, proc, run_id),
        daemon=True,
    )
    watcher.start()
    return run_id


def cancel_daily_pipeline(*, store_db_id: int) -> bool:
    repo = get_pipeline_run_repo()
    run = repo.get_running_for_store(store_db_id)
    cancelled = False

    with _lock:
        proc = _running.get(store_db_id)
        if proc is not None and proc.poll() is None:
            _terminate_process(proc)
            _running.pop(store_db_id, None)
            cancelled = True

    if run is not None:
        repo.cancel_run(run.id)
        cancelled = True

    return cancelled


def raw_dates_payload(*, group_code: str, store_id: str) -> list[dict[str, str]]:
    return [
        {"id": item, "label": format_date_br(item)}
        for item in list_raw_import_dates(group_code=group_code, store_id=store_id)
    ]
