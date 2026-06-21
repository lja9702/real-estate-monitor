"""수집 1회 오케스트레이션 — config→fetch→parse→diff→upsert→history→집계→알림."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from ..constants import EventType, ListingStatus, RunStatus, from_iso, now_kst, to_iso
from ..db import repo
from ..db.engine import get_session, set_meta
from ..db.models import Listing, ListingHistory
from ..naver.client import FetchResult, NaverLandClient
from ..naver.errors import NaverApiError, NaverParseError
from ..naver.parser import ArticleDTO
from ..settings import Config, Settings
from .diff import (
    NEW,
    PENDING_REMOVAL,
    PRICE_CHANGED,
    REAPPEARED,
    REMOVED,
    SEEN,
    ComplexDiff,
    DiffOp,
    ListingState,
    diff_complex,
)
from .targets import ResolvedTarget, resolve_targets

log = logging.getLogger(__name__)

LOCK_STALE_SECONDS = 3600  # 이보다 오래된 락은 죽은 프로세스로 간주하고 회수


class CollectorLocked(RuntimeError):
    """다른 수집이 이미 실행 중."""


@contextmanager
def _acquire_lock(path: Path) -> Iterator[None]:
    """수집 중복 실행 방지 파일락. 점유 중이면 CollectorLocked."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = 0.0
        if age <= LOCK_STALE_SECONDS:
            raise CollectorLocked(f"이미 수집이 실행 중입니다: {path}") from None
        log.warning("오래된 락(%.0fs) 회수: %s", age, path)
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


@dataclass
class ComplexResult:
    complex_no: str
    label: str
    name: str
    address: str | None = None
    diff: ComplexDiff | None = None
    fetch: FetchResult | None = None
    error: str | None = None


@dataclass
class RunResult:
    run_id: int
    started_at: datetime
    status: RunStatus
    complexes: list[ComplexResult] = field(default_factory=list)
    targets_count: int = 0
    articles_fetched: int = 0
    new_count: int = 0
    price_changed_count: int = 0
    removed_count: int = 0
    reappeared_count: int = 0
    http_errors: int = 0
    starred_complexes: set[str] = field(default_factory=set)  # 관심 단지번호(다이제스트 ★)

    @property
    def total_changes(self) -> int:
        return self.new_count + self.price_changed_count + self.removed_count


def _to_state(listing: Listing) -> ListingState:
    return ListingState(
        article_no=listing.article_no,
        status=listing.status,
        price_fingerprint=listing.price_fingerprint,
        cluster_key=listing.cluster_key,
        price_deal=listing.price_deal,
        price_rent=listing.price_rent,
        missing_since=from_iso(listing.missing_since),
    )


def _apply_content(listing: Listing, dto: ArticleDTO) -> None:
    listing.area_excl = dto.area_excl
    listing.area_supply = dto.area_supply
    listing.floor_info = dto.floor_info
    listing.floor_num = dto.floor_num
    listing.direction = dto.direction
    listing.dong = dto.dong
    listing.feature_desc = dto.feature_desc
    listing.realtor_name = dto.realtor_name
    listing.confirm_date = dto.confirm_date
    listing.article_url = dto.article_url
    listing.cluster_key = dto.cluster_key


def _apply_price(listing: Listing, dto: ArticleDTO) -> None:
    listing.price_deal = dto.price_deal
    listing.price_rent = dto.price_rent
    listing.price_fingerprint = dto.price_fingerprint


def _new_listing(dto: ArticleDTO, run_id: int, now_s: str) -> Listing:
    listing = Listing(
        article_no=dto.article_no,
        complex_no=dto.complex_no,
        trade_type=dto.trade_type,
        status=ListingStatus.ACTIVE,
        first_seen_at=now_s,
        last_seen_at=now_s,
        first_seen_run_id=run_id,
        last_seen_run_id=run_id,
        missing_since=None,
    )
    _apply_content(listing, dto)
    _apply_price(listing, dto)
    return listing


def _history(
    op: DiffOp, event: EventType, run_id: int, now_s: str, listing: Listing | None
) -> ListingHistory:
    dto = op.dto
    return ListingHistory(
        article_no=op.article_no,
        cluster_key=op.cluster_key,
        run_id=run_id,
        event_type=event,
        price_deal=(dto.price_deal if dto else (listing.price_deal if listing else None)),
        price_rent=(dto.price_rent if dto else (listing.price_rent if listing else None)),
        old_price_deal=op.old_price_deal,
        old_price_rent=op.old_price_rent,
        recorded_at=now_s,
    )


