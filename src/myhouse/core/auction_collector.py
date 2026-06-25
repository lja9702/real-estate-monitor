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
from ..court.case_dxdy_parser import CHANGED, derive_outcome
from ..court.case_dxdy_parser import FAILED as OUT_FAILED
from ..court.case_dxdy_parser import SOLD as OUT_SOLD
from ..court.case_dxdy_parser import WITHDRAWN as OUT_WITHDRAWN
from ..court.client import CourtAuctionClient
from ..court.endpoints import case_no_to_csno
from ..court.errors import CourtAuctionApiError, CourtAuctionParseError
from ..db import repo
from ..db.engine import get_session, set_meta
from ..db.models import Auction
from ..settings import Config, Settings
from .auction_diff import (
    DATE_CHANGED,
    FAILED,
    NEW,
    PRICE_DOWN,
    SOLD,
    WITHDRAWN,
    AuctionOp,
    diff_auctions,
)
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
    sold_count: int = 0  # 정합: 매각(낙찰) 확정
    failed_count: int = 0  # 정합: 유찰(재공고 다음기일)
    withdrawn_count: int = 0  # 정합: 취하·취소 등 종국
    reconciled_count: int = 0  # 정합으로 기일내역을 폴링한 물건 수
    errors: int = 0
    missing_jibun: int = 0  # 지번 미백필로 매칭에서 빠진 단지 수
    unmatched_court: int = 0  # 관할법원 미상 단지 수
    purged_count: int = 0  # 보관기간 경과로 삭제한 지난 경매 수
    starred_complexes: set[str] = field(default_factory=set)

    @property
    def total_changes(self) -> int:
        return (
            self.new_count + self.price_down_count + self.date_changed_count
            + self.sold_count + self.failed_count + self.withdrawn_count
        )


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
        remarks=dto.remarks,
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

    auction_key 는 전역 PK 다. 같은 지번에 추적단지가 둘 이상이면(예: 과천 주공8·9단지=부림동 41,
    재건축 분할 단지) 동일 물건이 양쪽에 매칭된다 — diff 는 단지별로 계산되므로 두 번째 단지는
    이를 NEW 로 본다. 이때 한 단지에만 귀속하고 형제 단지는 건너뛴다(중복 PK 삽입 회피).
    """
    alerts: list[AuctionOp] = []
    for op in diff.ops:
        dto = op.dto
        if op.kind == NEW:
            if session.get(Auction, dto.auction_key) is not None:
                continue  # 같은 지번의 형제 단지에 이미 귀속됨 — 전역 유일키 중복 회피
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
            if dto.remarks:  # 비고는 갱신될 수 있음(빈값으로 덮어쓰지 않음)
                row.remarks = dto.remarks
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


def _dto_from_row(row: Auction) -> AuctionDTO:
    """저장행 → 다이제스트 렌더용 최소 DTO(정합 결과 op 에 실어 보낸다)."""
    return AuctionDTO(
        auction_key=row.auction_key,
        court_code=row.court_code,
        court_name=row.court_name,
        case_no=row.case_no or "?",
        item_no=row.item_no,
        address=row.address or "",
        building_name=row.building_name,
        usage_name=row.usage_name,
        appraisal_manwon=row.appraisal_manwon,
        min_bid_manwon=row.min_bid_manwon,
        min_bid_ratio=row.min_bid_ratio,
        fail_count=row.fail_count,
        sale_date=row.sale_date,
        area_max=row.area_excl,
    )


def _ratio(min_manwon: int | None, appraisal_manwon: int | None) -> int | None:
    if min_manwon and appraisal_manwon and appraisal_manwon > 0:
        return round(min_manwon / appraisal_manwon * 100)
    return None


@dataclass
class ReconcileResult:
    ops_by_complex: dict[str, list[AuctionOp]] = field(default_factory=dict)
    sold: int = 0
    failed: int = 0
    withdrawn: int = 0
    polled: int = 0


def _reconcile_matured(
    session: Session,
    client: CourtAuctionClient,
    config: Config,
    today_iso: str,
    now_s: str,
) -> ReconcileResult:
    """매각기일 지난(결과 미확정) 물건을 사건 기일내역으로 정합.

    - 매각/취하 → outcome 확정(종국, in_progress=False) + 알림.
    - 유찰·변경에 재공고된 다음 매각기일이 있으면 그 회차로 '재활성'(sale_date·최저가 갱신, outcome 미확정 유지)
      → 다음 수집부터 다시 추적. 유찰은 알림(다음기일 안내).
    - 미확정·다음기일 없음 → reconciled_at 만 갱신, 다음 회차에 재폴링(가장 오래된 것부터, 회차 상한).
    """
    rows = repo.get_auctions_to_reconcile(
        session, today_iso, limit=config.auctions.reconcile_max
    )
    res = ReconcileResult(ops_by_complex=defaultdict(list))
    for row in rows:
        cs_no = case_no_to_csno(row.case_no or "")
        if not (cs_no and row.court_code):
            row.reconciled_at = now_s
            session.add(row)
            continue
        try:
            events = client.fetch_case_dxdy(row.court_code, cs_no)
        except (CourtAuctionApiError, CourtAuctionParseError) as e:
            log.warning("사건 기일내역 조회 실패 %s(%s): %s", row.case_no, row.court_code, e)
            continue
        res.polled += 1
        outcome = derive_outcome(events, item_seq=row.item_no, today_iso=today_iso)
        row.reconciled_at = now_s
        op: AuctionOp | None = None

        if outcome.outcome == OUT_SOLD:
            row.outcome, row.outcome_label = "sold", outcome.label
            row.final_bid_manwon, row.outcome_date = outcome.final_bid_manwon, outcome.outcome_date
            row.in_progress = False
            res.sold += 1
            op = AuctionOp(
                SOLD, _dto_from_row(row),
                outcome_label=outcome.label, final_bid_manwon=outcome.final_bid_manwon,
            )
        elif outcome.outcome == OUT_WITHDRAWN:
            row.outcome, row.outcome_label = "withdrawn", outcome.label
            row.outcome_date, row.in_progress = outcome.outcome_date, False
            res.withdrawn += 1
            op = AuctionOp(WITHDRAWN, _dto_from_row(row), outcome_label=outcome.label)
        elif outcome.outcome in (OUT_FAILED, CHANGED) and outcome.next_sale_date:
            old_min, old_date = row.min_bid_manwon, row.sale_date
            row.sale_date = outcome.next_sale_date
            if outcome.next_min_bid_manwon is not None:
                row.min_bid_manwon = outcome.next_min_bid_manwon
                row.min_bid_ratio = _ratio(row.min_bid_manwon, row.appraisal_manwon)
            row.in_progress = True  # 다음 회차로 재활성 — 추적 계속(outcome 미확정 유지)
            if outcome.outcome == OUT_FAILED:
                row.fail_count = (row.fail_count or 0) + 1
                res.failed += 1
                op = AuctionOp(
                    FAILED, _dto_from_row(row), outcome_label=outcome.label,
                    old_min_bid_manwon=old_min, old_sale_date=old_date,
                    next_sale_date=outcome.next_sale_date,
                )
            elif config.auctions.notify_date_changed:
                op = AuctionOp(DATE_CHANGED, _dto_from_row(row), old_sale_date=old_date)
        elif outcome.outcome is None and outcome.next_sale_date and outcome.next_sale_date != row.sale_date:
            # 결과 미확정이나 매각기일이 미래로 갱신(윈도우 밖 재공고) — 날짜만 동기화, 알림 없음.
            row.sale_date = outcome.next_sale_date
            if outcome.next_min_bid_manwon is not None:
                row.min_bid_manwon = outcome.next_min_bid_manwon
                row.min_bid_ratio = _ratio(row.min_bid_manwon, row.appraisal_manwon)
            row.in_progress = True
        # else: 미확정·다음기일 없음 → reconciled_at 만, 다음 회차 재폴링.

        session.add(row)
        if op is not None:
            res.ops_by_complex[row.complex_no].append(op)
    session.commit()
    return res


def _merge_reconcile_ops(
    results: list[ComplexAuctionResult],
    reconcile: ReconcileResult,
    targets: list[ResolvedTarget],
) -> None:
    """정합 결과 op 를 단지별 결과에 합류. 이번 forward 대상에 없던 단지는 새 항목 추가."""
    by_no = {r.complex_no: r for r in results}
    label_by_no = {t.complex.complex_no: t for t in targets}
    for complex_no, ops in reconcile.ops_by_complex.items():
        if complex_no in by_no:
            by_no[complex_no].ops.extend(ops)
            continue
        rt = label_by_no.get(complex_no)
        name = rt.complex.name if rt else (ops[0].dto.building_name or "")
        cr = ComplexAuctionResult(
            complex_no,
            rt.label if rt else complex_no,
            name,
            address=rt.complex.address if rt else (ops[0].dto.address or None),
            ops=list(ops),
        )
        results.append(cr)
        by_no[complex_no] = cr


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
    today_iso = now.strftime("%Y-%m-%d")  # 매각기일(ISO) 비교용 — 정합 대상 선별
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

            # 사후 정합: 매각기일 지난(미확정) 물건의 실제 결과(매각/유찰/취하)를 사건 기일내역으로 확정.
            reconcile = ReconcileResult()
            if config.auctions.reconcile:
                try:
                    reconcile = _reconcile_matured(session, client, config, today_iso, now_s)
                except (CourtAuctionApiError, CourtAuctionParseError) as e:
                    log.error("경매 결과 정합 실패: %s", e)
                    errors += 1
                _merge_reconcile_ops(results, reconcile, targets)

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
                sold_count=reconcile.sold,
                failed_count=reconcile.failed,
                withdrawn_count=reconcile.withdrawn,
                reconciled_count=reconcile.polled,
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
        "법원경매 수집 완료 (run #%s, %s): 신규 %d · 최저가하락 %d · 기일변경 %d · "
        "매각 %d · 유찰 %d · 취하 %d (정합폴링 %d) · 법원 %d · 오류 %d",
        run_id, result.status.value, result.new_count, result.price_down_count,
        result.date_changed_count, result.sold_count, result.failed_count,
        result.withdrawn_count, result.reconciled_count, result.court_count, result.errors,
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
