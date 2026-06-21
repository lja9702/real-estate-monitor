"""실거래 수집 1회 오케스트레이션 — config→평형선택→fetch→diff→upsert→집계→알림.

매물 수집기(collector.py)와 분리: 실거래는 하루 1회면 충분하고 변화 모델이 다르다(신규/취소만).
브라우저 세션·DB·Run 테이블(kind="deals")은 공유한다.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from ..constants import NAVER_TRADE_CODE, RunStatus, now_kst, to_iso
from ..db import repo
from ..db.engine import get_session, set_meta
from ..db.models import Deal
from ..naver.client import DealFetchResult, NaverLandClient
from ..naver.deal_parser import DealDTO, PyeongInfo
from ..naver.errors import NaverApiError, NaverParseError
from ..seoul.permit_parser import normalize_jibun
from ..settings import Config, FilterSpec, Settings
from .collector import CollectorLocked, _acquire_lock
from .deal_diff import CANCELLED, NEW, SEEN, DealState, diff_deals
from .targets import ResolvedTarget, resolve_targets

log = logging.getLogger(__name__)


def select_pyeongs(
    pyeongs: list[PyeongInfo], filt: FilterSpec, use_area_filter: bool = True
) -> list[PyeongInfo]:
    """면적 필터에 맞는 평형만 선택(호출량↓·관련성↑). 매칭 없으면 빈 리스트(해당 단지 skip)."""
    if not use_area_filter:
        return list(pyeongs)

    def ok(p: PyeongInfo) -> bool:
        if filt.area_supply_min_m2 and p.area_supply and p.area_supply < filt.area_supply_min_m2:
            return False
        if filt.area_supply_max_m2 and p.area_supply and p.area_supply > filt.area_supply_max_m2:
            return False
        if filt.area_excl_min_m2 and p.area_excl and p.area_excl < filt.area_excl_min_m2:
            return False
        if filt.area_excl_max_m2 and p.area_excl and p.area_excl > filt.area_excl_max_m2:
            return False
        return True

    return [p for p in pyeongs if ok(p)]


@dataclass
class ComplexDealResult:
    complex_no: str
    label: str
    name: str
    address: str | None = None
    new_deals: list[DealDTO] = field(default_factory=list)
    cancelled_deals: list[DealDTO] = field(default_factory=list)
    error: str | None = None


@dataclass
class DealRunResult:
    run_id: int
    started_at: datetime
    status: RunStatus
    complexes: list[ComplexDealResult] = field(default_factory=list)
    targets_count: int = 0
    deals_fetched: int = 0
    new_count: int = 0
    cancelled_count: int = 0
    errors: int = 0
    starred_complexes: set[str] = field(default_factory=set)

    @property
    def total_changes(self) -> int:
        return self.new_count + self.cancelled_count


def _starred_complex_nos(session: Session) -> set[str]:
    """관심 단지번호 집합(단지 단위 별표). scope='starred' 필터·다이제스트 ★ 판정에 사용."""
    return repo.starred_complex_nos(session)


def _load_or_fetch_pyeongs(
    session: Session, client: NaverLandClient, complex_no: str, cached_json: str | None
) -> list[PyeongInfo]:
    """평형 목록을 캐시(complex.pyeongs_json)에서 읽거나 1회 조회 후 캐시."""
    if cached_json:
        try:
            return [PyeongInfo(**d) for d in json.loads(cached_json)]
        except Exception:  # noqa: BLE001
            log.debug("평형 캐시 파싱 실패 — 재조회: %s", complex_no)
    pyeongs = client.fetch_pyeongs(complex_no)
    repo.upsert_complex(
        session,
        complex_no,
        pyeongs_json=json.dumps([p.model_dump() for p in pyeongs], ensure_ascii=False),
    )
    return pyeongs


def _apply_deal_ops(
    session: Session,
    diff,  # ComplexDealDiff
    by_key: dict[str, Deal],
    run_id: int,
    now_s: str,
) -> tuple[list[DealDTO], list[DealDTO]]:
    """diff 연산을 ORM 에 반영. (신규 거래, 취소 거래) DTO 리스트 반환."""
    new_deals: list[DealDTO] = []
    cancelled_deals: list[DealDTO] = []
    for op in diff.ops:
        dto = op.dto
        row = by_key.get(dto.deal_key)
        if op.kind == NEW:
            session.add(_new_deal(dto, run_id, now_s, cancelled=False))
            new_deals.append(dto)
        elif op.kind == CANCELLED:
            if row is None:  # 처음부터 취소 상태로 신고된 거래
                session.add(_new_deal(dto, run_id, now_s, cancelled=True))
            else:
                row.cancelled = True
                row.cancel_seen_at = now_s
                row.last_seen_at = now_s
                session.add(row)
            cancelled_deals.append(dto)
        elif op.kind == SEEN and row is not None:
            row.last_seen_at = now_s
            session.add(row)
    session.commit()
    return new_deals, cancelled_deals


def _new_deal(dto: DealDTO, run_id: int, now_s: str, *, cancelled: bool) -> Deal:
    return Deal(
        deal_key=dto.deal_key,
        complex_no=dto.complex_no,
        trade_type=dto.trade_type,
        deal_date=dto.deal_date,
        price_deal=dto.price_deal,
        price_rent=dto.price_rent,
        floor=dto.floor,
        pyeong_no=dto.pyeong_no,
        pyeong_name=dto.pyeong_name,
        area_excl=dto.area_excl,
        area_supply=dto.area_supply,
        cancelled=cancelled,
        first_seen_at=now_s,
        first_seen_run_id=run_id,
        last_seen_at=now_s,
        cancel_seen_at=now_s if cancelled else None,
    )


def _ensure_jibun(session: Session, client: NaverLandClient, cx) -> None:
    """단지에 토지거래허가 매칭용 대표지번(cortar_no·본번·부번)을 채운다. 실패는 조용히 무시.

    실거래 수집이 단지상세를 보는 김에 호출돼 추가 비용이 단지당 평생 1회뿐이다.
    """
    try:
        res = client.fetch_complex_jibun(cx.complex_no)
    except Exception:  # noqa: BLE001
        return
    if res is None:
        return
    cortar, jibun = res
    fields: dict[str, str] = {}
    if cortar:
        fields["cortar_no"] = cortar
    norm = normalize_jibun(jibun)
    if norm is not None:
        fields["bonbun"], fields["bubun"] = norm
    if fields:
        repo.upsert_complex(session, cx.complex_no, **fields)


def _collect_one(
    session: Session,
    rt: ResolvedTarget,
    run_id: int,
    config: Config,
    client: NaverLandClient,
    now_s: str,
) -> ComplexDealResult:
    cx = rt.complex
    label = rt.label
    trade_codes = [NAVER_TRADE_CODE[t] for t in config.deals.trade_types]
    try:
        pyeongs = _load_or_fetch_pyeongs(session, client, cx.complex_no, cx.pyeongs_json)
    except (NaverApiError, NaverParseError) as e:
        log.error("단지 %s(%s) 평형 조회 실패: %s", cx.complex_no, label, e)
        return ComplexDealResult(cx.complex_no, label, cx.name, address=cx.address, error=str(e))

    # 토지거래허가 매칭용 대표지번을 단지당 1회 백필(이미 채워졌으면 skip) — 별도 fill-jibun 불필요.
    if config.permits.enabled and not cx.bonbun:
        _ensure_jibun(session, client, cx)

    selected = select_pyeongs(pyeongs, rt.filt, config.deals.use_area_filter)
    if not selected:
        log.info("단지 %s(%s): 면적필터 매칭 평형 없음 — skip", cx.complex_no, label)
        return ComplexDealResult(cx.complex_no, label, cx.name, address=cx.address)

    try:
        fetch: DealFetchResult = client.fetch_deals(
            cx.complex_no, selected, trade_codes, year=config.deals.years
        )
    except (NaverApiError, NaverParseError) as e:
        log.error("단지 %s(%s) 실거래 수집 실패: %s", cx.complex_no, label, e)
        return ComplexDealResult(cx.complex_no, label, cx.name, address=cx.address, error=str(e))

    existing = repo.get_deals_for_complex(session, cx.complex_no)
    by_key = {d.deal_key: d for d in existing}
    states = {k: DealState(deal_key=k, cancelled=d.cancelled) for k, d in by_key.items()}

    diff = diff_deals(cx.complex_no, fetch.deals, states)
    new_deals, cancelled_deals = _apply_deal_ops(session, diff, by_key, run_id, now_s)
    repo.upsert_complex(session, cx.complex_no, deals_fetched_at=now_s)

    log.info(
        "단지 %s(%s): 평형 %d · 수집 %d · 신규 %d · 취소 %d%s",
        cx.complex_no,
        label,
        fetch.pyeongs,
        fetch.raw_count,
        len(new_deals),
        len(cancelled_deals),
        "" if fetch.complete else " · ⚠일부 평형 수집실패",
    )
    return ComplexDealResult(
        cx.complex_no,
        label,
        cx.name,
        address=cx.address,
        new_deals=new_deals,
        cancelled_deals=cancelled_deals,
        error=None if fetch.complete else "일부 평형 수집실패",
    )


def run_deal_collection(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str = "scheduled",
    client: NaverLandClient | None = None,
    notify: Callable[[DealRunResult], None] | None = None,
) -> DealRunResult:
    """실거래 수집 1회 (중복 실행 방지 파일락). notify 가 주어지면 집계 후 호출."""
    lock_path = Path(config.app.db_path).parent / ".deal_collector.lock"
    with _acquire_lock(lock_path):
        return _run(config, settings, engine, trigger=trigger, client=client, notify=notify)


def run_deal_collection_for(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    targets_builder: Callable[[Session], list[ResolvedTarget]],
    trigger: str = "manual",
    client: NaverLandClient | None = None,
    notify: Callable[[DealRunResult], None] | None = None,
) -> DealRunResult:
    """지정한 단지만(예: 텔레그램 /deals) 실거래 수집. scope 설정과 무관하게 그 단지를 조회한다."""
    lock_path = Path(config.app.db_path).parent / ".deal_collector.lock"
    with _acquire_lock(lock_path):
        return _run(
            config,
            settings,
            engine,
            trigger=trigger,
            client=client,
            notify=notify,
            targets_builder=targets_builder,
        )


def _run(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str,
    client: NaverLandClient | None,
    notify: Callable[[DealRunResult], None] | None,
    targets_builder: Callable[[Session], list[ResolvedTarget]] | None = None,
) -> DealRunResult:
    now = now_kst()
    now_s = to_iso(now)
    own_client = client is None
    if own_client:
        client = NaverLandClient(
            request_delay_seconds=config.app.request_delay_seconds,
            headless=config.app.headless,
        )
        client.__enter__()

    with get_session(engine) as session:
        run = repo.create_run(session, trigger, kind="deals")
        run_id = run.id
        try:
            if targets_builder is not None:
                targets = targets_builder(session)  # 온디맨드: scope 무시, 지정 단지만
            else:
                targets = resolve_targets(config, session, client)
                if config.deals.scope == "starred":
                    starred = _starred_complex_nos(session)
                    targets = [t for t in targets if t.complex.complex_no in starred]
            log.info(
                "실거래 수집 시작 (run #%s, 트리거=%s, 범위=%s, 타겟 %d개)",
                run_id,
                trigger,
                config.deals.scope,
                len(targets),
            )

            results: list[ComplexDealResult] = []
            for i, rt in enumerate(targets):
                if i > 0:
                    time.sleep(random.uniform(*config.app.request_delay_seconds))
                try:
                    results.append(_collect_one(session, rt, run_id, config, client, now_s))
                except Exception as e:  # noqa: BLE001 — 한 단지 실패가 전체를 막지 않게
                    log.exception("단지 %s 실거래 수집 중 예외", rt.complex.complex_no)
                    results.append(
                        ComplexDealResult(
                            rt.complex.complex_no, rt.label, rt.complex.name, error=str(e)
                        )
                    )

            new_count = sum(len(r.new_deals) for r in results)
            cancelled_count = sum(len(r.cancelled_deals) for r in results)
            deals_fetched = sum(len(r.new_deals) + len(r.cancelled_deals) for r in results)
            errors = sum(1 for r in results if r.error)
            status = RunStatus.PARTIAL if errors else RunStatus.SUCCESS

            repo.finalize_run(
                session,
                run,
                status,
                targets_count=len(targets),
                articles_fetched=deals_fetched,
                new_count=new_count,
                removed_count=cancelled_count,
                http_errors=errors,
            )
            if status in (RunStatus.SUCCESS, RunStatus.PARTIAL):
                set_meta(session, "last_deal_run_id", str(run_id))
                session.commit()

            result = DealRunResult(
                run_id=run_id,
                started_at=now,
                status=status,
                complexes=results,
                targets_count=len(targets),
                deals_fetched=deals_fetched,
                new_count=new_count,
                cancelled_count=cancelled_count,
                errors=errors,
                starred_complexes=_starred_complex_nos(session),
            )
        except Exception as e:  # noqa: BLE001
            log.exception("실거래 수집 실패 (run #%s)", run_id)
            repo.finalize_run(session, run, RunStatus.FAILED, error=str(e))
            if own_client:
                client.close()
            raise
        finally:
            if own_client:
                client.close()

    log.info(
        "실거래 수집 완료 (run #%s, %s): 신규 %d · 취소 %d",
        run_id,
        result.status.value,
        result.new_count,
        result.cancelled_count,
    )

    if notify is not None and (result.total_changes > 0 or config.deals.notify_on_no_change):
        try:
            notify(result)
        except Exception:  # noqa: BLE001
            log.exception("실거래 알림 전송 실패")

    return result


__all__ = [
    "run_deal_collection",
    "DealRunResult",
    "ComplexDealResult",
    "select_pyeongs",
    "CollectorLocked",
]