def _apply_ops(
    session: Session,
    cdiff: ComplexDiff,
    by_id: dict[str, Listing],
    run_id: int,
    now_s: str,
) -> None:
    for op in cdiff.ops:
        if op.kind == NEW and op.dto is not None:
            listing = _new_listing(op.dto, run_id, now_s)
            session.add(listing)
            session.add(_history(op, EventType.NEW, run_id, now_s, listing))
        elif op.kind == PRICE_CHANGED and op.dto is not None:
            listing = by_id[op.article_no]
            _apply_content(listing, op.dto)
            _apply_price(listing, op.dto)
            listing.status = ListingStatus.ACTIVE
            listing.missing_since = None
            listing.last_seen_at = now_s
            listing.last_seen_run_id = run_id
            session.add(listing)
            session.add(_history(op, EventType.PRICE_CHANGED, run_id, now_s, listing))
        elif op.kind == SEEN and op.dto is not None:
            listing = by_id[op.article_no]
            _apply_content(listing, op.dto)
            listing.status = ListingStatus.ACTIVE
            listing.missing_since = None
            listing.last_seen_at = now_s
            listing.last_seen_run_id = run_id
            session.add(listing)
        elif op.kind == PENDING_REMOVAL:
            listing = by_id[op.article_no]
            listing.status = ListingStatus.PENDING_REMOVAL
            listing.missing_since = now_s
            session.add(listing)
        elif op.kind == REMOVED:
            listing = by_id[op.article_no]
            listing.status = ListingStatus.REMOVED
            session.add(listing)
            session.add(_history(op, EventType.REMOVED, run_id, now_s, listing))
        elif op.kind == REAPPEARED and op.dto is not None:
            listing = by_id[op.article_no]
            _apply_content(listing, op.dto)
            _apply_price(listing, op.dto)
            listing.status = ListingStatus.ACTIVE
            listing.missing_since = None
            listing.last_seen_at = now_s
            listing.last_seen_run_id = run_id
            session.add(listing)
            session.add(_history(op, EventType.REAPPEARED, run_id, now_s, listing))


def _collect_one(
    session: Session,
    rt: ResolvedTarget,
    run_id: int,
    config: Config,
    client: NaverLandClient,
    now: datetime,
) -> ComplexResult:
    cx = rt.complex
    label = rt.label
    try:
        fetch = client.fetch_articles(cx, rt.filt)
    except (NaverApiError, NaverParseError) as e:
        log.error("단지 %s(%s) 수집 실패: %s", cx.complex_no, label, e)
        return ComplexResult(cx.complex_no, label, cx.name, address=cx.address, error=str(e))

    # 주소가 아직 없고 매물이 있으면 첫 번째 매물 상세에서 주소 조회
    if cx.address is None and fetch.articles:
        addr = client.fetch_complex_address(cx.complex_no, fetch.articles[0].article_no)
        if addr:
            cx = repo.upsert_complex(session, cx.complex_no, address=addr)

    # 좌표·단지메타(세대수/동수/준공/용적률/건폐율)가 아직 없으면 단지 정보 API에서 한 번에 백필
    if cx.lat is None or cx.floor_area_ratio is None:
        meta = client.fetch_complex_meta(cx.complex_no)
        if meta:
            cx = repo.upsert_complex(
                session,
                cx.complex_no,
                lat=meta.lat,
                lon=meta.lon,
                total_households=meta.total_households,
                total_dong_count=meta.total_dong_count,
                use_approve_ymd=meta.use_approve_ymd,
                floor_area_ratio=meta.floor_area_ratio,
                building_coverage_ratio=meta.building_coverage_ratio,
            )

    existing_rows = repo.get_listings_for_complex(session, cx.complex_no)
    by_id = {r.article_no: r for r in existing_rows}
    states = {aid: _to_state(r) for aid, r in by_id.items()}

    cdiff = diff_complex(
        cx.complex_no,
        fetch.articles,
        states,
        now=now,
        removal_debounce_hours=config.app.removal_debounce_hours,
        fetch_complete=fetch.complete,
    )
    _apply_ops(session, cdiff, by_id, run_id, to_iso(now))
    session.commit()

    log.info(
        "단지 %s(%s): 수집 %d건 · 신규 %d · 가격변동 %d · 거래완료 %d%s",
        cx.complex_no,
        label,
        len(fetch.articles),
        len(cdiff.new),
        len(cdiff.price_changed),
        len(cdiff.removed),
        "" if fetch.complete else " · ⚠수집불완전(삭제판정 생략)",
    )
    return ComplexResult(cx.complex_no, label, cx.name, address=cx.address, diff=cdiff, fetch=fetch)


