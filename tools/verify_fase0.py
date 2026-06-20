#!/usr/bin/env python3
"""Verifica pré-requisitos da Fase 0 — base operacional Atlas / track_fraude."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ok(message: str) -> None:
    print(f"  OK  {message}")


def _fail(message: str) -> None:
    print(f"  FAIL  {message}")


def check_compose_file() -> bool:
    path = ROOT / "docker-compose.infra.yml"
    if not path.is_file():
        _fail(f"Arquivo ausente: {path}")
        return False
    text = path.read_text(encoding="utf-8")
    for service in ("registry", "rabbitmq", "postgres"):
        if f"{service}:" not in text:
            _fail(f"Serviço {service!r} não encontrado em docker-compose.infra.yml")
            return False
    _ok("docker-compose.infra.yml contém registry, rabbitmq e postgres")
    return True


def check_k8s_queue_mode() -> bool:
    path = ROOT / "infra" / "k8s" / "app-config.yaml"
    if not path.is_file():
        _fail(f"ConfigMap ausente: {path}")
        return False
    text = path.read_text(encoding="utf-8")
    ok = True
    if "mode: queue" not in text:
        _fail("app-config.yaml não define pipeline.mode: queue")
        ok = False
    else:
        _ok("app-config.yaml usa pipeline.mode: queue")
    if "backend: postgres" not in text:
        _fail("app-config.yaml não define database.backend: postgres")
        ok = False
    else:
        _ok("app-config.yaml usa Postgres")
    return ok


def check_worker_scaledjob() -> bool:
    path = ROOT / "infra" / "k8s" / "worker-scaledjob.yaml"
    if not path.is_file():
        _fail(f"ScaledJob ausente: {path}")
        return False
    text = path.read_text(encoding="utf-8")
    ok = True
    if "track-fraude-pipelines" not in text:
        _fail("ScaledJob não referencia fila track-fraude-pipelines")
        ok = False
    else:
        _ok("ScaledJob aponta para fila track-fraude-pipelines")
    if "TRACK_FRAUDE_DATABASE_URL" not in text:
        _fail("ScaledJob não injeta TRACK_FRAUDE_DATABASE_URL")
        ok = False
    else:
        _ok("ScaledJob injeta TRACK_FRAUDE_DATABASE_URL")
    return ok


def check_postgres(postgres_url: str) -> bool:
    try:
        import psycopg
    except ImportError:
        _fail('psycopg não instalado (pip install "psycopg[binary]>=3.1")')
        return False
    try:
        with psycopg.connect(postgres_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'groups'"
                )
                row = cur.fetchone()
        if row is None:
            _fail("Postgres acessível, mas tabela groups não existe (rode schema/migrate)")
            return False
        _ok(f"Postgres acessível e schema presente ({postgres_url})")
        return True
    except Exception as exc:
        _fail(f"Postgres inacessível: {exc}")
        return False


def _list_queue_names(api_url: str, user: str, password: str) -> set[str] | None:
    request = urllib.request.Request(api_url)
    credentials = f"{user}:{password}".encode("utf-8")
    import base64

    request.add_header("Authorization", "Basic " + base64.b64encode(credentials).decode("ascii"))
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    return {str(item.get("name")) for item in payload if isinstance(item, dict) and item.get("name")}


def _declare_queue(rabbitmq_url: str, queue_name: str) -> bool:
    try:
        import pika
    except ImportError:
        _fail("pika não instalado — pip install pika (para declarar fila)")
        return False
    try:
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        channel = connection.channel()
        channel.queue_declare(queue=queue_name, durable=True)
        connection.close()
        return True
    except Exception as exc:
        _fail(f"Não foi possível declarar fila {queue_name!r}: {exc}")
        return False


def check_rabbitmq_management(
    api_url: str,
    user: str,
    password: str,
    *,
    queue_name: str,
    rabbitmq_url: str,
    declare_missing: bool,
) -> bool:
    names = _list_queue_names(api_url, user, password)
    if names is None:
        _fail("RabbitMQ management API inacessível")
        return False

    if queue_name not in names:
        if not declare_missing:
            _fail(
                f"Fila {queue_name!r} não encontrada no RabbitMQ "
                "(será criada no primeiro Play ou use --declare-queue)"
            )
            return False
        print(f"  ... fila {queue_name!r} ausente — declarando via AMQP")
        if not _declare_queue(rabbitmq_url, queue_name):
            return False
        names = _list_queue_names(api_url, user, password)
        if names is None or queue_name not in names:
            _fail(f"Fila {queue_name!r} ainda não visível após queue_declare")
            return False
        _ok(f"Fila {queue_name!r} criada (durable) no RabbitMQ")
        return True

    _ok(f"RabbitMQ management API responde e fila {queue_name!r} existe")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificação Fase 0 — base operacional")
    parser.add_argument(
        "--postgres-url",
        default="postgresql://track_fraude:track_fraude@127.0.0.1:5432/track_fraude",
    )
    parser.add_argument(
        "--rabbitmq-api",
        default="http://127.0.0.1:15672/api/queues/%2F",
    )
    parser.add_argument("--rabbitmq-user", default="track_fraude")
    parser.add_argument("--rabbitmq-password", default="track_fraude")
    parser.add_argument(
        "--rabbitmq-url",
        default="amqp://track_fraude:track_fraude@127.0.0.1:5672/%2F",
    )
    parser.add_argument("--queue-name", default="track-fraude-pipelines")
    parser.add_argument(
        "--no-declare-queue",
        action="store_true",
        help="Não criar fila automaticamente se ainda não existir",
    )
    parser.add_argument("--skip-live", action="store_true", help="Só valida arquivos do repo")
    args = parser.parse_args()

    print("Fase 0 — verificação base operacional\n")

    results = [
        check_compose_file(),
        check_k8s_queue_mode(),
        check_worker_scaledjob(),
    ]

    if not args.skip_live:
        results.append(check_postgres(args.postgres_url))
        results.append(
            check_rabbitmq_management(
                args.rabbitmq_api,
                args.rabbitmq_user,
                args.rabbitmq_password,
                queue_name=args.queue_name,
                rabbitmq_url=args.rabbitmq_url,
                declare_missing=not args.no_declare_queue,
            )
        )

    print()
    if all(results):
        print("Fase 0 (checks automatizados): PASS")
        return 0
    print("Fase 0 (checks automatizados): FAIL — corrija os itens acima")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
