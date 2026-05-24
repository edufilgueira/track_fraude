from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from track_fraude.models.pos import PosDayExport, Transaction


class PosClient(ABC):
    @abstractmethod
    def get_day_export(self, store_id: str, date: str) -> PosDayExport:
        raise NotImplementedError

    @abstractmethod
    def get_transactions_between(
        self,
        store_id: str,
        date: str,
        t_from: datetime,
        t_to: datetime,
        lane_id: int | None = None,
        statuses: list[str] | None = None,
    ) -> list[Transaction]:
        raise NotImplementedError
