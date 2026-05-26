from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from track_fraude.models.pos import PosDayExport, Transaction
from track_fraude.pos.client import PosClient
from track_fraude.pos.file_client import DEFAULT_STATUSES

DEFAULT_TIMEOUT_SEC = 15


class HttpPosClient(PosClient):
    """Cliente HTTP para a API POS provisória (data/pos/server.js)."""

    def __init__(self, base_url: str, *, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def _request_json(self, path: str, *, query: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            filtered = {key: value for key, value in query.items() if value is not None}
            url = f"{url}?{urlencode(filtered)}"

        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"POS API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"POS API indisponível em {self.base_url}: {exc.reason}") from exc

        if "error" in payload and "transactions" not in payload:
            raise RuntimeError(str(payload["error"]))
        return payload

    def get_day_export(self, store_id: str, date: str) -> PosDayExport:
        payload = self._request_json(
            "/day",
            query={"store_id": store_id, "date": date},
        )
        export = PosDayExport.from_dict(payload)
        if export.store_id != store_id:
            raise ValueError(
                f"store_id esperado {store_id}, API retornou {export.store_id}"
            )
        return export

    def get_transactions_between(
        self,
        store_id: str,
        date: str,
        t_from: datetime,
        t_to: datetime,
        lane_id: int | None = None,
        statuses: list[str] | None = None,
    ) -> list[Transaction]:
        allowed = statuses or DEFAULT_STATUSES
        payload = self._request_json(
            "/transactions",
            query={
                "store_id": store_id,
                "date": date,
                "t_from": t_from.isoformat(),
                "t_to": t_to.isoformat(),
                "lane_id": lane_id,
                "statuses": ",".join(allowed),
            },
        )
        return [
            Transaction.from_dict(item) for item in payload.get("transactions", [])
        ]
