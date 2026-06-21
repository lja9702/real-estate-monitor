"""new.land 검색 응답 → 단지 후보(SearchHit).

`/api/search?keyword=` 응답(라이브 검증 2026-06):
  {"complexes": [{complexNo, complexName, cortarNo, cortarAddress("서울시 서초구 방배동"),
                  realEstateTypeName("재건축"), totalHouseholdCount, latitude, longitude, ...}],
   "regions": [...], "isMoreData", "totalCount", "keyword"}

주소/단지명으로 단지번호를 역추적하는 데 쓴다. 검색은 best-effort(UX)라 구조가 비거나 어긋나도
예외 대신 빈 리스트를 반환한다(호출측은 '못 찾음'으로 처리).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from ..util import parse_float

log = logging.getLogger(__name__)


class SearchHit(BaseModel):
    """검색 결과 단지 1건 (주소→단지번호 역추적용)."""

    complex_no: str
    name: str
    address: str | None = None  # cortarAddress (구/동 수준)
    cortar_no: str | None = None
    type_name: str | None = None  # realEstateTypeName ("아파트"/"재건축"/"분양권")
    households: int | None = None
    lat: float | None = None
    lon: float | None = None


def _to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_search(payload: dict) -> list[SearchHit]:
    """검색 응답 → SearchHit 리스트. complexes 부재/형식오류는 조용히 빈 리스트."""
    if not isinstance(payload, dict):
        log.debug("검색 응답이 dict 아님: %s", type(payload))
        return []
    rows = payload.get("complexes")
    if not isinstance(rows, list):
        return []
    hits: list[SearchHit] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        no = r.get("complexNo")
        if no in (None, ""):
            continue
        hits.append(
            SearchHit(
                complex_no=str(no),
                name=(r.get("complexName") or str(no)),
                address=(r.get("cortarAddress") or None),
                cortar_no=(str(r["cortarNo"]) if r.get("cortarNo") else None),
                type_name=(r.get("realEstateTypeName") or None),
                households=_to_int(r.get("totalHouseholdCount")),
                lat=parse_float(r.get("latitude")),
                lon=parse_float(r.get("longitude")),
            )
        )
    return hits
