from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

PIPELINE_STATUS_QUEUED = "queued"
PIPELINE_STATUS_RUNNING = "running"
PIPELINE_STATUS_COMPLETED = "completed"
PIPELINE_STATUS_FAILED = "failed"
PIPELINE_STATUS_CANCELLED = "cancelled"

PIPELINE_ACTIVE_STATUSES = (PIPELINE_STATUS_QUEUED, PIPELINE_STATUS_RUNNING)
PIPELINE_TERMINAL_STATUSES = (
    PIPELINE_STATUS_COMPLETED,
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_CANCELLED,
)


@dataclass(frozen=True)
class PipelineQueueMessage:
    run_id: int
    store_db_id: int
    group_code: str
    store_id: str
    date: str
    db_path: str
    pos_root: str = "data/pos"
    pos_api_url: str | None = None
    skip_vision: bool = False
    skip_evidence: bool = False
    from_phase: str | None = None
    only_phase: str | None = None
    only_camera: str | None = None
    log_path: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload: str | bytes) -> "PipelineQueueMessage":
        raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        data: dict[str, Any] = json.loads(raw)
        return cls(
            run_id=int(data["run_id"]),
            store_db_id=int(data["store_db_id"]),
            group_code=str(data["group_code"]),
            store_id=str(data["store_id"]),
            date=str(data["date"]),
            db_path=str(data["db_path"]),
            pos_root=str(data.get("pos_root") or "data/pos"),
            pos_api_url=data.get("pos_api_url"),
            skip_vision=bool(data.get("skip_vision", False)),
            skip_evidence=bool(data.get("skip_evidence", False)),
            from_phase=data.get("from_phase"),
            only_phase=data.get("only_phase"),
            only_camera=data.get("only_camera"),
            log_path=data.get("log_path"),
        )

    def worker_args(self) -> list[str]:
        args = [
            "--date",
            self.date,
            "--store-id",
            self.store_id,
            "--group-code",
            self.group_code,
            "--db",
            self.db_path,
            "--run-id",
            str(self.run_id),
        ]
        if self.pos_api_url:
            args.extend(["--pos-api-url", self.pos_api_url])
        else:
            args.extend(["--pos-root", self.pos_root])
        if self.skip_vision:
            args.append("--skip-vision")
        if self.skip_evidence:
            args.append("--skip-evidence")
        if self.from_phase:
            args.extend(["--from", self.from_phase])
        if self.only_phase:
            args.extend(["--only", self.only_phase])
        if self.only_camera:
            args.extend(["--camera", self.only_camera])
        return args
