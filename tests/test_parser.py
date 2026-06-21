"""parser 단위 테스트 (new.land) — 정규화, 한글가격, cluster_key, 방어적 실패."""

from __future__ import annotations

import pytest

from myhouse.constants import TradeType
from myhouse.naver.errors import NaverParseError
from myhouse.naver.parser import (
    compute_cluster_key,
    extract_article_body,
    has_more,
    parse_article,
    parse_korean_price,
)
from myhouse.util import parse_confirm_date


def test_parse_jeonse_article(newland_payload):
    body = extract_article_body(newland_payload)
    assert len(body) == 3
    dto = parse_article(body[0], complex_no="947")
    assert dto.article_no == "2633388082"
    assert dto.trade_type == TradeType.JEONSE
    assert dto.price_deal == 65000  # 6억 5,000
    assert dto.price_rent is None
    assert dto.area_excl == 81.0
    assert dto.area_supply == 82.0
    assert dto.area_name == "82A"
    assert dto.floor_info == "2/12" and dto.floor_num == 2
    assert dto.direction == "남향"
    assert dto.dong == "2동"
    assert dto.confirm_date == "2026-06-20"
    assert dto.cluster_key


def test_parse_sale_article(newland_payload):
    body = extract_article_body(newland_payload)
    dto = parse_article(body[1], complex_no="947")
    assert dto.trade_type == TradeType.SALE
    assert dto.price_deal == 258000  # 25억 8,000


def test_parse_wolse_article(newland_payload):
    body = extract_article_body(newland_payload)
    dto = parse_article(body[2], complex_no="947")
    assert dto.trade_type == TradeType.WOLSE
    assert dto.price_deal == 10000  # 보증금 1억
    assert dto.price_rent == 150    # 월세
    assert dto.floor_num is None    # '고/12'


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("6억 5,000", 65000),
        ("25억 8,000", 258000),
        ("1억", 10000),
        ("150", 150),
        ("5,000", 5000),
        ("", None),
        (None, None),
    ],
)
def test_parse_korean_price(raw, expected):
    assert parse_korean_price(raw) == expected


def test_cluster_key_ignores_price_uses_areaname():
    a = compute_cluster_key("947", "82A", 2, None, "남향", TradeType.JEONSE)
    b = compute_cluster_key("947", "82A", 2, None, "남향", TradeType.JEONSE)
    assert a == b
    # 평형이 다르면 다른 키
    c = compute_cluster_key("947", "117", 2, None, "남향", TradeType.JEONSE)
    assert a != c
    # 층이 다르면 다른 키
    d = compute_cluster_key("947", "82A", 3, None, "남향", TradeType.JEONSE)
    assert a != d


def test_missing_article_no_raises():
    with pytest.raises(NaverParseError):
        parse_article({"tradeTypeCode": "A1", "dealOrWarrantPrc": "1억"}, complex_no="947")


def test_unknown_trade_raises():
    with pytest.raises(NaverParseError):
        parse_article({"articleNo": "1", "dealOrWarrantPrc": "1억"}, complex_no="947")


def test_extract_body_missing_raises():
    with pytest.raises(NaverParseError):
        extract_article_body({"code": "fail"})


def test_has_more():
    assert has_more({"isMoreData": True}) is True
    assert has_more({"isMoreData": False}) is False
    assert has_more({}) is False


@pytest.mark.parametrize(
    "raw,expected",
    [("20260620", "2026-06-20"), ("24.06.19.", "2024-06-19"), ("", None), ("nope", None)],
)
def test_parse_confirm_date(raw, expected):
    assert parse_confirm_date(raw) == expected
