from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from server.dependencies import get_pipeline_run_repo, get_settings
from server.services.atlas_client import AtlasPlatformClient, AtlasPlatformError
from server.services.pipeline_queue import PipelineQueuePublisher
from server.services.video_storage import format_date_br, list_raw_import_dates
from server.services.worker_python import resolve_worker_python
from track_fraude_core.pipeline_queue import PipelineQueueMessage

_lock = threading.Lock()
_running: dict[int, subprocess.Popen] = {}
_log_files: dict[int, Path] = {}
_log_handles: dict[int, object] = {}


def _close_log_handle(store_db_id: int) -> None:
    with _lock:
        handle = _log_handles.pop(store_db_id, None)
    if handle is None:
        return
    try:
        handle.flush()
    except OSError:
        pass
    try:
        handle.close()
    except OSError:
        pass


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
    _close_log_handle(store_db_id)
    with _lock:
        _running.pop(store_db_id, None)
    try:
        repo = get_pipeline_run_repo()
        if repo.get_running_for_store(store_db_id) is not None:
            repo.finish_run(run_id, ok=proc.returncode == 0)
    except sqlite3.OperationalError:
        pass


def _find_latest_log(project_root: Path, store_db_id: int) -> Path | None:
    logs_dir = project_root / "data" / "logs"
    if not logs_dir.is_dir():
        return None
    matches = sorted(
        logs_dir.glob(f"pipeline_{store_db_id}_*.log"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def _path_from_log_ref(project_root: Path, log_ref: str) -> Path:
    candidate = Path(log_ref)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate


def resolve_log_path(project_root: Path, store_db_id: int) -> Path | None:
    with _lock:
        tracked = _log_files.get(store_db_id)
    if tracked is not None and tracked.is_file():
        return tracked

    try:
        repo = get_pipeline_run_repo()
        run = repo.get_running_for_store(store_db_id) or repo.get_latest_run_for_store(
            store_db_id
        )
        if run and run.log_path:
            candidate = _path_from_log_ref(project_root, run.log_path)
            if candidate.is_file():
                return candidate
    except (sqlite3.OperationalError, OSError):
        pass

    return _find_latest_log(project_root, store_db_id)


def _is_store_running(store_db_id: int) -> bool:
    if is_store_running_locally(store_db_id):
        return True
    try:
        return get_pipeline_run_repo().is_store_running(store_db_id)
    except sqlite3.OperationalError:
        return is_store_running_locally(store_db_id)


def read_pipeline_log(
    *,
    project_root: Path,
    store_db_id: int,
    offset: int = 0,
) -> dict:
    running = _is_store_running(store_db_id)
    path = resolve_log_path(project_root, store_db_id)
    if path is None:
        return {
            "content": "",
            "offset": 0,
            "running": running,
            "has_log": False,
        }

    safe_offset = max(0, offset)
    try:
        log_path_display = path.relative_to(project_root).as_posix()
    except ValueError:
        log_path_display = path.as_posix()

    try:
        with path.open("rb") as handle:
            handle.seek(safe_offset)
            chunk = handle.read(128 * 1024)
            new_offset = safe_offset + len(chunk)
    except OSError as exc:
        return {
            "content": "",
            "offset": safe_offset,
            "running": running,
            "has_log": True,
            "log_path": log_path_display,
            "error": (
                "too_many_open_files"
                if getattr(exc, "errno", None) == 24
                else str(exc)
            ),
        }

    return {
        "content": chunk.decode("utf-8", errors="replace"),
        "offset": new_offset,
        "running": running,
        "has_log": True,
        "log_path": log_path_display,
    }


def is_store_running_locally(store_db_id: int) -> bool:
    with _lock:
        proc = _running.get(store_db_id)
        if proc is None:
            return False
        if proc.poll() is not None:
            _running.pop(store_db_id, None)
            return False
        return True


def list_running_store_ids_locally() -> list[int]:
    with _lock:
        active: list[int] = []
        for store_db_id, proc in list(_running.items()):
            if proc.poll() is None:
                active.append(store_db_id)
            else:
                _running.pop(store_db_id, None)
        return sorted(active)


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
    if settings.pipeline_mode == "queue":
        log_file_path = _log_path(project_root, store_db_id, date)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        run_id = repo.enqueue_run(
            store_db_id,
            date,
            log_path=log_file_path.relative_to(project_root).as_posix(),
        )
        message = PipelineQueueMessage(
            run_id=run_id,
            store_db_id=store_db_id,
            group_code=group_code,
            store_id=store_id,
            date=date,
            db_path=settings.database_dsn,
            log_path=str(log_file_path),
        )

        try:
            if settings.atlas_api_url:
                atlas_result = AtlasPlatformClient(
                    api_url=settings.atlas_api_url,
                    api_key=settings.atlas_api_key,
                ).create_job(workload="track-fraude", message=message)
                queue_name = settings.queue_name
                message_id = str(
                    atlas_result.get("rabbit_message_id")
                    or f"atlas-{atlas_result.get('id')}"
                )
            else:
                if not settings.queue_url:
                    repo.cancel_run(run_id)
                    raise RuntimeError(
                        "Configure atlas.api_url ou pipeline.queue_url para pipeline.mode=queue"
                    )
                result = PipelineQueuePublisher(
                    queue_url=settings.queue_url,
                    queue_name=settings.queue_name,
                ).publish(message)
                queue_name = result.queue_name
                message_id = result.message_id
        except AtlasPlatformError as exc:
            repo.cancel_run(run_id)
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            repo.cancel_run(run_id)
            raise RuntimeError(f"Falha ao publicar pipeline na fila: {exc}") from exc

        with log_file_path.open("a", encoding="utf-8") as log_handle:
            log_handle.write(f"\n--- pipeline enfileirado {datetime.now().isoformat()} ---\n")
            if settings.atlas_api_url:
                log_handle.write(f"atlas_job: {atlas_result.get('id')}\n")
            log_handle.write(f"queue: {queue_name}\n")
            log_handle.write(f"message_id: {message_id}\n")
            log_handle.flush()

        with _lock:
            _log_files[store_db_id] = log_file_path

        return run_id, log_file_path
    if settings.pipeline_mode != "local":
        raise RuntimeError(f"pipeline.mode inválido: {settings.pipeline_mode!r}")

    worker_python = resolve_worker_python(
        project_root=project_root,
        configured=settings.pipeline_python,
    )

    run_id = repo.start_run(store_db_id, date)

    db_path = settings.database_dsn
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

    _close_log_handle(store_db_id)

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
        "env": {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        },
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
        _log_files[store_db_id] = log_file_path
        _log_handles[store_db_id] = log_handle

    watcher = threading.Thread(
        target=_watch_process,
        args=(store_db_id, proc, run_id),
        daemon=True,
    )
    watcher.start()
    return run_id, log_file_path


def cancel_daily_pipeline(*, store_db_id: int) -> bool:
    cancelled = False

    with _lock:
        proc = _running.get(store_db_id)
        if proc is not None and proc.poll() is None:
            _terminate_process(proc)
            _running.pop(store_db_id, None)
            cancelled = True

    if cancelled:
        with _lock:
            handle = _log_handles.get(store_db_id)
        if handle is not None:
            try:
                handle.write(
                    f"\n--- cancelado pelo usuário {datetime.now().isoformat()} ---\n"
                )
                handle.flush()
            except OSError:
                pass
        _close_log_handle(store_db_id)

    try:
        repo = get_pipeline_run_repo()
        run = repo.get_running_for_store(store_db_id)
        if run is not None:
            repo.cancel_run(run.id)
            cancelled = True
    except sqlite3.OperationalError:
        if cancelled:
            return True

    return cancelled


def raw_dates_payload(*, group_code: str, store_id: str) -> list[dict[str, str]]:
    return [
        {"id": item, "label": format_date_br(item)}
        for item in list_raw_import_dates(group_code=group_code, store_id=store_id)
    ]