def run_collection(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str = "scheduled",
    client: NaverLandClient | None = None,
    notify: Callable[[RunResult], None] | None = None,
) -> RunResult:
    """수집 1회 실행 (중복 실행 방지 파일락 포함). notify 가 주어지면 집계 후 호출."""
    lock_path = Path(config.app.db_path).parent / ".collector.lock"
    with _acquire_lock(lock_path):
        return _run_collection(
            config, settings, engine, trigger=trigger, client=client, notify=notify
        )


def run_collection_for(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    targets_builder: Callable[[Session], list[ResolvedTarget]],
    trigger: str = "manual",
    client: NaverLandClient | None = None,
    notify: Callable[[RunResult], None] | None = None,
) -> RunResult:
    """지정한 타겟만(예: 텔레그램으로 요청한 단지 1개) 수집한다.

    정기 수집과 같은 파일락(.collector.lock)을 공유해 동시 실행을 막는다 —
    정기 수집이 진행 중이면 CollectorLocked 가 발생한다.
    """
    lock_path = Path(config.app.db_path).parent / ".collector.lock"
    with _acquire_lock(lock_path):
        return _run_collection(
            config,
            settings,
            engine,
            trigger=trigger,
            client=client,
            notify=notify,
            targets_builder=targets_builder,
        )


def _run_collection(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str = "scheduled",
    client: NaverLandClient | None = None,
    notify: Callable[[RunResult], None] | None = None,
    targets_builder: Callable[[Session], list[ResolvedTarget]] | None = None,
) -> RunResult:
    now = now_kst()
    own_client = client is None
    if own_client:
        client = NaverLandClient(
            request_delay_seconds=config.app.request_delay_seconds,
            headless=config.app.headless,
        )
        client.__enter__()  # 헤드리스 브라우저 세션 시작

    with get_session(engine) as session:
        run = repo.create_run(session, trigger)
        run_id = run.id
        try:
            build = targets_builder or (lambda s: resolve_targets(config, s, client))
            targets = build(session)
            log.info("수집 시작 (run #%s, 트리거=%s, 타겟 %d개)", run_id, trigger, len(targets))

            results: list[ComplexResult] = []
            for rt in targets:
                results.append(_collect_one(session, rt, run_id, config, client, now))

            new_count = sum(len(r.diff.new) for r in results if r.diff)
            price_changed_count = sum(len(r.diff.price_changed) for r in results if r.diff)
            removed_count = sum(len(r.diff.removed) for r in results if r.diff)
            reappeared_count = sum(len(r.diff.reappeared) for r in results if r.diff)
            articles_fetched = sum(r.fetch.raw_count for r in results if r.fetch)
            http_errors = sum(1 for r in results if r.error or (r.fetch and not r.fetch.complete))
            status = RunStatus.PARTIAL if http_errors else RunStatus.SUCCESS

            repo.finalize_run(
                session,
                run,
                status,
                targets_count=len(targets),
                articles_fetched=articles_fetched,
                new_count=new_count,
                price_changed_count=price_changed_count,
                removed_count=removed_count,
                http_errors=http_errors,
            )
            if status in (RunStatus.SUCCESS, RunStatus.PARTIAL):
                set_meta(session, "last_successful_run_id", str(run_id))
                session.commit()

            run_result = RunResult(
                run_id=run_id,
                started_at=now,
                status=status,
                complexes=results,
                targets_count=len(targets),
                articles_fetched=articles_fetched,
                new_count=new_count,
                price_changed_count=price_changed_count,
                removed_count=removed_count,
                reappeared_count=reappeared_count,
                http_errors=http_errors,
                starred_complexes=repo.starred_complex_nos(session),
            )
        except Exception as e:  # noqa: BLE001
            log.exception("수집 실패 (run #%s)", run_id)
            repo.finalize_run(session, run, RunStatus.FAILED, error=str(e))
            if own_client:
                client.close()
            raise
        finally:
            if own_client:
                client.close()

    log.info(
        "수집 완료 (run #%s, %s): 신규 %d · 가격변동 %d · 거래완료 %d",
        run_id,
        run_result.status.value,
        run_result.new_count,
        run_result.price_changed_count,
        run_result.removed_count,
    )

    if notify is not None and (run_result.total_changes > 0 or config.app.notify_on_no_change):
        try:
            notify(run_result)
        except Exception:  # noqa: BLE001
            log.exception("알림 전송 실패")

    return run_result
