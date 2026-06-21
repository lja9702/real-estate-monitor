"""원시 JSON(실거래/평형) → 정규화 DTO.

new.land `/api/complexes/{cx}/prices/real` 응답:
  realPriceOnMonthList[].realPriceList[] 원소 기준 —
    tradeType(A1/B1/B2), tradeYear("2025"), tradeMonth(11), tradeDate("21"),
    dealPrice/leasePrice/rentPrice(만원 정수), floor(int), formattedPrice("22억"),
    deleteYn("O" 이면 거래취소). areaNo=0(대표)일 때 면적은 0.0 으로 비어 옴 →
    평형별로 조회하고 면적은 complexPyeongDetailList(PyeongInfo)에서 태깅한다.

`/api/complexes/{cx}?sameAddressGroup=false` 응답:
  complexPyeongDetailList[] — pyeongNo, pyeongName, supplyArea, exclusiveArea, householdCountByPyeong.

구조가 바뀌면 NaverParseError 로 시끄럽게 실패한다(쓰레기 저장 방지).
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel

from ..constants import TRADE_CODE_TO_TYPE, TradeType
from ..util import parse_float
from .errors import NaverParseError


class PyeongInfo(BaseModel):
    """단지 평형 1종 (실거래 면적 태깅·평형 선택용)."""

    pyeong_no: str  # areaNo 로 사용
    pyeong_name: str | None = None  # "80B"
    area_supply: float | None = None  # 공급 ㎡
    area_excl: float | None = None  # 전용 ㎡
    households: int | None = None


class DealDTO(BaseModel):
    """정규화된 실거래 1건 (DB·diff 공유 값 객체)."""

    deal_key: str
    complex_no: str
    trade_type: TradeType
    deal_date: str  # ISO 'YYYY-MM-DD'
    price_deal: int  # 매매가/보증금 (만원)
    price_rent: int | None = None  # 월세 (만원)
    floor: int | None = None
    pyeong_no: str | None = None
    pyeong_name: str | None = None
    area_excl: float | None = None
    area_supply: float | None = None
    cancelled: bool = False


def _to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_pyeongs(detail: dict) -> list[PyeongInfo]:
    """단지 상세 → 평형 목록. complexPyeongDetailList 부재 시 NaverParseError."""
    if not isinstance(detail, dict):
        raise NaverParseError(f"단지상세가 dict 아님: {type(detail)}")
    rows = detail.get("complexPyeongDetailList")
    if rows is None:
        raise NaverParseError(f"평형목록(complexPyeongDetailList) 없음: keys={sorted(detail)[:12]}")
    out: list[PyeongInfo] = []
    for r in rows:
        pno = r.get("pyeongNo")
        if pno is None:
            continue
        out.append(
            PyeongInfo(
                pyeong_no=str(pno),
                pyeong_name=(r.get("pyeongName") or None),
                area_supply=parse_float(r.get("supplyArea") or r.get("supplyAreaDouble")),
                area_excl=parse_float(r.get("exclusiveArea")),
                households=_to_int(r.get("householdCountByPyeong")),
            )
        )
    return out


def _deal_date(row: dict) -> str | None:
    """tradeYear/tradeMonth/tradeDate → 'YYYY-MM-DD'. 불완전하면 None."""
    y = _to_int(row.get("tradeYear"))
    m = _to_int(row.get("tradeMonth"))
    d = _to_int(row.get("tradeDate"))
    if not (y and m and d):
        return None
    try:
        return f"{y:04d}-{m:02d}-{d:02d}"
    except (ValueError, TypeError):
        return None


def _price_fields(row: dict, trade_type: TradeType) -> tuple[int | None, int | None]:
    """거래유형별 (보증금/매매가, 월세) 만원."""
    if trade_type == TradeType.SALE:
        return _to_int(row.get("dealPrice")), None
    if trade_type == TradeType.JEONSE:
        return _to_int(row.get("leasePrice")), None
    # 월세
    return _to_int(row.get("leasePrice")), _to_int(row.get("rentPrice")) or None


def compute_deal_key(
    complex_no: str,
    trade_type: TradeType,
    deal_date: str,
    floor: int | None,
    pyeong_no: str | None,
    price_deal: int,
    price_rent: int | None,
) -> str:
    """실거래 자연키. 취소여부는 제외(취소는 같은 키로 재관측되어 행을 갱신)."""
    raw = (
        f"{complex_no}|{trade_type.value}|{deal_date}|{floor if floor is not None else '?'}"
        f"|{pyeong_no or '?'}|{price_deal}|{price_rent if price_rent is not None else 0}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def extract_real_price_rows(payload: dict) -> list[dict]:
    """응답에서 거래 배열을 평탄화. 구조 불일치 시 NaverParseError."""
    if not isinstance(payload, dict):
        raise NaverParseError(f"실거래 응답이 dict 아님: {type(payload)}")
    months = payload.get("realPriceOnMonthList")
    if months is None:
        raise NaverParseError(
            f"실거래 배열(realPriceOnMonthList) 없음: keys={sorted(payload)[:12]}"
        )
    if not isinstance(months, list):
        raise NaverParseError(f"realPriceOnMonthList 가 list 아님: {type(months)}")
    rows: list[dict] = []
    for m in months:
        for r in m.get("realPriceList", []) or []:
            rows.append(r)
    return rows


def parse_deals(
    payload: dict,
    complex_no: str,
    pyeong: PyeongInfo,
    default_trade_type: TradeType,
) -> list[DealDTO]:
    """평형 1종의 실거래 응답 → DealDTO 리스트. 날짜/가격 결손 행은 조용히 skip."""
    out: list[DealDTO] = []
    for r in extract_real_price_rows(payload):
        code = r.get("tradeType")
        trade_type = TRADE_CODE_TO_TYPE.get(str(code)) if code is not None else None
        if trade_type is None:
            trade_type = default_trade_type
        deal_date = _deal_date(r)
        if deal_date is None:
            continue
        price_deal, price_rent = _price_fields(r, trade_type)
        if price_deal is None:
            continue
        floor = _to_int(r.get("floor"))
        cancelled = str(r.get("deleteYn") or "").upper() == "O"
        key = compute_deal_key(
            complex_no, trade_type, deal_date, floor, pyeong.pyeong_no, price_deal, price_rent
        )
        out.append(
            DealDTO(
                deal_key=key,
                complex_no=complex_no,
                trade_type=trade_type,
                deal_date=deal_date,
                price_deal=price_deal,
                price_rent=price_rent,
                floor=floor,
                pyeong_no=pyeong.pyeong_no,
                pyeong_name=pyeong.pyeong_name,
                area_excl=pyeong.area_excl,
                area_supply=pyeong.area_supply,
                cancelled=cancelled,
            )
        )
    return out
