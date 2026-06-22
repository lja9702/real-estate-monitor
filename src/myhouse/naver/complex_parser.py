"""원시 JSON(단지상세) → 단지 메타 DTO.

new.land `/api/complexes/{cx}` 응답의 `complexDetail` 아래에서 단지 기본 정보를 뽑는다:
  totalHouseholdCount(총세대수), totalDongCount(총동수), useApproveYmd(사용승인일 'YYYYMMDD'),
  batlRatio(용적률 %), btlRatio(건폐율 %), latitude/longitude.

라이브 검증(2026-06): 947 삼호1차=419세대·3동·19751128·용적률238%·건폐율23%,
971 대치현대=630세대·8동·19990614·용적률341%·건폐율23%. 용적률(batlRatio)은 항상
건폐율(btlRatio)보다 크다(정의상). 값이 문자열('238')로 오므로 int 로 정규화한다.

메타는 부가정보다 — 평형(deal_parser)과 달리 누락돼도 표시만 생략하면 되므로
NaverParseError 를 던지지 않고 best-effort 로 채운다(좌표/이름 파서와 같은 정책).
"""

from __future__ import annotations

from pydantic import BaseModel

from ..util import parse_float


class ComplexMeta(BaseModel):
    """단지 기본 메타 (세대수/동수/준공/용적률/건폐율 + 좌표)."""

    total_households: int | None = None
    total_dong_count: int | None = None
    use_approve_ymd: str | None = None  # 'YYYYMMDD'
    floor_area_ratio: int | None = None  # 용적률 %
    building_coverage_ratio: int | None = None  # 건폐율 %
    lat: float | None = None
    lon: float | None = None


def _to_int(value: object) -> int | None:
    """'238' / 238 / 238.0 / '' / None → int | None (소수 문자열도 허용)."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_ymd(value: object) -> str | None:
    """사용승인일/입주예정일 → 숫자만. 8자리(YYYYMMDD·준공) 또는 6자리(YYYYMM·입주예정)만 통과.

    신규 분양권/입주권 단지는 아직 준공 전이라 네이버가 사용승인일(8자리) 대신 입주예정월을
    6자리(YYYYMM)로 준다(라이브 확인: 광명자이더샵포레나 '202512', 청량리롯데캐슬하이루체
    '202604'). 자릿수로 준공/입주예정을 구분하므로 정규화하지 않고 원본 자릿수를 보존한다
    (표시는 format_use_approve, 연도 추출은 앞 4자리라 6/8 모두 동작)."""
    if value is None:
        return None
    s = str(value).strip().replace(".", "").replace("-", "")
    return s if s.isdigit() and len(s) in (6, 8) else None


def parse_complex_meta(payload: dict) -> ComplexMeta:
    """단지상세 응답 → ComplexMeta. complexDetail 중첩을 해제하고 best-effort 로 채운다."""
    detail = (payload.get("complexDetail") if isinstance(payload, dict) else None) or payload
    if not isinstance(detail, dict):
        return ComplexMeta()
    return ComplexMeta(
        total_households=_to_int(detail.get("totalHouseholdCount")),
        total_dong_count=_to_int(detail.get("totalDongCount")),
        use_approve_ymd=_clean_ymd(detail.get("useApproveYmd")),
        floor_area_ratio=_to_int(detail.get("batlRatio")),
        building_coverage_ratio=_to_int(detail.get("btlRatio")),
        lat=parse_float(detail.get("latitude")),
        lon=parse_float(detail.get("longitude")),
    )
