"""new.land.naver.com API URL 빌더.

⚠️ 비공식 엔드포인트. wire 지식을 이 파일에 모은다.
가격/면적 필터는 서버측 단위가 모호해 항상 무제한으로 요청하고 클라이언트에서 거른다.
"""

from __future__ import annotations

from urllib.parse import urlencode

NEW_LAND_BASE = "https://new.land.naver.com"
ARTICLES_PATH = "/api/articles/complex"          # /{complexNo}
SINGLE_MARKERS_PATH = "/api/complexes/single-markers/2.0"
COMPLEX_INFO_PATH = "/api/complexes"              # /{complexNo}
SEARCH_PATH = "/api/search"                       # ?keyword= (단지명/주소 → 단지목록·지역)

# 아파트:아파트분양권:재건축 — 삼호1차 같은 재건축(JGC)도 포함하려면 필수
DEFAULT_REAL_ESTATE = "APT:ABYG:JGC"
MAX_PAGES = 50

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def build_article_url(
    complex_no: str,
    trade_codes: list[str],
    real_estate_type: str = DEFAULT_REAL_ESTATE,
    page: int = 1,
) -> str:
    """단지 매물 목록 URL. 가격/면적은 무제한으로 받고 클라이언트에서 필터링."""
    params = {
        "realEstateType": real_estate_type or DEFAULT_REAL_ESTATE,
        "tradeType": ":".join(trade_codes),
        "rentPriceMin": 0,
        "rentPriceMax": 900000000,
        "priceMin": 0,
        "priceMax": 900000000,
        "areaMin": 0,
        "areaMax": 900000000,
        "showArticle": "false",
        "sameAddressGroup": "false",
        "priceType": "RETAIL",
        "page": page,
        "type": "list",
        "order": "rank",
    }
    return f"{NEW_LAND_BASE}{ARTICLES_PATH}/{complex_no}?{urlencode(params)}"


def build_article_detail_url(article_no: str) -> str:
    return f"{NEW_LAND_BASE}/api/articles/{article_no}"


def build_search_url(keyword: str) -> str:
    """단지명/주소 키워드 검색 URL. 응답 `complexes[]`(complexNo·complexName·cortarAddress 등)."""
    return f"{NEW_LAND_BASE}{SEARCH_PATH}?{urlencode({'keyword': keyword})}"


def search_referer(keyword: str) -> str:
    return f"{NEW_LAND_BASE}/search?{urlencode({'query': keyword})}"


def complex_referer(complex_no: str) -> str:
    return f"{NEW_LAND_BASE}/complexes/{complex_no}"


def build_complex_info_url(complex_no: str) -> str:
    return f"{NEW_LAND_BASE}{COMPLEX_INFO_PATH}/{complex_no}"


def build_complex_detail_url(complex_no: str) -> str:
    """단지 상세 — complexPyeongDetailList(평형별 면적/세대수) 포함."""
    return f"{NEW_LAND_BASE}{COMPLEX_INFO_PATH}/{complex_no}?sameAddressGroup=false"


def build_single_markers_url(
    *,
    bbox: tuple[float, float, float, float],
    cortar_no: str = "",
    zoom: int = 13,
    real_estate_type: str = DEFAULT_REAL_ESTATE,
    trade_code: str = "A1",
    price_min: int = 0,
    price_max: int = 900000000,
    area_min: float = 0,
    area_max: float = 900000000,
    min_households: int | None = None,
) -> str:
    """지도 bbox 내 단지 마커 목록 URL (지역 단지 자동탐색).

    bbox = (leftLon, rightLon, topLat, bottomLat). 응답은 마커 list 이며 거래가 있는
    단지는 minDealPrice/maxDealPrice/medianDealPrice(만원)·totalHouseholdCount·minArea/maxArea
    를 포함한다(거래 없는 단지는 가격 필드 누락).

    ⚠️ 라이브 검증(2026-06): bbox 1회당 최대 500개로 캡되고, cortarNo 는 서버측 필터가
    아니다(bbox 가 유일한 지리 경계). 단, priceMin/priceMax·areaMin/areaMax·minHouseHoldCount
    는 서버측에서 먹으므로, 15~26억·세대수 필터를 걸면 결과가 캡 아래로 줄어 구당 1회로
    완전 수집된다. cortarNo 는 referer/맥락용으로만 전달한다.
    """
    left, right, top, bottom = bbox
    params: dict[str, object] = {
        "cortarNo": cortar_no,
        "zoom": zoom,
        "priceType": "RETAIL",
        "markerType": "",
        "realEstateType": real_estate_type or DEFAULT_REAL_ESTATE,
        "tradeType": trade_code,
        "tag": "::::::::",
        "rentPriceMin": 0,
        "rentPriceMax": 900000000,
        "priceMin": price_min,
        "priceMax": price_max,
        "areaMin": area_min,
        "areaMax": area_max,
        "oldBuildYears": "",
        "recentlyBuildYears": "",
        "minHouseHoldCount": min_households if min_households is not None else "",
        "maxHouseHoldCount": "",
        "showArticle": "false",
        "sameAddressGroup": "false",
        "minMaintenanceCost": "",
        "maxMaintenanceCost": "",
        "directions": "",
        "leftLon": left,
        "rightLon": right,
        "topLat": top,
        "bottomLat": bottom,
        "isPresale": "false",
    }
    return f"{NEW_LAND_BASE}{SINGLE_MARKERS_PATH}?{urlencode(params)}"


def build_real_price_url(
    complex_no: str,
    trade_code: str,
    area_no: str | int = 0,
    year: int = 3,
) -> str:
    """평형(areaNo)별 실거래 내역 URL. areaNo=0 은 대표 평형.

    응답: realPriceOnMonthList[].realPriceList[] (거래일/dealPrice/floor/deleteYn 등).
    year 는 조회 기간(년). 최신 거래가 앞에 온다.
    """
    params = {
        "tradeType": trade_code,
        "year": year,
        "priceChartChange": "false",
        "areaNo": area_no,
        "areaChange": "false",
        "type": "table",
    }
    return f"{NEW_LAND_BASE}{COMPLEX_INFO_PATH}/{complex_no}/prices/real?{urlencode(params)}"
