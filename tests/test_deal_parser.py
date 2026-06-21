"""실거래 파서 테스트 — 평형/거래 파싱·취소 플래그·키 안정성·결손 스킵."""

from __future__ import annotations

import pytest

from myhouse.constants import TradeType
from myhouse.naver.deal_parser import (
    PyeongInfo,
    compute_deal_key,
    parse_deals,
    parse_pyeongs,
)
from myhouse.naver.errors import NaverParseError

DETAIL = {
    "complexPyeongDetailList": [
        {
            "pyeongNo": "3",
            "pyeongName": "80B",
            "supplyArea": "80.85",
            "exclusiveArea": "80.33",
            "householdCountByPyeong": "76",
        },
        {
            "pyeongNo": "1",
            "pyeongName": "82A",
            "supplyArea": "82.08",
            "exclusiveArea": "81.39",
            "householdCountByPyeong": "174",
        },
    ]
}

PYEONG = PyeongInfo(
    pyeong_no="3", pyeong_name="80B", area_supply=80.85, area_excl=80.33, households=76
)

REAL_PAYLOAD = {
    "areaNo": 3,
    "realPriceOnMonthList": [
        {
            "tradeBaseYear": "2025",
            "tradeBaseMonth": 11,
            "realPriceList": [
                {
                    "tradeType": "A1",
                    "tradeYear": "2025",
                    "tradeMonth": 11,
                    "tradeDate": "21",
                    "dealPrice": 220000,
                    "floor": 11,
                    "formattedPrice": "22억",
                },
            ],
        },
        {
            "tradeBaseYear": "2024",
            "tradeBaseMonth": 12,
            "realPriceList": [
                {  # 거래취소
                    "tradeType": "A1",
                    "tradeYear": "2024",
                    "tradeMonth": 12,
                    "tradeDate": "04",
                    "dealPrice": 170000,
                    "floor": 10,
                    "deleteYn": "O",
                },
                {  # 날짜 결손 → 스킵
                    "tradeType": "A1",
                    "tradeYear": "2024",
                    "tradeMonth": 12,
                    "tradeDate": "",
                    "dealPrice": 160000,
                    "floor": 7,
                },
            ],
        },
    ],
    "totalRowCount": 92,
}


def test_parse_pyeongs():
    pyeongs = parse_pyeongs(DETAIL)
    assert len(pyeongs) == 2
    p = {x.pyeong_no: x for x in pyeongs}
    assert p["3"].pyeong_name == "80B"
    assert p["3"].area_supply == pytest.approx(80.85)
    assert p["3"].area_excl == pytest.approx(80.33)
    assert p["3"].households == 76
    assert p["1"].area_excl == pytest.approx(81.39)


def test_parse_pyeongs_missing_raises():
    with pytest.raises(NaverParseError):
        parse_pyeongs({"foo": 1})


def test_parse_deals_tags_area_and_handles_cancel():
    deals = parse_deals(REAL_PAYLOAD, "947", PYEONG, TradeType.SALE)
    assert len(deals) == 2  # 날짜 결손 1건 스킵

    by_date = {d.deal_date: d for d in deals}
    d1 = by_date["2025-11-21"]
    assert d1.price_deal == 220000
    assert d1.floor == 11
    assert d1.cancelled is False
    # 면적은 평형(PyeongInfo)에서 태깅
    assert d1.area_excl == pytest.approx(80.33)
    assert d1.pyeong_name == "80B"
    assert d1.pyeong_no == "3"
    assert d1.trade_type == TradeType.SALE

    d2 = by_date["2024-12-04"]
    assert d2.cancelled is True


def test_parse_deals_jeonse_uses_lease_price():
    payload = {
        "realPriceOnMonthList": [
            {
                "realPriceList": [
                    {
                        "tradeType": "B1",
                        "tradeYear": "2026",
                        "tradeMonth": 1,
                        "tradeDate": "10",
                        "dealPrice": 0,
                        "leasePrice": 65000,
                        "floor": 5,
                    }
                ]
            }
        ]
    }
    deals = parse_deals(payload, "947", PYEONG, TradeType.JEONSE)
    assert len(deals) == 1
    assert deals[0].trade_type == TradeType.JEONSE
    assert deals[0].price_deal == 65000


def test_parse_deals_missing_list_raises():
    with pytest.raises(NaverParseError):
        parse_deals({"foo": 1}, "947", PYEONG, TradeType.SALE)


def test_deal_key_stable_and_cancel_independent():
    """같은 거래는 항상 같은 키 — 취소여부는 키에 영향 없음(취소가 같은 행을 갱신하도록)."""
    args = ("947", TradeType.SALE, "2024-12-04", 10, "3", 170000, None)
    assert compute_deal_key(*args) == compute_deal_key(*args)
    # 같은 거래가 취소로 다시 들어와도 키 동일 (parse_deals 가 cancel 을 키에 안 넣음)
    normal = parse_deals(REAL_PAYLOAD, "947", PYEONG, TradeType.SALE)
    cancel = next(d for d in normal if d.cancelled)
    assert cancel.deal_key == compute_deal_key(
        "947", TradeType.SALE, "2024-12-04", 10, "3", 170000, None
    )


def test_deal_key_differs_by_price_floor():
    base = compute_deal_key("947", TradeType.SALE, "2024-12-04", 10, "3", 170000, None)
    assert base != compute_deal_key("947", TradeType.SALE, "2024-12-04", 11, "3", 170000, None)
    assert base != compute_deal_key("947", TradeType.SALE, "2024-12-04", 10, "3", 180000, None)
