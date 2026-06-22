"""util 단위 테스트 — 층 파싱 및 '저/중/고' 밴드 추정층."""

from __future__ import annotations

import pytest

from myhouse.util import estimate_floor_from_band, parse_floor


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12/15", (("12/15"), 12)),
        ("고/15", ("고/15", None)),
        ("저/3", ("저/3", None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_floor(raw, expected):
    assert parse_floor(raw) == expected


@pytest.mark.parametrize(
    "floor_info,expected",
    [
        # 15층 단지: 저=1~5(중앙3) · 중=6~10(중앙8) · 고=11~15(중앙13)
        ("저/15", 3),
        ("중/15", 8),
        ("고/15", 13),
        # 3층 단지: 한 층씩 → 저1·중2·고3
        ("저/3", 1),
        ("중/3", 2),
        ("고/3", 3),
        # 숫자층/총층결손/밴드아님 → 추정 불가
        ("12/15", None),
        ("고", None),
        ("고/", None),
        ("", None),
        (None, None),
    ],
)
def test_estimate_floor_from_band(floor_info, expected):
    assert estimate_floor_from_band(floor_info) == expected


def test_estimate_floor_band_order_and_bounds():
    """어떤 총층이든 저<중<고 순이고 1..총층 범위를 벗어나지 않는다."""
    for total in range(1, 60):
        lo = estimate_floor_from_band(f"저/{total}")
        mid = estimate_floor_from_band(f"중/{total}")
        hi = estimate_floor_from_band(f"고/{total}")
        assert lo is not None and mid is not None and hi is not None
        assert 1 <= lo <= mid <= hi <= total
