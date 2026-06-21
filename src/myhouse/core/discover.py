"""주간 신규편입 단지 탐색 1회 오케스트레이션.

지정 지역(config.discover.regions)을 single-markers 로 훑어 매매 가격대·세대수·면적 조건에
맞는 단지를 모은다(서버측 필터로 1차 거름). 기존 추적 단지(config/DB)·이미 발견한 후보에
없던 '신규 편입' 단지만 골라 텔레그램으로 알린다. 추가(추적)는 사용자가 /add 로 직접 한다.

첫 탐색 회차는 baseline 으로 현재 후보를 전부 기록만 하고 알리지 않는다(폭주 방지).
이후 회차부터 baseline 에 없던 단지를 알린다. 알림은 단지당 1회(notified=sticky).
실거래 수집과 같은 인프라(브라우저·Run 테이블·파일락 패턴)를 공유한다.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from ..constants import RunStatus, now_kst, to_iso
from ..db import repo
from ..db.engine import get_session, set_meta
from ..naver.client import NaverLandClient
from ..naver.errors import NaverApiError, NaverParseError
from ..naver.regions import DiscoveredComplex
from ..settings import Config, Settings
from .collector import CollectorLocked, _acquire_lock

log = logging.getLogger(__name__)


@dataclass
class RegionResult:
    name: str
    found: int = 0
    capped: bool = False
    error: str | None = None


@dataclass
class DiscoverResult:
    run_id: int
    started_at: datetime
    status: RunStatus
    new_candidates: list[DiscoveredComplex] = field(default_factory=list)
    total_found: int = 0  # 밴드 편입 고유 단지 수(중복 제거 후)
    first_run: bool = False  # baseline 회차(알림 억제)
    regions: list[RegionResult] = field(default_factory=list)
    errors: int = 0


def _seed_complex_no(config: Config, session: Session) -> str:
    """토큰 발급용 seed 단지번호 — 설정 > config 고정타겟 > 활성 DB 단지 > 947 폴백."""
    if config.discover.seed_complex_no:
        return config.discover.seed_complex_no
    for t in config.targets:
        if t.kind == "complex" and t.complex_no:
            return t.complex_no
    rows = repo.list_active_complexes(session)
    if rows:
        return rows[0].complex_no
    return "947"


def _known_tracked_nos(config: Config, session: Session) -> set[str]:
    """이미 사용자가 추적 중인 단지(알릴 필요 없음) — resolve_targets 와 같은 의미.

    config 고정 타겟(추적 해제분 제외) ∪ 활성 DB 단지.
    """
    config_nos = {
        t.complex_no for t in config.targets if t.kind == "complex" and t.complex_no
    }
    inactive = repo.list_inactive_complex_nos(session)
    active_db = {c.complex_no for c in repo.list_active_complexes(session)}
    return (config_nos - inactive) | active_db


def run_discovery(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str = "scheduled",
    client: NaverLandClient | None = None,
    notify: Callable[[DiscoverResult], None] | None = None,
) -> DiscoverResult:
    """주간 탐색 1회 (중복 실행 방지 파일락). notify 가 주어지면 신규 발견 시 호출."""
    lock_path = Path(config.app.db_path).parent / ".discover.lock"
    with _acquire_lock(lock_path):
        return _run(config, settings, engine, trigger=trigger, client=client, notify=notify)


def _run(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str,
    client: NaverLandClient | None,
    notify: Callable[[DiscoverResult], None] | None,
) -> DiscoverResult:
    now = now_kst()
    now_s = to_iso(now)
    disc = config.discover
    own_client = client is None
    if own_client:
        client = NaverLandClient(
            request_delay_seconds=config.app.request_delay_seconds,
            headless=config.app.headless,
        )
        client.__enter__()

    with get_session(engine) as session:
        run = repo.create_run(session, trigger, kind="discover")
        run_id = run.id
        try:
            seed = _seed_complex_no(config, session)
            known = _known_tracked_nos(config, session)
            existing = repo.list_discover_candidate_nos(session)
            first_run = len(existing) == 0

            # 1) 지역별 마커 수집 → complex_no 로 중복 제거(먼저 발견한 지역 라벨 유지)
            found: dict[str, DiscoveredComplex] = {}
            region_results: list[RegionResult] = []
            for i, region in enumerate(disc.regions):
                if i > 0:
                    time.sleep(random.uniform(*config.app.request_delay_seconds))
                rr = RegionResult(name=region.name)
                try:
                    markers = client.fetch_markers(region, disc, seed_complex_no=seed)
                except (NaverApiError, NaverParseError) as e:
                    log.error("지역 '%s' 마커 수집 실패: %s", region.name, e)
                    rr.error = str(e)
                    region_results.append(rr)
                    continue
                rr.capped = len(markers) >= 500
                fresh = 0
                for dc in markers:
                    if dc.complex_no not in found:
                        found[dc.complex_no] = dc
                        fresh += 1
                rr.found = fresh
                region_results.append(rr)
                log.info("지역 '%s': 밴드 편입 %d개(신규고유 %d)", region.name, len(markers), fresh)

            # 2) 후보 upsert + 신규 편입 판정
            new_candidates: list[DiscoveredComplex] = []
            for no, dc in found.items():
                is_tracked = no in known
                is_existing = no in existing
                # baseline 이거나 이미 추적/기록된 단지면 알림 억제(notified=True)
                alert = (not first_run) and (not is_existing) and (not is_tracked)
                fields = dict(
                    name=dc.name or None,
                    region=dc.region,
                    real_estate_type=dc.real_estate_type,
                    price_min=dc.min_deal_price,
                    price_max=dc.max_deal_price,
                    households=dc.total_households,
                    area_min=dc.min_area,
                    area_max=dc.max_area,
                )
                if no not in existing:
                    fields["tracked_at_discovery"] = is_tracked
                if alert:
                    fields["notified"] = True
                    fields["notified_at"] = now_s
                    new_candidates.append(dc)
                elif not is_existing:
                    # baseline 흡수 또는 이미-추적 단지: 기록만, 알림 억제
                    fields["notified"] = True
                    if first_run or is_tracked:
                        fields["notified_at"] = now_s
                repo.upsert_discover_candidate(session, no, **fields)

            errors = sum(1 for r in region_results if r.error)
            status = RunStatus.PARTIAL if errors else RunStatus.SUCCESS
            repo.finalize_run(
                session,
                run,
                status,
                targets_count=len(disc.regions),
                articles_fetched=len(found),
                new_count=len(new_candidates),
                http_errors=errors,
            )
            if status in (RunStatus.SUCCESS, RunStatus.PARTIAL):
                set_meta(session, "last_discover_run_id", str(run_id))
                session.commit()

            result = DiscoverResult(
                run_id=run_id,
                started_at=now,
                status=status,
                new_candidates=new_candidates,
                total_found=len(found),
                first_run=first_run,
                regions=region_results,
                errors=errors,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("주간 탐색 실패 (run #%s)", run_id)
            repo.finalize_run(session, run, RunStatus.FAILED, error=str(e))
            if own_client:
                client.close()
            raise
        finally:
            if own_client:
                client.close()

    if first_run:
        log.info(
            "주간 탐색 baseline 확립 (run #%s): 후보 %d개 기록(알림 없음)",
            run_id,
            result.total_found,
        )
    else:
        log.info(
            "주간 탐색 완료 (run #%s, %s): 편입 %d개 중 신규 %d개",
            run_id,
            result.status.value,
            result.total_found,
            len(result.new_candidates),
        )

    should_notify = (not first_run) and (
        bool(result.new_candidates) or disc.notify_on_no_change
    )
    if notify is not None and should_notify:
        try:
            notify(result)
        except Exception:  # noqa: BLE001
            log.exception("주간 탐색 알림 전송 실패")

    return result


__all__ = ["run_discovery", "DiscoverResult", "RegionResult", "CollectorLocked"]
