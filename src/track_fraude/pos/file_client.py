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

    def _load_export(self, store_id: str, date: str) -> PosDayExport:
        legacy_path = self._path_for_date(date)
        if legacy_path.exists():
            with legacy_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            export = PosDayExport.from_dict(payload)
            if export.store_id != store_id:
                raise ValueError(
                    f"store_id esperado {store_id}, arquivo contém {export.store_id}"
                )
            return export

        consolidated_path = self.pos_root / "transactions.json"
        if not consolidated_path.exists():
            raise FileNotFoundError(
                f"POS não encontrado: {legacy_path} ou {consolidated_path}"
            )

        with consolidated_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)

        if isinstance(payload.get("exports"), list):
            for item in payload["exports"]:
                if item.get("store_id") == store_id and item.get("date") == date:
                    merged = dict(item)
                    merged.setdefault("timezone", payload.get("timezone", "America/Sao_Paulo"))
                    return PosDayExport.from_dict(merged)
            raise FileNotFoundError(
                f"POS não encontrado para store_id={store_id} date={date} em {consolidated_path}"
            )

        export = PosDayExport.from_dict(payload)
        if export.store_id != store_id:
            raise ValueError(
                f"store_id esperado {store_id}, arquivo contém {export.store_id}"
            )
        if export.date != date:
            raise FileNotFoundError(
                f"POS em {consolidated_path} é do dia {export.date}, pedido {date}"
            )
        return export

    def get_day_export(self, store_id: str, date: str) -> PosDayExport:
        return self._load_export(store_id, date)

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
