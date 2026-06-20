from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from track_fraude_core.pipeline_queue import PipelineQueueMessage


class AtlasPlatformError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AtlasPlatformClient:
    def __init__(self, *, api_url: str, api_key: str | None = None) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = (api_key or "").strip()

    def create_job(
        self,
        *,
        workload: str,
        message: PipelineQueueMessage,
    ) -> dict[str, Any]:
        payload = asdict(message)
        body = json.dumps(
            {"workload": workload, "payload": payload},
            ensure_ascii=False,
        ).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            f"{self.api_url}/v1/jobs",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AtlasPlatformError(
                f"Atlas Platform API HTTP {exc.code}: {detail}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise AtlasPlatformError(
                f"Falha ao contactar Atlas Platform API: {exc.reason}"
            ) from exc

        data = json.loads(raw)
        if not isinstance(data, dict) or not data.get("id"):
            raise AtlasPlatformError("Resposta inválida da Atlas Platform API")
        return data

    def get_job(self, job_id: str) -> dict[str, Any]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            f"{self.api_url}/v1/jobs/{job_id}",
            headers=headers,
            method="GET",
        )
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
