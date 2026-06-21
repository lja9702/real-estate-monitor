"""NaverLandClient — new.land 매물 수집(Playwright 세션 기반) 및 DTO 변환."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from ..constants import NAVER_TRADE_CODE, TRADE_CODE_TO_TYPE, TradeType
from ..settings import DiscoverConfig, FilterSpec, RegionSpec
from .browser import NaverBrowser
from .complex_parser import ComplexMeta, parse_complex_meta
from .deal_parser import DealDTO, PyeongInfo, parse_deals, parse_pyeongs
from .endpoints import (
    MAX_PAGES,
    build_article_detail_url,
    build_article_url,
    build_complex_detail_url,
    build_complex_info_url,
    build_real_price_url,
    build_search_url,
    build_single_markers_url,
    complex_referer,
    search_referer,
)
from .errors import NaverApiError, NaverParseError
from .parser import ArticleDTO, extract_article_body, has_more, parse_article
from .regions import DiscoveredComplex, extract_markers, parse_marker
from .search_parser import SearchHit, parse_search

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """단지 1개 수집 결과."""

    complex_no: str
    articles: list[ArticleDTO]
    complete: bool  # True 면 마지막 페이지까지 정상 도달(삭제 판정 가능)
    pages: int = 0
    raw_count: int = 0
    parse_failures: int = 0


@dataclass
class DealFetchResult:
    """단지 1개 실거래 수집 결과. (deals 는 append-only 라 complete 는 참고용)."""

    complex_no: str
    deals: list[DealDTO]
    complete: bool
    pyeongs: int = 0
    raw_count: int = 0


def _passes_client_filters(dto: ArticleDTO, filt: FilterSpec) -> bool:
    """가격/면적/층 필터를 클라이언트에서 적용(서버측 단위가 모호하므로)."""
    if filt.floor_min is not None and dto.floor_num is not None and dto.floor_num < filt.floor_min:
        return False
    if (
        filt.area_excl_min_m2 is not None
        and dto.area_excl is not None
        and dto.area_excl < filt.area_excl_min_m2
    ):
        return False
    if (
        filt.area_excl_max_m2 is not None
        and dto.area_excl is not None
        and dto.area_excl > filt.area_excl_max_m2
    ):
        return False
    if (
        filt.area_supply_min_m2 is not None
        and dto.area_supply is not None
        and dto.area_supply < filt.area_supply_min_m2
    ):
        return False
    if (
        filt.area_supply_max_m2 is not None
        and dto.area_supply is not None
        and dto.area_supply > filt.area_supply_max_m2
    ):
        return False
    if (
        filt.price_min_manwon is not None
        and dto.price_deal is not None
        and dto.price_deal < filt.price_min_manwon
    ):
        return False
    if (
        filt.price_max_manwon is not None
        and dto.price_deal is not None
        and dto.price_deal > filt.price_max_manwon
    ):
        return False
    return True


class NaverLandClient:
    """new.land 매물 클라이언트. with 문으로 브라우저 세션을 연다."""

    def __init__(
        self,
        request_delay_seconds: tuple[float, float] = (1.0, 3.0),
        headless: bool = True,
        browser: NaverBrowser | None = None,
    ):
        self._delay = request_delay_seconds
        self._browser = browser or NaverBrowser(headless=headless)
        self._owns_browser = browser is None

    def __enter__(self) -> NaverLandClient:
        if self._owns_browser:
            self._browser.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_browser:
            self._browser.close()

    def fetch_articles(self, complex_row, filt: FilterSpec) -> FetchResult:
        """단지의 모든 매물을 페이지네이션으로 수집해 ArticleDTO 리스트로 반환.

        complete=False 면 수집이 중단된 것이므로 호출측은 삭제 판정을 생략해야 한다.
        """
        complex_no = str(complex_row.complex_no)
        # 첫 호출 시 이 단지 페이지로 토큰 캡처(이후 재사용)
        self._browser.ensure_token(complex_no)

        trade_codes = [NAVER_TRADE_CODE[t] for t in filt.trade_types]
        referer = complex_referer(complex_no)
        raw_by_id: dict[str, dict] = {}
        pages = 0
        complete = True

        try:
            for page in range(1, MAX_PAGES + 1):
                url = build_article_url(complex_no, trade_codes, filt.real_estate_type, page)
                payload = self._browser.fetch_json(url, referer)
                body = extract_article_body(payload)
                pages += 1
                for item in body:
                    aid = str(item.get("articleNo") or "")
                    if aid:
                        raw_by_id.setdefault(aid, item)
                if not body or not has_more(payload):
                    break
                time.sleep(random.uniform(*self._delay))
        except NaverApiError as e:
            log.warning("단지 %s 수집 불완전(삭제 판정 생략): %s", complex_no, e)
            complete = False

        articles: list[ArticleDTO] = []
        parse_failures = 0
        for raw in raw_by_id.values():
            try:
                dto = parse_article(raw, complex_no)
            except NaverParseError as e:
                parse_failures += 1
                log.debug("매물 파싱 실패 skip: %s", e)
                continue
            if _passes_client_filters(dto, filt):
                articles.append(dto)

        if raw_by_id and parse_failures == len(raw_by_id):
            raise NaverParseError(
                f"단지 {complex_no}: 매물 {len(raw_by_id)}건 전부 파싱 실패 — 응답 구조 변경 의심"
            )

        return FetchResult(
            complex_no=complex_no,
            articles=articles,
            complete=complete,
            pages=pages,
            raw_count=len(raw_by_id),
            parse_failures=parse_failures,
        )

    def fetch_pyeongs(self, complex_no: str) -> list[PyeongInfo]:
        """단지 상세에서 평형 목록(면적/세대수) 조회. 실패 시 NaverApiError/NaverParseError."""
        self._browser.ensure_token(complex_no)
        referer = complex_referer(complex_no)
        detail = self._browser.fetch_json(build_complex_detail_url(complex_no), referer)
        return parse_pyeongs(detail)

    def fetch_deals(
        self,
        complex_no: str,
        pyeongs: list[PyeongInfo],
        trade_codes: list[str],
        year: int = 3,
    ) -> DealFetchResult:
        """선택된 평형 × 거래유형별로 실거래를 수집해 DealDTO 리스트로 반환.

        실거래는 append-only(과거 사실)라 일부 평형이 실패해도 손실 위험이 없다 —
        complete=False 면 이번 회차에 일부 신규/취소를 놓쳤을 수 있을 뿐(다음 회차에 포착).
        """
        self._browser.ensure_token(complex_no)
        referer = complex_referer(complex_no)
        deals: list[DealDTO] = []
        raw = 0
        complete = True
        first = True

        for pyeong in pyeongs:
            for code in trade_codes:
                if not first:
                    time.sleep(random.uniform(*self._delay))
                first = False
                url = build_real_price_url(complex_no, code, pyeong.pyeong_no, year)
                try:
                    payload = self._browser.fetch_json(url, referer)
                except NaverApiError as e:
                    log.warning(
                        "단지 %s 평형 %s(%s) 실거래 수집 실패: %s",
                        complex_no, pyeong.pyeong_no, code, e,
                    )
                    complete = False
                    continue
                trade_type = TRADE_CODE_TO_TYPE.get(code, TradeType.SALE)
                try:
                    dtos = parse_deals(payload, complex_no, pyeong, trade_type)
                except NaverParseError as e:
                    log.debug("단지 %s 평형 %s 실거래 파싱 실패: %s", complex_no, pyeong.pyeong_no, e)
                    complete = False
                    continue
                raw += len(dtos)
                deals.extend(dtos)

        return DealFetchResult(
            complex_no=complex_no, deals=deals, complete=complete,
            pyeongs=len(pyeongs), raw_count=raw,
        )

    def fetch_complex_meta(self, complex_no: str) -> ComplexMeta | None:
        """단지 상세 API로 단지 메타(세대수/동수/사용승인일/용적률/건폐율 + 좌표) 조회.

        좌표/이름과 같은 단지정보 응답(complexDetail 아래 중첩)에서 뽑는다. 실패 시 None —
        메타는 부가정보라 호출측이 그냥 건너뛴다(쓰레기 저장 위험 없음).
        """
        try:
            self._browser.ensure_token(complex_no)
            referer = complex_referer(complex_no)
            data = self._browser.fetch_json(build_complex_info_url(complex_no), referer)
        except Exception as e:  # noqa: BLE001
            log.debug("단지 %s 메타 조회 실패: %s", complex_no, e)
            return None
        return parse_complex_meta(data)

    def fetch_complex_coords(self, complex_no: str) -> tuple[float, float] | None:
        """단지 상세 API로 좌표(lat, lon) 반환. 실패 시 None."""
        try:
            self._browser.ensure_token(complex_no)
            referer = complex_referer(complex_no)
            data = self._browser.fetch_json(build_complex_info_url(complex_no), referer)
            detail = data.get("complexDetail") or data  # 응답이 complexDetail 아래에 중첩
            lat = detail.get("latitude")
            lon = detail.get("longitude")
            if lat and lon:
                return float(lat), float(lon)
            return None
        except Exception as e:
            log.debug("단지 %s 좌표 조회 실패: %s", complex_no, e)
            return None

    def fetch_complex_jibun(self, complex_no: str) -> tuple[str | None, str | None] | None:
        """단지 상세 API로 (법정동코드 cortarNo, 지번 detailAddress) 반환. 실패 시 None.

        토지거래허가 매칭용. detailAddress 정규화(본번/부번 분리)는 호출측(core)에서 한다 —
        여기선 raw 값만 넘겨 naver 패키지가 seoul 도메인 규칙에 의존하지 않게 한다.
        """
        try:
            self._browser.ensure_token(complex_no)
            referer = complex_referer(complex_no)
            data = self._browser.fetch_json(build_complex_info_url(complex_no), referer)
            detail = data.get("complexDetail") or data  # 응답이 complexDetail 아래에 중첩
            cortar = detail.get("cortarNo")
            jibun = detail.get("detailAddress")
            return (str(cortar) if cortar else None, str(jibun) if jibun else None)
        except Exception as e:  # noqa: BLE001
            log.debug("단지 %s 지번 조회 실패: %s", complex_no, e)
            return None

    def fetch_complex_name(self, complex_no: str) -> str | None:
        """단지 상세 API로 단지명을 best-effort 조회. 실패/미발견 시 None.

        좌표와 같은 단지정보 응답(complexDetail 아래 중첩)에서 complexName 을 읽는다.
        실패해도 호출측이 별칭/번호로 대체하므로 안전(쓰레기 저장 위험 없음).
        """
        try:
            self._browser.ensure_token(complex_no)
            referer = complex_referer(complex_no)
            data = self._browser.fetch_json(build_complex_info_url(complex_no), referer)
        except Exception as e:  # noqa: BLE001
            log.debug("단지 %s 이름 조회 실패: %s", complex_no, e)
            return None
        detail = data.get("complexDetail") if isinstance(data, dict) else None
        for src in (detail, data):
            if isinstance(src, dict):
                name = src.get("complexName") or src.get("complexName1")
                if isinstance(name, str) and name.strip():
                    return name.strip()
        return None

    def fetch_markers(
        self, region: RegionSpec, disc: DiscoverConfig, *, seed_complex_no: str
    ) -> list[DiscoveredComplex]:
        """지역 bbox 안의 단지 마커를 서버측 필터(가격/면적/세대수)와 함께 조회.

        토큰은 seed 단지로 발급한다(마커 조회만으로는 토큰 시드가 없으므로). 반환된 마커 중
        가격 정보가 있는 COMPLEX 만 DiscoveredComplex 로 파싱해 region 라벨을 태깅한다.
        bbox 1회 응답이 500개로 캡되므로(라이브 검증), 캡에 닿으면 경고하고 호출측이 처리한다.
        """
        self._browser.ensure_token(seed_complex_no)
        url = build_single_markers_url(
            bbox=region.bbox_tuple,
            cortar_no=region.cortar_no,
            zoom=disc.zoom,
            real_estate_type=disc.real_estate_type,
            trade_code=NAVER_TRADE_CODE[disc.trade_type],
            price_min=disc.price_min_manwon,
            price_max=disc.price_max_manwon,
            area_min=disc.area_supply_min_m2 if disc.area_supply_min_m2 is not None else 0,
            area_max=disc.area_supply_max_m2 if disc.area_supply_max_m2 is not None else 900000000,
            min_households=disc.min_households,
        )
        payload = self._browser.fetch_json(url, complex_referer(seed_complex_no))
        markers = extract_markers(payload)
        out: list[DiscoveredComplex] = []
        for raw in markers:
            dc = parse_marker(raw)
            if dc is None or dc.min_deal_price is None:
                continue  # 가격 없는 단지(거래 0)는 후보 아님
            dc.region = region.name
            out.append(dc)
        if len(markers) >= 500:
            log.warning(
                "지역 '%s' 마커 500개 캡 도달 — bbox 가 너무 넓거나 필터가 느슨함(누락 가능)",
                region.name,
            )
        return out

    def search_complexes(self, keyword: str, *, seed_complex_no: str) -> list[SearchHit]:
        """단지명/주소 키워드로 단지 후보를 검색(주소→단지번호 역추적).

        토큰은 seed 단지 페이지로 발급한다(검색만으로는 토큰 시드가 없으므로). 검색은
        best-effort — 결과 없음은 빈 리스트, 네트워크/HTTP 오류만 NaverApiError 로 전파한다.
        """
        self._browser.ensure_token(seed_complex_no)
        payload = self._browser.fetch_json(build_search_url(keyword), search_referer(keyword))
        return parse_search(payload)

    def fetch_complex_address(self, complex_no: str, article_no: str) -> str | None:
        """매물 상세 API로 단지 주소(서울시 서초구 방배동) 반환. 실패 시 None."""
        try:
            referer = complex_referer(complex_no)
            detail = self._browser.fetch_json(build_article_detail_url(article_no), referer)
            ad = detail.get("articleDetail") or {}
            return ad.get("exposureAddress") or None
        except Exception as e:
            log.debug("단지 %s 주소 조회 실패: %s", complex_no, e)
            return None
