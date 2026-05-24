from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from track_fraude.models.pos import PosDayExport, Transaction
from track_fraude.pos.client import PosClient

DEFAULT_STATUSES = ["paid", "completed"]


class FilePosClient(PosClient):
    def __init__(self, pos_root: Path | str = "data/pos") -> None:
        self.pos_root = Path(pos_root)

    def _path_for_date(self, date: str) -> Path:
        return self.pos_root / date / "transactions.json"

    def get_day_export(self, store_id: str, date: str) -> PosDayExport:
        path = self._path_for_date(date)
        if not path.exists():
            raise FileNotFoundError(f"POS não encontrado: {path}")

        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)

        export = PosDayExport.from_dict(payload)
        if export.store_id != store_id:
            raise ValueError(
                f"store_id esperado {store_id}, arquivo contém {export.store_id}"
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
        export = self.get_day_export(store_id, date)
        allowed_statuses = statuses or DEFAULT_STATUSES

        matches: list[Transaction] = []
        for tx in export.transactions:
            if tx.t_sale < t_from or tx.t_sale > t_to:
                continue
            if lane_id is not None and tx.lane_id != lane_id:
                continue
            if tx.status not in allowed_statuses:
                continue
            matches.append(tx)
        return sorted(matches, key=lambda item: item.t_sale)
