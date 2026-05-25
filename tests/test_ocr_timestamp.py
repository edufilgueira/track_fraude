from __future__ import annotations

from datetime import datetime

import pytest

from track_fraude.sync.ocr_timestamp import normalize_ocr_timestamp_text, parse_timestamp_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("22/05/2026 06:10:00", datetime(2026, 5, 22, 6, 10, 0)),
        ("22/05/202606:16:30", datetime(2026, 5, 22, 6, 16, 30)),
        ("22-05-2026 06:16:30", datetime(2026, 5, 22, 6, 16, 30)),
        ("22.05.2026 06:16:30", datetime(2026, 5, 22, 6, 16, 30)),
        ("2026-05-2514:41:56", datetime(2026, 5, 25, 14, 41, 56)),
        ("2026-05-25 14:41:56", datetime(2026, 5, 25, 14, 41, 56)),
    ],
)
def test_parse_timestamp_text(raw: str, expected: datetime):
    assert parse_timestamp_text(raw) == expected


def test_normalize_merged_year_hour():
    assert normalize_ocr_timestamp_text("22/05/202606:16:30") == "22/05/2026 06:16:30"


def test_normalize_iso_date_glued_to_time():
    assert normalize_ocr_timestamp_text("2026-05-2514:41:56") == "2026-05-25 14:41:56"


def test_parse_timestamp_text_rejects_garbage():
    assert parse_timestamp_text("sem data") is None
