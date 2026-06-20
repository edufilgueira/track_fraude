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


def check_rabbitmq_management(api_url: str, user: str, password: str) -> bool:
    request = urllib.request.Request(api_url)
    credentials = f"{user}:{password}".encode("utf-8")
    import base64

    request.add_header("Authorization", "Basic " + base64.b64encode(credentials).decode("ascii"))
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        _fail(f"RabbitMQ management API inacessível: {exc}")
        return False

    names = {item.get("name") for item in payload if isinstance(item, dict)}
    if "track-fraude-pipelines" not in names:
        _fail("Fila track-fraude-pipelines não encontrada no RabbitMQ")
        return False
    _ok("RabbitMQ management API responde e fila track-fraude-pipelines existe")
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
                args.rabbitmq_api, args.rabbitmq_user, args.rabbitmq_password
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
