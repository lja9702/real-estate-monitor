"""경매 물건 상세(기일내역) 온디맨드 조회 — 앱 내 상세 패널용.

공식 courtauction 신시스템은 SPA 라 물건별 딥링크 URL 이 없다(상세에 들어가도 URL 이
일반 검색 주소 그대로). 그래서 상세를 외부로 링크하는 대신 우리 대시보드에서 직접 보여준다.
사건 기일내역(매각/유찰 이력·최저가·다음기일)을 법원에서 받아 짧게 캐시한다 — 매 클릭마다
법원을 때리지 않도록 메모리 TTL 캐시. cloud_readonly(쓰기·수집 금지) 환경에선 라이브 fetch 를
하지 않고 가진 것만 돌려준다(맥 대시보드가 1차 surface).
"""

from __future__ import annotations

import logging
import time

from ..court.case_dxdy_parser import AuctionDateEvent
from ..court.client import CourtAuctionClient
from ..court.endpoints import case_no_to_csno
from ..court.errors import CourtAuctionApiError, CourtAuctionParseError
from ..db.models import Auction

log = logging.getLogger(__name__)

# auction_key → (만료 epoch, 기일내역). 프로세스 메모리 캐시(대시보드 단일 프로세스).
_CACHE: dict[str, tuple[float, list[AuctionDateEvent]]] = {}
_TTL_SECONDS = 6 * 3600  # 6시간 — 기일내역은 자주 안 바뀐다


def _now() -> float:
    return time.time()


def get_case_events(
    row: Auction,
    *,
    allow_fetch: bool = True,
    delay: tuple[float, float] = (1.0, 2.0),
) -> list[AuctionDateEvent]:
    """물건 1건의 기일내역. TTL 캐시 우선, 만료/없음이면 라이브 1회 fetch(allow_fetch).

    allow_fetch=False(예: cloud_readonly) 면 라이브 호출 없이 캐시만(없으면 빈 리스트).
    사건번호가 타경 형식이 아니거나 법원코드 결손이면 빈 리스트.
    """
    hit = _CACHE.get(row.auction_key)
    if hit and hit[0] > _now():
        return hit[1]
    if not allow_fetch:
        return hit[1] if hit else []

    cs_no = case_no_to_csno(row.case_no or "")
    if not (cs_no and row.court_code):
        return hit[1] if hit else []

    try:
        with CourtAuctionClient(request_delay_seconds=delay) as client:
            events = client.fetch_case_dxdy(row.court_code, cs_no)
    except (CourtAuctionApiError, CourtAuctionParseError) as e:
        log.warning("기일내역 조회 실패 %s(%s): %s", row.case_no, row.court_code, e)
        return hit[1] if hit else []

    _CACHE[row.auction_key] = (_now() + _TTL_SECONDS, events)
    return events


def clear_cache() -> None:
    """테스트/디버그용 캐시 비우기."""
    _CACHE.clear()


__all__ = ["get_case_events", "clear_cache"]
