"""법원경매 수집 1회 오케스트레이션 — 추적단지→관할법원 그룹→fetch→지번매칭→diff→upsert→알림.

토지거래허가(permit_collector.py)와 형제 구조. courtauction.go.kr 신규시스템을 법원 단위로
조회(매각기일 윈도우)하고, 추적단지 지번(cortar_no[:8] + 본번/부번)에 매칭된 아파트 물건만
저장한다. 허가와 달리 물건이 살아 움직이므로 신규(NEW)·최저가하락(PRICE_DOWN)·기일변경을 알린다.

지역(구) 직접검색은 입력코드 체계가 달라(미검증) 법원 단위로 받아 로컬 지번매칭한다 — permits 의
자치구 단위 패턴과 동일·더 견고. 관할법원 맵은 아래 COURT_BY_SIGUNGU(법정동 시군구 5자리 기준).
지번 미백필 단지는 이번 회차 매칭에서 빠진다(fill-jibun 으로 채운다 — 허가와 공유).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from ..constants import RunStatus, now_kst, to_iso
from ..court.auction1_link import auction1_search_url, court_case_search_url
from ..court.auction1_resolver import resolve_view_url
from ..court.auction_parser import AuctionDTO
from ..court.client import CourtAuctionClient
from ..court.errors import CourtAuctionApiError, CourtAuctionParseError
from ..db import repo
from ..db.engine import get_session, set_meta
from ..db.models import Auction
from ..settings import Config, Settings
from .auction_diff import DATE_CHANGED, NEW, PRICE_DOWN, AuctionOp, diff_auctions
from .collector import _acquire_lock
from .targets import ResolvedTarget, resolve_targets

log = logging.getLogger(__name__)

# 추적단지 시군구(법정동 5자리) → 관할 경매법원 코드. courtauction selectCortOfcCdLst 기준.
# 우리 추적지역(서울 + 과천·성남·용인) 관할만 — 누락 시군구는 수집에서 빠지며 경고한다.
COURT_BY_SIGUNGU: dict[str, str] = {
    # 서울중앙(B000210): 종로·중구·강남·서초·관악·동작
    "11110": "B000210", "11140": "B000210", "11680": "B000210",
    "11650": "B000210", "11620": "B000210", "11590": "B000210",
    # 서울동부(B000211): 성동·광진·강동·송파
    "11200": "B000211", "11215": "B000211", "11740": "B000211", "11710": "B000211",
    # 서울남부(B000212): 영등포·강서·양천·구로·금천
    "11560": "B000212", "11500": "B000212", "11470": "B000212",
    "11530": "B000212", "11545": "B000212",
    # 서울북부(B000213): 동대문·중랑·성북·도봉·강북·노원
    "11230": "B000213", "11260": "B000213", "11290": "B000213",
    "11320": "B000213", "11305": "B000213", "11350": "B000213",
    # 서울서부(B000215): 서대문·마포·은평·용산
    "11410": "B000215", "11440": "B000215", "11380": "B000215", "11170": "B000215",
    # 수원(B000250): 용인(처인·기흥·수지)·수원·화성·오산
    "41461": "B000250", "41463": "B000250", "41465": "B000250",
    "41111": "B000250", "41113": "B000250", "41115": "B000250", "41117": "B000250",
    "41590": "B000250", "41370": "B000250",
    # 성남지원(B000251): 성남(수정·중원·분당)·하남·광주
    "41131": "B000251", "41133": "B000251", "41135": "B000251",
    "41450": "B000251", "41610": "B000251",
    # 안양지원(B000254): 안양(만안·동안)·과천·군포·의왕
    "41171": "B000254", "41173": "B000254", "41290": "B000254",
    "41410": "B000254", "41430": "B000254",
}


def _match_key(dong8: str | None, bonbun: str | None, bubun: str | None) -> tuple | None:
    """단지/물건 공통 매칭키 (법정동 8자리, 본번, 부번). 본번 없으면 None(매칭 불가)."""
    if not (dong8 and bonbun):
        return None
    return (dong8, bonbun, bubun or "0000")


@dataclass
class ComplexAuctionResult:
    complex_no: str
    label: str
    name: str
    address: str | None = None
    ops: list[AuctionOp] = field(default_factory=list)  # 알림 대상(NEW·PRICE_DOWN·DATE_CHANGED)
    error: str | None = None


@dataclass
class AuctionRunResult:
    run_id: int
    started_at: datetime
    status: RunStatus
    complexes: list[ComplexAuctionResult] = field(default_factory=list)
    targets_count: int = 0  # 매칭 시도한(지번 보유) 단지 수
    court_count: int = 0
    auctions_fetched: int = 0  # 법원 응답 아파트 raw 합
    new_count: int = 0
    price_down_count: int = 0
    date_changed_count: int = 0
    errors: int = 0
    missing_jibun: int = 0  # 지번 미백필로 매칭에서 빠진 단지 수
    unmatched_court: int = 0  # 관할법원 미상 단지 수
    purged_count: int = 0  # 보관기간 경과로 삭제한 지난 경매 수
    starred_complexes: set[str] = field(default_factory=set)

    @property
    def total_changes(self) -> int:
        return self.new_count + self.price_down_count + self.date_changed_count


def _new_auction(
    dto: AuctionDTO, complex_no: str, run_id: int, now_s: str, view_url: str | None
) -> Auction:
    return Auction(
        auction_key=dto.auction_key,
        complex_no=complex_no,
        court_code=dto.court_code,
        court_name=dto.court_name,
        case_no=dto.case_no,
        item_no=dto.item_no,
        address=dto.address,
        building_name=dto.building_name,
        usage_name=dto.usage_name,
        area_excl=dto.area_max or dto.area_min,
        appraisal_manwon=dto.appraisal_manwon,
        min_bid_manwon=dto.min_bid_manwon,
        min_bid_ratio=dto.min_bid_ratio,
        fail_count=dto.fail_count,
        sale_date=dto.sale_date,
        status_code=dto.status_code,
        in_progress=dto.in_progress,
        auction1_url=view_url or auction1_search_url(),
        court_url=court_case_search_url(),
        first_seen_at=now_s,
        first_seen_run_id=run_id,
        last_seen_at=now_s,
    )


def _has_view_link(url: str | None) -> bool:
    return bool(url and "ca_view.php" in url)


def _apply_auction_ops(
    session: Session,
    diff,  # ComplexAuctionDiff
    by_key: dict[str, Auction],
    complex_no: str,
    run_id: int,
    now_s: str,
    resolve: Callable[[str], str | None] | None,
) -> list[AuctionOp]:
    """diff 연산을 ORM 에 반영. 알림 대상(NEW·PRICE_DOWN·DATE_CHANGED) op 리스트 반환.

    resolve 가 있으면 NEW 물건마다 옥션원 직링크를 1회 해석(이후 행에 캐시·재사용).
    """
    alerts: list[AuctionOp] = []
    for op in diff.ops:
        dto = op.dto
        if op.kind == NEW:
            view_url = resolve(dto.case_no) if resolve is not None else None
            session.add(_new_auction(dto, complex_no, run_id, now_s, view_url))
            op.view_url = view_url
            alerts.append(op)
            continue
        row = by_key.get(dto.auction_key)
        if row is not None:  # PRICE_DOWN·DATE_CHANGED·SEEN — 변동값 갱신
            row.last_seen_at = now_s
            row.min_bid_manwon = dto.min_bid_manwon
            row.min_bid_ratio = dto.min_bid_ratio
            row.fail_count = dto.fail_count
            row.sale_date = dto.sale_date
            row.status_code = dto.status_code
            row.in_progress = dto.in_progress
            session.add(row)
            if _has_view_link(row.auction1_url):
                op.view_url = row.auction1_url  # 직전 NEW 때 해석된 직링크 재사용
            if op.kind in (PRICE_DOWN, DATE_CHANGED):
                alerts.append(op)
    session.commit()
    return alerts


def _select_targets(config: Config, session: Session) -> tuple[list[ResolvedTarget], int]:
    """추적단지 중 지번(cortar_no+본번) 보유 단지만 매칭 대상으로. (대상, 지번미보유 수) 반환."""
    targets = resolve_targets(config, session, None)
    if config.auctions.scope == "starred":
        targets = [t for t in targets if t.complex.starred]
    matchable = [t for t in targets if t.complex.cortar_no and t.complex.bonbun]
    return matchable, len(targets) - len(matchable)


def _collect_court(
    session: Session,
    court_code: str,
    targets: list[ResolvedTarget],
    client: CourtAuctionClient,
    config: Config,
    begin_s: str,
    end_s: str,
    run_id: int,
    now_s: str,
    resolve: Callable[[str], str | None] | None,
) -> tuple[list[ComplexAuctionResult], int]:
    """법원 1개: 아파트 물건 fetch → 단지별 지번매칭·diff·저장. (단지결과, 아파트 raw건수) 반환."""
    auctions = client.fetch_auctions(
        court_code, begin_s, end_s, max_pages=config.auctions.max_pages
    )
    apts = [a for a in auctions if a.is_apartment]

    index: dict[tuple, list[AuctionDTO]] = defaultdict(list)
    for a in apts:
        key = _match_key(a.dong_code, a.bonbun, a.bubun)
        if key is not None:
            index[key].append(a)

    results: list[ComplexAuctionResult] = []
    for rt in targets:
        cx = rt.complex
        key = _match_key(cx.cortar_no[:8] if cx.cortar_no else None, cx.bonbun, cx.bubun)
        matched = index.get(key, []) if key else []
        existing = repo.get_auctions_for_complex(session, cx.complex_no)
        by_key = {a.auction_key: a for a in existing}
        diff = diff_auctions(cx.complex_no, matched, by_key)
        alerts = _apply_auction_ops(
            session, diff, by_key, cx.complex_no, run_id, now_s, resolve
        )
        if not config.auctions.notify_date_changed:
            alerts = [op for op in alerts if op.kind != DATE_CHANGED]  # 기일변경은 옵션
        if alerts:
            log.info("단지 %s(%s): 경매 변동 %d건", cx.complex_no, rt.label, len(alerts))
        results.append(
            ComplexAuctionResult(
                cx.complex_no, rt.label, cx.name, address=cx.address, ops=alerts
            )
        )
    return results, len(apts)


def run_auction_collection(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str = "scheduled",
    client: CourtAuctionClient | None = None,
    notify: Callable[[AuctionRunResult], None] | None = None,
) -> AuctionRunResult:
    """법원경매 수집 1회 (중복 실행 방지 파일락). notify 가 주어지면 집계 후 호출."""
    lock_path = Path(config.app.db_path).parent / ".auction_collector.lock"
    with _acquire_lock(lock_path):
        return _run(config, settings, engine, trigger=trigger, client=client, notify=notify)


def _run(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str,
    client: CourtAuctionClient | None,
    notify: Callable[[AuctionRunResult], None] | None,
) -> AuctionRunResult:
    now = now_kst()
    now_s = to_iso(now)
    begin_s = now.strftime("%Y%m%d")
    end_s = (now + timedelta(days=config.auctions.days)).strftime("%Y%m%d")

    own_client = client is None
    if own_client:
        client = CourtAuctionClient(request_delay_seconds=config.app.request_delay_seconds)

    def _resolve(case_no: str) -> str | None:
        return resolve_view_url(case_no, settings.auction1_cookie)

    resolve = (
        _resolve if (config.auctions.resolve_auction1 and settings.auction1_cookie) else None
    )

    with get_session(engine) as session:
        run = repo.create_run(session, trigger, kind="auctions")
        run_id = run.id
        try:
            targets, missing_jibun = _select_targets(config, session)
            by_court: dict[str, list[ResolvedTarget]] = defaultdict(list)
            unmatched = 0
            for rt in targets:
                court = COURT_BY_SIGUNGU.get(rt.complex.cortar_no[:5])
                if court is None:
                    unmatched += 1
                    log.warning(
                        "단지 %s(%s) 관할법원 미상(시군구 %s) — 수집 제외",
                        rt.complex.complex_no, rt.label, rt.complex.cortar_no[:5],
                    )
                    continue
                by_court[court].append(rt)
            log.info(
                "법원경매 수집 시작 (run #%s, 트리거=%s, 범위=%s, 단지 %d개·법원 %d개, "
                "지번미보유 %d·관할미상 %d, 매각기일 %s~%s)",
                run_id, trigger, config.auctions.scope, len(targets), len(by_court),
                missing_jibun, unmatched, begin_s, end_s,
            )

            results: list[ComplexAuctionResult] = []
            fetched = 0
            errors = 0
            for court_code, court_targets in by_court.items():
                try:
                    court_results, raw = _collect_court(
                        session, court_code, court_targets, client,
                        config, begin_s, end_s, run_id, now_s, resolve,
                    )
                    results.extend(court_results)
                    fetched += raw
                except (CourtAuctionApiError, CourtAuctionParseError) as e:
                    log.error("법원 %s 경매물건 수집 실패: %s", court_code, e)
                    errors += 1
                    for rt in court_targets:
                        results.append(
                            ComplexAuctionResult(
                                rt.complex.complex_no, rt.label, rt.complex.name,
                                address=rt.complex.address, error=str(e),
                            )
                        )

            new_count = sum(1 for r in results for o in r.ops if o.kind == NEW)
            price_down = sum(1 for r in results for o in r.ops if o.kind == PRICE_DOWN)
            date_changed = sum(1 for r in results for o in r.ops if o.kind == DATE_CHANGED)
            status = RunStatus.PARTIAL if errors else RunStatus.SUCCESS
            repo.finalize_run(
                session, run, status,
                targets_count=len(targets),
                articles_fetched=fetched,
                new_count=new_count,
                price_changed_count=price_down,
                http_errors=errors,
            )
            if status in (RunStatus.SUCCESS, RunStatus.PARTIAL):
                set_meta(session, "last_auction_run_id", str(run_id))
                session.commit()

            # 보관기간 경과(매각기일이 retention_days 이전)인 지난 경매 정리.
            cutoff = (now - timedelta(days=config.auctions.retention_days)).strftime("%Y-%m-%d")
            purged = repo.purge_old_auctions(session, cutoff)
            if purged:
                log.info("지난 경매 %d건 정리(매각기일 %s 이전)", purged, cutoff)

            result = AuctionRunResult(
                run_id=run_id,
                started_at=now,
                status=status,
                complexes=results,
                targets_count=len(targets),
                court_count=len(by_court),
                auctions_fetched=fetched,
                new_count=new_count,
                price_down_count=price_down,
                date_changed_count=date_changed,
                errors=errors,
                missing_jibun=missing_jibun,
                unmatched_court=unmatched,
                purged_count=purged,
                starred_complexes={t.complex.complex_no for t in targets if t.complex.starred},
            )
        except Exception as e:  # noqa: BLE001
            log.exception("법원경매 수집 실패 (run #%s)", run_id)
            repo.finalize_run(session, run, RunStatus.FAILED, error=str(e))
            if own_client:
                client.close()
            raise
        finally:
            if own_client:
                client.close()

    log.info(
        "법원경매 수집 완료 (run #%s, %s): 신규 %d · 최저가하락 %d · 기일변경 %d · 법원 %d · 오류 %d",
        run_id, result.status.value, result.new_count, result.price_down_count,
        result.date_changed_count, result.court_count, result.errors,
    )

    if notify is not None and (result.total_changes > 0 or config.auctions.notify_on_no_change):
        try:
            notify(result)
        except Exception:  # noqa: BLE001
            log.exception("법원경매 알림 전송 실패")

    return result


__all__ = [
    "run_auction_collection",
    "AuctionRunResult",
    "ComplexAuctionResult",
    "COURT_BY_SIGUNGU",
]
