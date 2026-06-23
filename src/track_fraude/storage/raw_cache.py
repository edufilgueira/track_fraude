from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from track_fraude.storage.paths import RawScope, source_raw_root

RAW_CACHE_DIR_ENV = "TRACK_FRAUDE_RAW_CACHE_DIR"
RAW_ROOT_OVERRIDE_ENV = "TRACK_FRAUDE_RAW_ROOT"
WORKER_BUILD_ID = "raw-cache-v2"


def raw_cache_dir() -> Path | None:
    """Diretório base do cache local (ex.: /cache/raw no worker GPU)."""
    value = os.getenv(RAW_CACHE_DIR_ENV, "").strip()
    return Path(value) if value else None


def log_raw_cache_status(*, worker: bool = False) -> None:
    cache = raw_cache_dir()
    if cache is not None:
        print(
            f"raw cache: configurado ({WORKER_BUILD_ID}) cache_dir={cache}",
            flush=True,
        )
        return
    if worker:
        print(
            f"AVISO raw cache: {RAW_CACHE_DIR_ENV} não definido — "
            "vídeos serão lidos via NFS (lento). "
            "Rebuild worker + kubectl apply -f infra/k8s/worker-scaledjob.yaml",
            flush=True,
        )


def stage_raw_videos_if_configured(
    *,
    project_root: Path | str,
    group_code: str | None,
    store_id: str,
    date: str,
) -> Path | None:
    """Copia vídeos raw do NFS para disco local e ativa TRACK_FRAUDE_RAW_ROOT.

    Retorna o diretório de destino do dia ou None se staging desabilitado.
    """
    cache_base = raw_cache_dir()
    if cache_base is None:
        return None

    root = Path(project_root)
    scope = RawScope.from_config(
        source_raw_root(root),
        {"group_code": group_code or "default", "store_id": store_id},
    )
    source_day = scope.date_dir(date)
    if not source_day.is_dir():
        raise FileNotFoundError(f"Pasta raw não encontrada para staging: {source_day}")

    dest_day = cache_base / scope.group_code / scope.store_id / date
    existing_override = os.getenv(RAW_ROOT_OVERRIDE_ENV, "").strip()
    if existing_override and dest_day.is_dir() and any(dest_day.iterdir()):
        print(f"raw cache: reutilizando {dest_day} ({WORKER_BUILD_ID})", flush=True)
        return dest_day

    dest_day.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    if dest_day.exists():
        shutil.rmtree(dest_day)
    shutil.copytree(source_day, dest_day)

    file_count = sum(1 for path in dest_day.rglob("*") if path.is_file())
    total_bytes = sum(path.stat().st_size for path in dest_day.rglob("*") if path.is_file())
    elapsed = time.perf_counter() - started

    os.environ[RAW_ROOT_OVERRIDE_ENV] = str(cache_base)
    print(
        f"raw cache: {source_day} -> {dest_day} | "
        f"{file_count} arquivo(s), {total_bytes / (1024 * 1024):.1f} MB em {elapsed:.2f}s "
        f"({WORKER_BUILD_ID})",
        flush=True,
    )
    return dest_day


def raw_root_override_env() -> dict[str, str]:
    """Env vars a repassar aos subprocessos do pipeline."""
    override = os.getenv(RAW_ROOT_OVERRIDE_ENV, "").strip()
    if not override:
        return {}
    return {RAW_ROOT_OVERRIDE_ENV: override}
