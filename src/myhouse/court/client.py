"""CourtAuctionClient — courtauction.go.kr 신규시스템 물건상세검색(httpx 직접).

Naver 와 달리 토큰 캡처가 불필요 — warmup GET 으로 세션 쿠키만 받으면 httpx POST 로 조회된다
(seoul.SeoulLandClient 와 같은 경량 패턴). with 문으로 사용. IP 차단(ipcheck=false)을 피하려
요청 사이 랜덤 지연을 둔다 — 차단되면 1시간 이상 같은 IP 로 재시도 불가.
"""

from __future__ import annotations

import json
import logging
import random
import time

import httpx

from .auction_parser import AuctionDTO, parse_auctions
from .case_dxdy_parser import AuctionDateEvent, parse_case_dxdy
from .endpoints import (
    COURT_AUCTION_BASE,
    SEARCH_SUBMISSION_ID,
    USER_AGENT,
    build_case_dxdy_body,
    build_search_body,
    case_dxdy_url,
    courts_url,
    search_referer,
    search_url,
    warmup_url,
)
from .errors import CourtAuctionApiError, CourtAuctionBlockedError

log = logging.getLogger(__name__)


class CourtAuctionClient:
    """법원경매 물건상세검색 클라이언트. 법원+매각기일 범위로 조회."""

    def __init__(
        self,
        timeout: float = 20.0,
        request_delay_seconds: tuple[float, float] = (1.5, 3.0),
        retries: int = 2,
    ) -> None:
        self._delay = request_delay_seconds
        self._retries = retries
        self._retry_base = 1.5  # 백오프 기준(초): 1.5 → 3 → 6 …
        self._search_calls = 0  # 법원 간 간격용 카운터
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            # 연결 재사용(keep-alive)을 끈다 — courtauction 은 유휴 연결을 곧잘 닫아
            # 재사용 시 'Server disconnected'(RemoteProtocolError)가 난다. 매 요청 새 커넥션.
            limits=httpx.Limits(max_keepalive_connections=0),
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            },
        )
        self._warmed = False

    def __enter__(self) -> CourtAuctionClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _sleep(self) -> None:
        time.sleep(random.uniform(*self._delay))

    def _backoff(self, attempt: int, exc: Exception) -> None:
        wait = self._retry_base * (2**attempt) + random.uniform(0, 0.4)
        log.warning(
            "courtauction 일시오류(%s) — %.1fs 후 재시도 %d/%d",
            type(exc).__name__, wait, attempt + 1, self._retries,
        )
        time.sleep(wait)

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response:
        """일시 오류(연결끊김·타임아웃·5xx) 재시도 포함 요청. 재전송은 새 커넥션을 잡아
        stale keep-alive('Server disconnected')를 해소한다. 소진 시 CourtAuctionApiError."""
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = self._client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                last = e
                if e.response.status_code >= 500 and attempt < self._retries:
                    self._backoff(attempt, e)
                    continue
                raise CourtAuctionApiError(f"HTTP {e.response.status_code} — {url}") from e
            except httpx.TransportError as e:  # 연결끊김·타임아웃 등
                last = e
                if attempt < self._retries:
                    self._backoff(attempt, e)
                    continue
                raise CourtAuctionApiError(f"요청 실패 {url}: {e}") from e
        raise CourtAuctionApiError(f"요청 실패 {url}: {last}")  # 방어(도달 불가)

    def _warmup(self) -> None:
        """검색 화면 GET 으로 세션 쿠키 획득(1회). httpx 쿠키잔류로 이후 POST 에 자동 첨부."""
        if self._warmed:
            return
        self._send("GET", warmup_url(), headers={"Accept": "text/html,*/*"})
        self._warmed = True

    def _post_json(
        self,
        url: str,
        body: dict,
        *,
        submission_id: str | None = None,
        sc_userid: bool = False,
    ) -> dict:
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": COURT_AUCTION_BASE,
            "Referer": search_referer(),
            "X-Requested-With": "XMLHttpRequest",
        }
        if submission_id:
            headers["submissionid"] = submission_id
        if submission_id or sc_userid:
            headers["sc-userid"] = "SYSTEM"
        resp = self._send(
            "POST", url, content=json.dumps(body).encode("utf-8"), headers=headers
        )
        try:
            payload = resp.json()
        except ValueError as e:  # JSON 디코드 실패
            raise CourtAuctionApiError(f"JSON 파싱 실패 {url}: {e}") from e

        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and data.get("ipcheck") is False:
            raise CourtAuctionBlockedError(
                "IP 차단(ipcheck=false) — 1시간 이상 대기 후 재시도하세요."
            )
        return payload

    def fetch_courts(self) -> dict[str, str]:
        """법원코드→이름 맵 {'B000210': '서울중앙지방법원', …}. 실패 시 빈 dict(베스트에포트)."""
        self._warmup()
        try:
            payload = self._post_json(courts_url(), {})
        except CourtAuctionApiError as e:
            log.debug("법원목록 조회 실패: %s", e)
            return {}
        data = payload.get("data") or {}
        rows = data.get("result") if isinstance(data, dict) else None
        out: dict[str, str] = {}
        for r in rows or []:
            code = _clean_str(r.get("cortOfcCd"))
            name = _clean_str(r.get("cortOfcNm"))
            if code and name:
                out[code] = name
        return out

    def fetch_auctions(
        self,
        court_code: str,
        begin_ymd: str,
        end_ymd: str,
        *,
        page_size: int = 40,
        max_pages: int = 10,
    ) -> list[AuctionDTO]:
        """법원 1곳의 매각기일 범위 물건(아파트 무필터). 페이지네이션으로 전부 수집."""
        if self._search_calls > 0:
            self._sleep()  # 법원 간 간격 — 연속요청 throttle/연결끊김 회피
        self._search_calls += 1
        self._warmup()
        out: list[AuctionDTO] = []
        page = 1
        while page <= max_pages:
            body = build_search_body(
                court_code, begin_ymd, end_ymd, page_no=page, page_size=page_size
            )
            payload = self._post_json(search_url(), body, submission_id=SEARCH_SUBMISSION_ID)
            dtos = parse_auctions(payload)
            out.extend(dtos)

            data = payload.get("data") or {}
            total = int((data.get("dma_pageInfo") or {}).get("totalCnt") or 0)
            if not dtos or page * page_size >= total:
                break
            page += 1
            self._sleep()
        return out

    def fetch_case_dxdy(self, court_code: str, cs_no: str) -> list[AuctionDateEvent]:
        """사건 1건의 기일내역(매각/유찰/미납 결과·낙찰가·다음기일). 매각기일 지난 물건 정합용.

        cs_no 는 내부 csNo(case_no_to_csno). 빈 응답(사건 없음)은 빈 리스트.
        """
        self._sleep()  # 정합은 사건별 1콜 — throttle
        self._warmup()
        payload = self._post_json(case_dxdy_url(), build_case_dxdy_body(court_code, cs_no), sc_userid=True)
        return parse_case_dxdy(payload)


def _clean_str(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None
