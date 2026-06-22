#!/usr/bin/env python3
"""Consome uma demanda RabbitMQ e executa um pipeline diário."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from track_fraude_core.db.pipeline_run_repository import PipelineRunRepository
from track_fraude_core.pipeline_queue import (
    PIPELINE_STATUS_CANCELLED,
    PipelineQueueMessage,
)
from track_fraude_core.subprocess_utils import TeeWriter, run_command_with_cancel


def _log_path(message: PipelineQueueMessage) -> Path:
    if message.log_path:
        path = Path(message.log_path)
        return path if path.is_absolute() else ROOT / path
    return ROOT / "data" / "logs" / f"pipeline_{message.store_db_id}_{message.date}_queued.log"


def _run_message(message: PipelineQueueMessage) -> int:
    db_target = os.getenv("TRACK_FRAUDE_DATABASE_URL", "").strip() or message.db_path
    repo = PipelineRunRepository(db_target)
    current = repo.get_run(message.run_id)
    if current is not None and current.status == PIPELINE_STATUS_CANCELLED:
        return 0

    log_path = _log_path(message)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-u", str(ROOT / "jobs" / "run_daily_pipeline.py"), *message.worker_args()]
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
    }
    with log_path.open("a", encoding="utf-8", buffering=1) as handle:
        handle.write(f"\n--- pipeline retirado da fila: run_id={message.run_id} ---\n")
        handle.write(" ".join(command) + "\n")
        handle.flush()
        tee = TeeWriter(handle, sys.stdout)
        should_cancel = lambda: _is_cancelled(repo, message.run_id)
        return run_command_with_cancel(
            command,
            cwd=str(ROOT),
            env=env,
            stdout=tee,
            should_cancel=should_cancel,
        )


def _is_cancelled(repo: PipelineRunRepository, run_id: int) -> bool:
    current = repo.get_run(run_id)
    return current is not None and current.status == PIPELINE_STATUS_CANCELLED


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker RabbitMQ de um pipeline.")
    parser.add_argument("--queue-url", default=os.getenv("PIPELINE_QUEUE_URL"), required=False)
    parser.add_argument(
        "--queue-name",
        default=os.getenv("PIPELINE_QUEUE_NAME", "track-fraude-pipelines"),
    )
    args = parser.parse_args()
    if not args.queue_url:
        raise SystemExit("Informe --queue-url ou PIPELINE_QUEUE_URL")

    try:
        import pika
    except ImportError as exc:
        raise SystemExit("pika não está instalado no worker") from exc

    connection = pika.BlockingConnection(pika.URLParameters(args.queue_url))
    try:
        channel = connection.channel()
        channel.queue_declare(queue=args.queue_name, durable=True)
        method, _properties, body = channel.basic_get(queue=args.queue_name, auto_ack=False)
        if method is None:
            return
        # Ack IMEDIATO + fecha a conexão antes de processar. O pipeline leva minutos
        # e o pika.BlockingConnection cairia por falta de heartbeat (a thread fica
        # bloqueada no subprocesso), fazendo a mensagem voltar à fila e reprocessar
        # em loop. O estado do run é rastreado no Postgres, então não precisamos da
        # conexão aberta durante o processamento.
        channel.basic_ack(delivery_tag=method.delivery_tag)
    finally:
        try:
            connection.close()
        except Exception:
            pass

    # Pipeline roda SEM conexão RabbitMQ aberta (evita StreamLostError no fim).
    message = PipelineQueueMessage.from_json(body)
    returncode = _run_message(message)
    if returncode != 0:
        raise SystemExit(returncode)


if __name__ == "__main__":
    main()
