"""지역 단지 탐색 — new.land single-markers 응답 파싱.

single-markers 엔드포인트는 지도 bbox 내 모든 단지를 마커로 반환한다:
  markerId(=complexNo), complexName, latitude/longitude, totalHouseholdCount,
  realEstateTypeCode/Name, minArea/maxArea, dealCount, 그리고 거래가 있는 단지는
  minDealPrice/maxDealPrice/medianDealPrice(만원). 거래 없는 단지는 가격 필드가 누락된다.

`core/discover` 가 주간 신규편입 단지 탐색에 쓴다(가격/세대수/면적은 서버측 필터로 1차 거름).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..settings import DiscoverSpec
from ..util import parse_float
from .errors import NaverParseError


@dataclass
class DiscoveredComplex:
    complex_no: str
    name: str
    total_households: int | None
    lat: float | None
    lon: float | None
    real_estate_type: str | None
    deal_count: int | None = None
    real_estate_type_name: str | None = None
    min_deal_price: int | None = None  # 만원
    max_deal_price: int | None = None  # 만원
    median_deal_price: int | None = None  # 만원
    min_area: float | None = None  # 공급면적 추정 ㎡ (마커 minArea)
    max_area: float | None = None  # 공급면적 추정 ㎡ (마커 maxArea)
    region: str | None = None  # 탐색에 사용한 config 지역 라벨(best-effort)


def _to_int(v: object) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def extract_markers(payload: object) -> list[dict]:
    """마커 배열 추출. 응답이 list 면 그대로, dict 면 흔한 키들을 시도."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("complexList", "markerList", "result"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
    raise NaverParseError(f"마커 배열 없음: {type(payload)}")


def parse_marker(raw: dict) -> DiscoveredComplex | None:
    no = raw.get("markerId") or raw.get("complexNo")
    if not no or raw.get("markerType", "COMPLEX") != "COMPLEX":
        return None
    return DiscoveredComplex(
        complex_no=str(no),
        name=raw.get("complexName") or "",
        total_households=_to_int(raw.get("totalHouseholdCount")),
        lat=parse_float(raw.get("latitude")),
        lon=parse_float(raw.get("longitude")),
        real_estate_type=raw.get("realEstateTypeCode"),
        real_estate_type_name=raw.get("realEstateTypeName"),
        deal_count=_to_int(raw.get("dealCount")),
        min_deal_price=_to_int(raw.get("minDealPrice")),
        max_deal_price=_to_int(raw.get("maxDealPrice")),
        median_deal_price=_to_int(raw.get("medianDealPrice")),
        min_area=parse_float(raw.get("minArea")),
        max_area=parse_float(raw.get("maxArea")),
    )


def passes_discover(dc: DiscoveredComplex, spec: DiscoverSpec) -> bool:
    if spec.min_total_households is not None and (
        dc.total_households is None or dc.total_households < spec.min_total_households
    ):
        return False
    if spec.name_includes and not any(s in dc.name for s in spec.name_includes):
        return False
    if spec.name_excludes and any(s in dc.name for s in spec.name_excludes):
        return False
    return True


def in_price_band(dc: DiscoveredComplex, price_min: int, price_max: int) -> bool:
    """단지 호가범위(min~maxDealPrice)가 [price_min, price_max] 만원과 겹치는가.

    마커는 단지 전체 평형의 최저~최고 호가다. 한 평형이라도 밴드에 들면 후보로 본다(겹침 판정).
    가격 정보가 없는 단지(거래 0)는 False.
    """
    if dc.min_deal_price is None or dc.max_deal_price is None:
        return False
    return dc.max_deal_price >= price_min and dc.min_deal_price <= price_max
