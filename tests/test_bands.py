"""가격밴드 헬퍼(notify.bands) + /band 인자 파서(bot.commands._parse_band)."""

from __future__ import annotations

import pytest

from myhouse.bot.commands import _parse_band
from myhouse.notify.bands import band_overlaps, format_band, in_band


# ── in_band ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "price,lo,hi,expected",
    [
        (100000, 70000, 120000, True),   # 10억 ∈ [7,12]
        (50000, 70000, 120000, False),   # 5억 < 7억
        (130000, 70000, 120000, False),  # 13억 > 12억
        (70000, 70000, 120000, True),    # 경계 포함(하한)
        (120000, 70000, 120000, True),   # 경계 포함(상한)
        (999999, 150000, None, True),    # 상한 없음
        (10000, None, 120000, True),     # 하한 없음
        (10000, None, None, True),       # 무제한
        (None, 70000, 120000, True),     # 가격 불명 → 포함(보수적)
    ],
)
def test_in_band(price, lo, hi, expected):
    assert in_band(price, lo, hi) is expected


# ── band_overlaps ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "vlo,vhi,lo,hi,expected",
    [
        (80000, 110000, 70000, 120000, True),    # 완전 포함
        (60000, 80000, 70000, 120000, True),     # 하단 걸침
        (110000, 200000, 70000, 120000, True),   # 상단 걸침
        (10000, 60000, 70000, 120000, False),    # 밴드보다 아래
        (130000, 200000, 70000, 120000, False),  # 밴드보다 위
        (None, None, 70000, 120000, True),       # 범위 불명 → 포함
        (90000, 90000, None, None, True),        # 무제한 밴드
    ],
)
def test_band_overlaps(vlo, vhi, lo, hi, expected):
    assert band_overlaps(vlo, vhi, lo, hi) is expected


# ── format_band ──────────────────────────────────────────────────────────────
def test_format_band():
    assert format_band(None, None) is None
    assert format_band(70000, 120000) == "7억~12억"
    assert format_band(150000, None) == "15억↑"
    assert format_band(None, 120000) == "~12억"


# ── _parse_band (/band 인자) ─────────────────────────────────────────────────
@pytest.mark.parametrize(
    "arg,expected",
    [
        ("", ("show", None, None)),
        ("   ", ("show", None, None)),
        ("off", ("off", None, None)),
        ("전체", ("off", None, None)),
        ("0", ("off", None, None)),
        ("7 12", ("set", 70000, 120000)),
        ("12 7", ("set", 70000, 120000)),   # 순서 무관
        ("7-12", ("set", 70000, 120000)),   # 하이픈 구분
        ("7~12", ("set", 70000, 120000)),   # 물결 구분
        ("15", ("set", 150000, None)),      # 단일 = 하한
        ("0 12", ("set", 0, 120000)),       # 12억 이하
        ("7.5 12", ("set", 75000, 120000)), # 소수 억
        ("abc", ("error", None, None)),
        ("7 12 15", ("error", None, None)), # 3개 이상
    ],
)
def test_parse_band(arg, expected):
    assert _parse_band(arg) == expected
