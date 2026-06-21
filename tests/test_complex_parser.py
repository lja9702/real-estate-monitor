"""단지 메타 파싱(parse_complex_meta) + 한 줄 요약 포맷(format_complex_meta).

라이브 검증(2026-06)으로 확인한 new.land 단지상세 필드명을 회귀로 고정한다:
  totalHouseholdCount·totalDongCount·useApproveYmd·batlRatio(용적률)·btlRatio(건폐율).
"""

from __future__ import annotations

from myhouse.naver.complex_parser import ComplexMeta, parse_complex_meta
from myhouse.util import format_complex_meta, format_use_approve


# ── parse_complex_meta ──────────────────────────────────────────────────────
def test_parse_nested_complex_detail():
    """실제 응답 형태 — 메타는 complexDetail 아래 중첩, 값은 문자열로 옴."""
    payload = {
        "complexDetail": {
            "complexName": "삼호1차",
            "totalHouseholdCount": 419,
            "totalDongCount": 3,
            "useApproveYmd": "19751128",
            "batlRatio": "238",  # 용적률
            "btlRatio": "23",  # 건폐율
            "latitude": 37.48,
            "longitude": 126.99,
        },
        "complexPyeongDetailList": [],
    }
    m = parse_complex_meta(payload)
    assert m.total_households == 419
    assert m.total_dong_count == 3
    assert m.use_approve_ymd == "19751128"
    assert m.floor_area_ratio == 238
    assert m.building_coverage_ratio == 23
    assert m.lat == 37.48 and m.lon == 126.99


def test_parse_flat_payload():
    """complexDetail 중첩이 없으면 최상위에서 읽는다(방어적)."""
    m = parse_complex_meta(
        {"totalHouseholdCount": 630, "totalDongCount": 8, "batlRatio": "341", "btlRatio": "23"}
    )
    assert m.total_households == 630
    assert m.total_dong_count == 8
    assert m.floor_area_ratio == 341
    assert m.building_coverage_ratio == 23


def test_parse_missing_fields_all_none():
    m = parse_complex_meta({"complexDetail": {"complexName": "이름만"}})
    assert m == ComplexMeta()


def test_parse_float_ratio_string():
    """비율이 소수 문자열로 와도 int 로 정규화."""
    m = parse_complex_meta({"complexDetail": {"batlRatio": "238.0", "btlRatio": "22.6"}})
    assert m.floor_area_ratio == 238
    assert m.building_coverage_ratio == 22


def test_parse_bad_ymd_dropped():
    assert parse_complex_meta({"complexDetail": {"useApproveYmd": "1975"}}).use_approve_ymd is None
    assert parse_complex_meta({"complexDetail": {"useApproveYmd": ""}}).use_approve_ymd is None


def test_parse_garbage_inputs():
    assert parse_complex_meta(None) == ComplexMeta()
    assert parse_complex_meta("nope") == ComplexMeta()
    assert parse_complex_meta({}) == ComplexMeta()
    assert parse_complex_meta({"complexDetail": None}) == ComplexMeta()


# ── format_complex_meta ─────────────────────────────────────────────────────
def test_format_full_line():
    s = format_complex_meta(
        households=419,
        dong_count=3,
        use_approve_ymd="19751128",
        floor_area_ratio=238,
        building_coverage_ratio=23,
    )
    assert s == "419세대(3개동) · 1975.11 준공 · 용적률 238% · 건폐율 23%"


def test_format_partial_only_present():
    assert format_complex_meta(households=630) == "630세대"
    assert format_complex_meta(dong_count=8) == "8개동"
    assert format_complex_meta(use_approve_ymd="19990614") == "1999.06 준공"
    assert format_complex_meta(floor_area_ratio=341) == "용적률 341%"
    assert format_complex_meta(building_coverage_ratio=23) == "건폐율 23%"


def test_format_thousands_separator():
    assert format_complex_meta(households=1234, dong_count=15) == "1,234세대(15개동)"


def test_format_empty_is_none():
    assert format_complex_meta() is None
    assert format_complex_meta(households=None, dong_count=None) is None


def test_format_use_approve_variants():
    assert format_use_approve("19751128") == "1975.11 준공"
    assert format_use_approve("20200001") == "2020년 준공"  # 월 '00' → 연도만
    assert format_use_approve("2020") == "2020년 준공"  # 월 결손
    assert format_use_approve("") is None
    assert format_use_approve(None) is None
    assert format_use_approve("garbage") is None
