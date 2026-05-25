from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

TRACK_COLUMNS = ("track_id", "frame_idx", "t_abs", "x1", "y1", "x2", "y2")


def _empty_table() -> pa.Table:
    return pa.table(
        {
            "track_id": pa.array([], type=pa.int64()),
            "frame_idx": pa.array([], type=pa.int64()),
            "t_abs": pa.array([], type=pa.string()),
            "x1": pa.array([], type=pa.float64()),
            "y1": pa.array([], type=pa.float64()),
            "x2": pa.array([], type=pa.float64()),
            "y2": pa.array([], type=pa.float64()),
        }
    )


def detections_to_table(rows: list[dict[str, Any]]) -> pa.Table:
    if not rows:
        return _empty_table()
    return pa.Table.from_pylist(rows)


def write_tracks_parquet(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(detections_to_table(rows), path, compression="snappy")
    return path


def read_tracks_parquet(path: Path) -> list[dict[str, Any]]:
    return pq.read_table(path).to_pylist()


def group_by_frame(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        frame_idx = int(row["frame_idx"])
        grouped.setdefault(frame_idx, []).append(row)
    return grouped
