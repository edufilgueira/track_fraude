from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PosItem:
    sku: str
    name: str
    qty: int
    unit_price: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PosItem:
        return cls(
            sku=str(data["sku"]),
            name=str(data["name"]),
            qty=int(data["qty"]),
            unit_price=float(data["unit_price"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "name": self.name,
            "qty": self.qty,
            "unit_price": self.unit_price,
        }


@dataclass
class Transaction:
    transaction_id: str
    t_sale: datetime
    lane_id: int
    status: str
    items: list[PosItem]
    qty_total: int
    total_value: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transaction:
        return cls(
            transaction_id=str(data["transaction_id"]),
            t_sale=datetime.fromisoformat(str(data["t_sale"])),
            lane_id=int(data["lane_id"]),
            status=str(data["status"]),
            items=[PosItem.from_dict(item) for item in data.get("items", [])],
            qty_total=int(data["qty_total"]),
            total_value=float(data["total_value"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "t_sale": self.t_sale.isoformat(),
            "lane_id": self.lane_id,
            "status": self.status,
            "items": [item.to_dict() for item in self.items],
            "qty_total": self.qty_total,
            "total_value": self.total_value,
        }


@dataclass
class PosDayExport:
    store_id: str
    date: str
    timezone: str
    transactions: list[Transaction] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PosDayExport:
        return cls(
            store_id=str(data["store_id"]),
            date=str(data["date"]),
            timezone=str(data["timezone"]),
            transactions=[
                Transaction.from_dict(tx) for tx in data.get("transactions", [])
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "date": self.date,
            "timezone": self.timezone,
            "transactions": [tx.to_dict() for tx in self.transactions],
        }
