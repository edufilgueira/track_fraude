#!/usr/bin/env python3
"""Verifica pré-requisitos da Fase 1 — Atlas Platform API."""

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


def check_schema_file() -> bool:
    path = ROOT / "infra" / "postgres" / "schema_atlas.sql"
    if not path.is_file():
        _fail(f"Schema ausente: {path}")
        return False
    text = path.read_text(encoding="utf-8")
    ok = True
    for token in ("atlas.workloads", "atlas.jobs", "atlas.api_keys", "track-fraude"):
        if token not in text:
            _fail(f"schema_atlas.sql não contém {token!r}")
            ok = False
    if ok:
        _ok("schema_atlas.sql presente com tabelas e seed track-fraude")
    return ok


def check_k8s_manifests() -> bool:
    ok = True
    api_path = ROOT / "infra" / "k8s" / "atlas-platform-api.yaml"
    if not api_path.is_file():
        _fail("Manifest ausente: infra/k8s/atlas-platform-api.yaml")
        ok = False
    else:
        text = api_path.read_text(encoding="utf-8")
        if "atlas-platform-api" not in text:
            _fail("Deployment atlas-platform-api não encontrado")
            ok = False
        else:
            _ok("Manifest K8s da Platform API presente")

    cfg_path = ROOT / "infra" / "k8s" / "app-config.yaml"
    text = cfg_path.read_text(encoding="utf-8")
    if "atlas:" not in text or "api_url:" not in text:
        _fail("app-config.yaml não define atlas.api_url")
        ok = False
    else:
        _ok("app-config.yaml aponta UI para Atlas API")
    return ok


def check_dockerfile() -> bool:
    path = ROOT / "Dockerfile.atlas-platform-api"
    if not path.is_file():
        _fail("Dockerfile.atlas-platform-api ausente")
        return False
    _ok("Dockerfile.atlas-platform-api presente")
    return True


def check_live_api(api_url: str, api_key: str) -> bool:
    url = api_url.rstrip("/") + "/v1/health"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        _fail(f"Platform API inacessível em {url}: {exc.reason}")
        return False

    if payload.get("status") != "ok":
        _fail(f"Health inesperado: {payload}")
        return False
    _ok(f"GET {url} → ok")

    if api_key:
        body = json.dumps(
            {
                "workload": "track-fraude",
                "payload": {"run_id": 0},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            api_url.rstrip("/") + "/v1/jobs",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                _fail(f"POST /v1/jobs deveria falhar com payload inválido, got {response.status}")
                return False
        except urllib.error.HTTPError as exc:
            if exc.code in {400, 404, 502}:
                _ok("POST /v1/jobs responde com erro esperado para payload de teste")
            else:
                _fail(f"POST /v1/jobs HTTP {exc.code}")
                return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifica Fase 1 Atlas")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--api-url", default="http://127.0.0.1:30090")
    parser.add_argument("--api-key", default="atlas-dev-internal-key")
    args = parser.parse_args()

    checks = [
        check_schema_file(),
        check_dockerfile(),
        check_k8s_manifests(),
    ]
    if not args.skip_live:
        checks.append(check_live_api(args.api_url, args.api_key))

    if all(checks):
        print("\nFase 1 — verificação PASS")
        return

    print("\nFase 1 — verificação FAIL")
    sys.exit(1)


if __name__ == "__main__":
    main()
