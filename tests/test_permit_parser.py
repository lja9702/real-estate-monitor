"""토지거래허가 파서 테스트 — 지번 정규화·매칭키·날짜·EXCEPTION·결손 스킵."""

from __future__ import annotations

import pytest

from myhouse.seoul.errors import SeoulParseError
from myhouse.seoul.permit_parser import (
    compute_permit_key,
    jibun_from_parts,
    normalize_jibun,
    parse_permits,
)

PAYLOAD = {
    "result": [
        {
            "ACC_YEAR": "2026", "ACC_NO": "0001732", "OBJ_SEQNO": "1",
            "SGG_CD": "11680", "LAWD_CD": "1168010600",
            "ADDRESS": "강남구 대치동 974 ", "BOBN": "0974", "BUBN": "0000",
            "HNDL_YMD": "20260526", "JOB_GBN_NM": "허가", "USE_PURP": "주거용", "JIMOK": "대",
        },
        {
            "ACC_YEAR": "2026", "ACC_NO": "0001733", "OBJ_SEQNO": "1",
            "SGG_CD": "11680", "LAWD_CD": "1168010400",
            "ADDRESS": "강남구 청담동 127-31 ", "BOBN": "0127", "BUBN": "0031",
            "HNDL_YMD": "20260619", "JOB_GBN_NM": "허가", "USE_PURP": "주거용", "JIMOK": "대",
        },
        {  # 취소 — 파싱은 하되 granted=False
            "ACC_YEAR": "2026", "ACC_NO": "0001734", "OBJ_SEQNO": "1",
            "SGG_CD": "11680", "LAWD_CD": "1168010600",
            "ADDRESS": "강남구 대치동 316 ", "BOBN": "0316", "BUBN": "0000",
            "HNDL_YMD": "20260618", "JOB_GBN_NM": "취소", "USE_PURP": "주거용", "JIMOK": "대",
        },
        {  # 접수번호 결손 → skip
            "ACC_YEAR": "2026", "ACC_NO": "", "OBJ_SEQNO": "1",
            "ADDRESS": "강남구 대치동 999", "BOBN": "0999", "BUBN": "0000",
        },
    ]
}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("770-1", ("0770", "0001")),
        ("974", ("0974", "0000")),
        ("974 외", ("0974", "0000")),
        ("0127-0031", ("0127", "0031")),
        ("산12-3", None),  # 임야 — 아파트 아님
        ("", None),
        ("-", None),
        (None, None),
    ],
)
def test_normalize_jibun(raw, expected):
    assert normalize_jibun(raw) == expected


def test_jibun_from_parts():
    assert jibun_from_parts("0974", "0000") == ("0974", "0000")
    assert jibun_from_parts("0770", "0001") == ("0770", "0001")
    assert jibun_from_parts("974", "0") == ("0974", "0000")  # zero-pad 보정
    assert jibun_from_parts("0000", "0000") == (None, None)  # 본번 0 → 매칭 불가


def test_jibun_normalize_matches_parts():
    """단지 detailAddress 와 허가 BOBN/BUBN 이 같은 형식으로 떨어져야 매칭된다."""
    assert normalize_jibun("974") == jibun_from_parts("0974", "0000")
    assert normalize_jibun("770-1") == jibun_from_parts("0770", "0001")


def test_parse_permits():
    permits = parse_permits(PAYLOAD, "11680")
    assert len(permits) == 3  # 접수번호 결손 1건 skip

    by_addr = {p.address: p for p in permits}
    dch = by_addr["강남구 대치동 974"]  # _clean 이 trailing space 제거
    assert dch.bonbun == "0974"
    assert dch.bubun == "0000"
    assert dch.lawd_cd == "1168010600"
    assert dch.permit_date == "2026-05-26"
    assert dch.use_purp == "주거용"
    assert dch.granted is True

    cd = by_addr["강남구 청담동 127-31"]
    assert (cd.bonbun, cd.bubun) == ("0127", "0031")


def test_parse_permits_cancel_not_granted():
    permits = parse_permits(PAYLOAD, "11680")
    cancel = next(p for p in permits if p.job_gbn == "취소")
    assert cancel.granted is False


def test_permit_key_stable_and_unique():
    a = compute_permit_key("11680", "2026", "0001732", "1")
    assert a == compute_permit_key("11680", "2026", "0001732", "1")
    assert a != compute_permit_key("11680", "2026", "0001733", "1")  # 접수번호 다름
    assert a != compute_permit_key("11680", "2026", "0001732", "2")  # 대상순번 다름


def test_exception_message_returns_empty():
    """한국토지정보시스템 점검(EXCEPTION) 응답은 빈 리스트(에러 아님)."""
    assert parse_permits({"result": [{"MESSAGE": "EXCEPTION"}]}, "11680") == []


def test_missing_result_raises():
    with pytest.raises(SeoulParseError):
        parse_permits({"foo": 1}, "11680")
