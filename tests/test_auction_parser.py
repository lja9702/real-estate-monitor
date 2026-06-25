"""경매 물건 파서 테스트 — 금액 만원환산·지번·매칭키·아파트 판별·결손 스킵·구조오류."""

from __future__ import annotations

import pytest

from myhouse.court.auction_parser import (
    AuctionDTO,
    extract_flags,
    parse_auction_row,
    parse_auctions,
)
from myhouse.court.errors import CourtAuctionParseError

# 라이브 응답(dlt_srchResult) 구조 기반 — 정릉동 아파트, 청담 유찰2 아파트, 토지(비아파트), docid 결손.
PAYLOAD = {
    "data": {
        "dma_pageInfo": {"totalCnt": "3", "pageNo": 1, "pageSize": 40},
        "dlt_srchResult": [
            {
                "docid": "B0002102008013002509213", "boCd": "B000210", "jiwonNm": "서울중앙지방법원",
                "saNo": "20080130025092", "srnSaNo": "2008타경25092", "mokmulSer": "3", "maemulSer": "1",
                "hjguSido": "서울특별시", "hjguSigu": "성북구", "hjguDong": "정릉동",
                "daepyoLotno": "508-123", "buldNm": "", "buldList": "1층102호",
                "gamevalAmt": "194000000", "minmaePrice": "194000000", "yuchalCnt": "1",
                "maeGiil": "20260625", "mulStatcd": "01", "jinstatCd": "0002100001", "mulJinYn": "Y",
                "sclsUtilCd": "20104", "dspslUsgNm": "아파트",
                "srchHjguDongCd": "11290133", "srchHjguSiguCd": "11290", "minArea": "67", "maxArea": "67",
            },
            {  # 청담 — 단지명 있음 · 유찰2 · 최저가 64%
                "docid": "B000210CHEONGDAM0001", "boCd": "B000210", "jiwonNm": "서울중앙지방법원",
                "saNo": "20240130012345", "srnSaNo": "2024타경12345", "mokmulSer": "1",
                "hjguSido": "서울특별시", "hjguSigu": "강남구", "hjguDong": "청담동",
                "daepyoLotno": "127-31", "buldNm": "청담자이",
                "gamevalAmt": "2800000000", "minmaePrice": "1792000000", "yuchalCnt": "2",
                "maeGiil": "20260805", "mulStatcd": "01", "mulJinYn": "Y",
                "sclsUtilCd": "20104", "dspslUsgNm": "아파트", "srchHjguDongCd": "11680104",
            },
            {  # 토지 — 비아파트(필터에서 빠짐)
                "docid": "B000210LAND0002", "boCd": "B000210", "jiwonNm": "서울중앙지방법원",
                "saNo": "20240130099999", "srnSaNo": "2024타경99999",
                "hjguSido": "서울특별시", "hjguSigu": "서초구", "hjguDong": "내곡동",
                "daepyoLotno": "5", "gamevalAmt": "500000000", "minmaePrice": "400000000",
                "yuchalCnt": "1", "maeGiil": "20260710", "sclsUtilCd": "10105", "dspslUsgNm": "토지",
            },
            {  # docid 결손 → skip
                "boCd": "B000210", "srnSaNo": "2024타경00000", "daepyoLotno": "1",
            },
        ],
    }
}


def test_parse_auctions_counts_and_skips():
    rows = parse_auctions(PAYLOAD)
    assert len(rows) == 3  # docid 결손 1건 skip
    assert {r.case_no for r in rows} == {"2008타경25092", "2024타경12345", "2024타경99999"}


def test_apartment_filter():
    rows = parse_auctions(PAYLOAD)
    apt = [r for r in rows if r.is_apartment]
    assert {r.case_no for r in apt} == {"2008타경25092", "2024타경12345"}  # 토지 제외


def test_amount_manwon_and_ratio():
    rows = {r.case_no: r for r in parse_auctions(PAYLOAD)}
    cheongdam = rows["2024타경12345"]
    assert cheongdam.appraisal_manwon == 280000  # 28억 (원→만원)
    assert cheongdam.min_bid_manwon == 179200
    assert cheongdam.min_bid_ratio == 64  # 17.92억 / 28억
    assert cheongdam.fail_count == 2
    assert cheongdam.building_name == "청담자이"


def test_matching_keys():
    """매칭키: dong_code(=cortar_no[:8]) + 지번 본번/부번(permits 와 동일 형식)."""
    rows = {r.case_no: r for r in parse_auctions(PAYLOAD)}
    jeongneung = rows["2008타경25092"]
    assert jeongneung.dong_code == "11290133"  # 성북구 정릉동 법정동 8자리
    assert (jeongneung.bonbun, jeongneung.bubun) == ("0508", "0123")
    assert jeongneung.address == "서울특별시 성북구 정릉동 508-123"
    assert rows["2024타경12345"].bonbun == "0127"
    assert rows["2024타경12345"].bubun == "0031"


def test_dates_and_status():
    r = {x.case_no: x for x in parse_auctions(PAYLOAD)}["2008타경25092"]
    assert r.sale_date == "2026-06-25"
    assert r.in_progress is True
    assert r.auction_key == "B0002102008013002509213"


def test_empty_result_not_error():
    """검색결과 0건(dlt_srchResult 없음)은 빈 리스트(에러 아님)."""
    assert parse_auctions({"data": {"dma_pageInfo": {"totalCnt": "0"}}}) == []


def test_missing_data_raises():
    with pytest.raises(CourtAuctionParseError):
        parse_auctions({"foo": 1})


def test_parse_row_skips_without_key():
    assert parse_auction_row({"srnSaNo": "2024타경1", "daepyoLotno": "1"}) is None  # docid 없음
    assert isinstance(parse_auction_row(PAYLOAD["data"]["dlt_srchResult"][0]), AuctionDTO)


# 라이브 검증된 물건비고 원문(서울동부 2022타경52802 자양오피스텔) — 플래그 추출 회귀.
_REAL_BIGO = (
    "1. 대지지분 없음(건물만 매각)\n"
    "2. 지분 매각임. 공유자우선매수권 행사 1회 제한 \n"
    "5. 감정서에 의하면 ... 위반건축물이 등재되어 있음."
)


def test_extract_flags_real_remark():
    flags = extract_flags(_REAL_BIGO)
    assert "지분매각" in flags
    assert "위반건축물" in flags
    assert "대지권미포함" in flags


def test_extract_flags_empty():
    assert extract_flags(None) == []
    assert extract_flags("특이사항 없음") == []


def test_flags_property_from_mulbigo():
    dto = parse_auction_row({**PAYLOAD["data"]["dlt_srchResult"][0], "mulBigo": "지분 매각임"})
    assert dto.remarks == "지분 매각임"
    assert dto.flags == ["지분매각"]
