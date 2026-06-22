"""토지거래허가 수집 1회 오케스트레이션 — 추적단지→자치구 그룹→fetch→매칭→diff→upsert→알림.

실거래 수집기(deal_collector.py)와 형제 구조지만 데이터원이 서울시(httpx)라 브라우저가 없다.
조회는 자치구 단위(최대 62일)이고, 추적단지 지번(cortar_no+bonbun/bubun)에 매칭된 허가만
저장한다 — 한 단지가 곧 거래 단계에 들어갔다는 *가격 없는* 선행신호. 알림은 신규 '허가'만.

지번이 아직 백필되지 않은 단지는 이번 회차에 매칭에서 빠진다(permit_backfill 로 채운다).
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
from ..db import repo
from ..db.engine import get_session, set_meta
from ..db.models import LandPermit
from ..gyeonggi.client import GwacheonLandClient
from ..gyeonggi.endpoints import GWACHEON_SGG_CD
from ..gyeonggi.errors import GyeonggiApiError, GyeonggiParseError
from ..seoul.client import SeoulLandClient
from ..seoul.endpoints import SEOUL_SGG_PREFIX
from ..seoul.errors import SeoulApiError, SeoulParseError
from ..seoul.permit_parser import RESIDENTIAL, PermitDTO
from ..settings import Config, Settings
from .collector import _acquire_lock
from .permit_diff import NEW, SEEN, diff_permits
from .targets import ResolvedTarget, resolve_targets

log = logging.getLogger(__name__)


def _match_key(cortar_no: str | None, bonbun: str | None, bubun: str | None) -> tuple | None:
    """단지/허가 공통 매칭키 (법정동코드, 본번, 부번). 본번 없으면 None(매칭 불가)."""
    if not (cortar_no and bonbun):
        return None
    return (cortar_no, bonbun, bubun or "0000")


@dataclass
class ComplexPermitResult:
    complex_no: str
    label: str
    name: str
    address: str | None = None
    new_permits: list[PermitDTO] = field(default_factory=list)  # 신규 '허가'(알림용)
    error: str | None = None


@dataclass
class PermitRunResult:
    run_id: int
    started_at: datetime
    status: RunStatus
    complexes: list[ComplexPermitResult] = field(default_factory=list)
    targets_count: int = 0  # 매칭 시도한(서울·지번 보유) 단지 수
    sgg_count: int = 0
    permits_fetched: int = 0  # 자치구 응답 raw 합
    new_count: int = 0  # 신규 '허가' 합
    errors: int = 0
    missing_jibun: int = 0  # 지번 미백필로 매칭에서 빠진 단지 수
    starred_complexes: set[str] = field(default_factory=set)

    @property
    def total_changes(self) -> int:
        return self.new_count


def _new_permit(dto: PermitDTO, complex_no: str, run_id: int, now_s: str) -> LandPermit:
    return LandPermit(
        permit_key=dto.permit_key,
        complex_no=complex_no,
        sgg_cd=dto.sgg_cd,
        lawd_cd=dto.lawd_cd,
        address=dto.address,
        bonbun=dto.bonbun,
        bubun=dto.bubun,
        permit_date=dto.permit_date,
        job_gbn=dto.job_gbn,
        use_purp=dto.use_purp,
        jimok=dto.jimok,
        first_seen_at=now_s,
        first_seen_run_id=run_id,
        last_seen_at=now_s,
    )


def _apply_permit_ops(
    session: Session,
    diff,  # ComplexPermitDiff
    by_key: dict[str, LandPermit],
    complex_no: str,
    run_id: int,
    now_s: str,
) -> list[PermitDTO]:
    """diff 연산을 ORM 에 반영. 신규 '허가'(알림 대상) DTO 리스트 반환.

    저장은 신규 전부(허가/취소/불허가 등)지만 알림은 granted 만 모은다.

    permit_key 는 전역 PK 다. 같은 지번에 추적단지가 둘 이상이면(예: 과천 주공8·9단지=부림동 41,
    재건축 분할 단지) 동일 허가가 양쪽에 매칭된다 — 이때 한 단지에만 귀속하고 형제 단지는 건너뛴다
    (중복 PK 삽입 회피). 가격 없는 거래활성 신호라 한쪽 귀속으로 충분하다.
    """
    new_granted: list[PermitDTO] = []
    for op in diff.ops:
        dto = op.dto
        if op.kind == NEW:
            if session.get(LandPermit, dto.permit_key) is not None:
                continue  # 같은 지번의 형제 단지에 이미 귀속됨 — 전역 유일키 중복 회피
            session.add(_new_permit(dto, complex_no, run_id, now_s))
            if dto.granted:
                new_granted.append(dto)
        elif op.kind == SEEN:
            row = by_key.get(dto.permit_key)
            if row is not None:
                row.last_seen_at = now_s
                if dto.job_gbn and row.job_gbn != dto.job_gbn:
                    row.job_gbn = dto.job_gbn  # 허가→취소 등 처리구분 변화 갱신
                session.add(row)
    session.commit()
    return new_granted


def _is_supported_zone(cortar_no: str | None) -> bool:
    """수집 지원 토지거래허가구역인가 — 서울 전역(11xxx) 또는 과천(41290)."""
    c = cortar_no or ""
    return c.startswith(SEOUL_SGG_PREFIX) or c.startswith(GWACHEON_SGG_CD)


def _select_targets(config: Config, session: Session) -> tuple[list[ResolvedTarget], int, int]:
    """추적단지 중 수집 지원구역·지번 보유 단지만 매칭 대상으로.

    (대상, 지번미보유 수, 미지원지역 skip 수) 반환. 미지원지역 = 경기 성남·용인 등
    (gris 에 처리내역 API 가 없어 미구현) — 조용히 버리지 않고 카운트해 로그로 드러낸다.
    """
    targets = resolve_targets(config, session, None)
    if config.permits.scope == "starred":
        targets = [t for t in targets if t.complex.starred]
    in_zone = [t for t in targets if _is_supported_zone(t.complex.cortar_no)]
    skipped = len(targets) - len(in_zone)
    matchable = [t for t in in_zone if t.complex.bonbun]
    return matchable, len(in_zone) - len(matchable), skipped


def _collect_sgg(
    session: Session,
    sgg_cd: str,
    targets: list[ResolvedTarget],
    client: SeoulLandClient,
    config: Config,
    begin_s: str,
    end_s: str,
    run_id: int,
    now_s: str,
) -> tuple[list[ComplexPermitResult], int]:
    """자치구 1개: 허가내역 fetch → 단지별 매칭·diff·저장. (단지결과, raw건수) 반환."""
    permits = client.fetch_permits(sgg_cd, begin_s, end_s)
    if config.permits.use_purpose_filter:
        permits = [p for p in permits if p.use_purp == RESIDENTIAL]

    index: dict[tuple, list[PermitDTO]] = defaultdict(list)
    for p in permits:
        key = _match_key(p.lawd_cd, p.bonbun, p.bubun)
        if key is not None:
            index[key].append(p)

    results: list[ComplexPermitResult] = []
    for rt in targets:
        cx = rt.complex
        key = _match_key(cx.cortar_no, cx.bonbun, cx.bubun)
        matched = index.get(key, []) if key else []
        existing = repo.get_permits_for_complex(session, cx.complex_no)
        by_key = {p.permit_key: p for p in existing}
        diff = diff_permits(cx.complex_no, matched, set(by_key))
        new_granted = _apply_permit_ops(session, diff, by_key, cx.complex_no, run_id, now_s)
        if new_granted:
            log.info("단지 %s(%s): 신규 허가 %d건", cx.complex_no, rt.label, len(new_granted))
        results.append(
            ComplexPermitResult(
                cx.complex_no,
                rt.label,
                cx.name,
                address=cx.address,
                new_permits=new_granted,
            )
        )
    return results, len(permits)


def run_permit_collection(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str = "scheduled",
    client: SeoulLandClient | None = None,
    gwacheon_client: GwacheonLandClient | None = None,
    notify: Callable[[PermitRunResult], None] | None = None,
) -> PermitRunResult:
    """토지거래허가 수집 1회 (중복 실행 방지 파일락). notify 가 주어지면 집계 후 호출."""
    lock_path = Path(config.app.db_path).parent / ".permit_collector.lock"
    with _acquire_lock(lock_path):
        return _run(
            config, settings, engine,
            trigger=trigger, client=client, gwacheon_client=gwacheon_client, notify=notify,
        )


def _run(
    config: Config,
    settings: Settings,
    engine: Engine,
    *,
    trigger: str,
    client: SeoulLandClient | None,
    gwacheon_client: GwacheonLandClient | None,
    notify: Callable[[PermitRunResult], None] | None,
) -> PermitRunResult:
    now = now_kst()
    now_s = to_iso(now)
    end_s = now.strftime("%Y%m%d")
    begin_s = (now - timedelta(days=config.permits.days)).strftime("%Y%m%d")

    own_client = client is None
    if own_client:
        client = SeoulLandClient()
        client.__enter__()
    own_gc = gwacheon_client is None
    if own_gc:
        gwacheon_client = GwacheonLandClient()
        gwacheon_client.__enter__()

    def _client_for(sgg_cd: str):
        return gwacheon_client if sgg_cd == GWACHEON_SGG_CD else client

    with get_session(engine) as session:
        run = repo.create_run(session, trigger, kind="permits")
        run_id = run.id
        try:
            targets, missing_jibun, skipped = _select_targets(config, session)
            by_sgg: dict[str, list[ResolvedTarget]] = defaultdict(list)
            for rt in targets:
                by_sgg[rt.complex.cortar_no[:5]].append(rt)
            log.info(
                "토지거래허가 수집 시작 (run #%s, 트리거=%s, 범위=%s, 단지 %d개·시군구 %d개, "
                "지번미보유 %d개, 미지원지역 %d개, 기간 %s~%s)",
                run_id, trigger, config.permits.scope, len(targets), len(by_sgg),
                missing_jibun, skipped, begin_s, end_s,
            )

            results: list[ComplexPermitResult] = []
            permits_fetched = 0
            errors = 0
            for sgg_cd, sgg_targets in by_sgg.items():
                try:
                    sgg_results, raw = _collect_sgg(
                        session, sgg_cd, sgg_targets, _client_for(sgg_cd),
                        config, begin_s, end_s, run_id, now_s,
                    )
                    results.extend(sgg_results)
                    permits_fetched += raw
                except (SeoulApiError, SeoulParseError, GyeonggiApiError, GyeonggiParseError) as e:
                    log.error("시군구 %s 허가내역 수집 실패: %s", sgg_cd, e)
                    errors += 1
                    for rt in sgg_targets:
                        results.append(
                            ComplexPermitResult(
                                rt.complex.complex_no, rt.label, rt.complex.name,
                                address=rt.complex.address, error=str(e),
                            )
                        )

            new_count = sum(len(r.new_permits) for r in results)
            status = RunStatus.PARTIAL if errors else RunStatus.SUCCESS
            repo.finalize_run(
                session, run, status,
                targets_count=len(targets),
                articles_fetched=permits_fetched,
                new_count=new_count,
                http_errors=errors,
            )
            if status in (RunStatus.SUCCESS, RunStatus.PARTIAL):
                set_meta(session, "last_permit_run_id", str(run_id))
                session.commit()

            result = PermitRunResult(
                run_id=run_id,
                started_at=now,
                status=status,
                complexes=results,
                targets_count=len(targets),
                sgg_count=len(by_sgg),
                permits_fetched=permits_fetched,
                new_count=new_count,
                errors=errors,
                missing_jibun=missing_jibun,
                starred_complexes={t.complex.complex_no for t in targets if t.complex.starred},
            )
        except Exception as e:  # noqa: BLE001
            log.exception("토지거래허가 수집 실패 (run #%s)", run_id)
            repo.finalize_run(session, run, RunStatus.FAILED, error=str(e))
            raise
        finally:
            if own_client:
                client.close()
            if own_gc:
                gwacheon_client.close()

    log.info(
        "토지거래허가 수집 완료 (run #%s, %s): 신규 허가 %d · 자치구 %d · 오류 %d",
        run_id, result.status.value, result.new_count, result.sgg_count, result.errors,
    )

    if notify is not None and (result.total_changes > 0 or config.permits.notify_on_no_change):
        try:
            notify(result)
        except Exception:  # noqa: BLE001
            log.exception("토지거래허가 알림 전송 실패")

    return result


def run_permit_for_one(
    config: Config,
    engine: Engine,
    complex_no: str,
    *,
    naver_client,
) -> ComplexPermitResult:
    """단지 1개 온디맨드 토지거래허가 수집. 지번 백필 포함.

    /permits 텔레그램 명령용 — /deals 처럼 단건 수집 후 결과를 반환한다.
    naver_client 는 jibun 미확보 시 Naver 복잡상세 API 로 채우는 데 쓴다.
    SeoulLandClient(httpx)는 내부에서 생성한다.
    """
    from ..db.models import Complex as _Complex
    from ..seoul.permit_parser import normalize_jibun

    now = now_kst()
    begin_s = (now - timedelta(days=config.permits.days)).strftime("%Y%m%d")
    end_s = now.strftime("%Y%m%d")
    now_s = to_iso(now)

    with get_session(engine) as session:
        cx = session.get(_Complex, complex_no)
        if cx is None:
            return ComplexPermitResult(complex_no, complex_no, complex_no, error="단지 없음")

        # 지번 백필 (없으면 Naver 단지상세 API)
        if not cx.bonbun:
            try:
                jd = naver_client.fetch_complex_jibun(complex_no)
                if jd:
                    cortar_no, detail = jd
                    parsed = normalize_jibun(detail)
                    if parsed:
                        cx = repo.upsert_complex(
                            session, complex_no,
                            cortar_no=cortar_no, bonbun=parsed[0], bubun=parsed[1],
                        )
            except Exception as e:  # noqa: BLE001
                log.debug("단지 %s 지번 조회 실패: %s", complex_no, e)

        if not cx.bonbun:
            return ComplexPermitResult(
                complex_no, cx.name or complex_no, cx.name or complex_no,
                address=cx.address, error="지번 정보를 가져오지 못했습니다",
            )
        if not _is_supported_zone(cx.cortar_no):
            return ComplexPermitResult(
                complex_no, cx.name or complex_no, cx.name or complex_no,
                address=cx.address,
                error="토지거래허가 수집 미지원 지역입니다 (서울 전역·과천만 지원)",
            )

        sgg_cd = cx.cortar_no[:5]
        run = repo.create_run(session, "telegram", kind="permits")
        run_id = run.id

        try:
            rt = ResolvedTarget(complex=cx, filt=config.defaults, label=cx.name or complex_no)
            client_cm = (
                GwacheonLandClient() if sgg_cd == GWACHEON_SGG_CD else SeoulLandClient()
            )
            with client_cm as client:
                results, raw = _collect_sgg(
                    session, sgg_cd, [rt], client, config, begin_s, end_s, run_id, now_s
                )
            new_count = sum(len(r.new_permits) for r in results)
            repo.finalize_run(
                session, run, RunStatus.SUCCESS,
                targets_count=1, articles_fetched=raw, new_count=new_count,
            )
            set_meta(session, "last_permit_run_id", str(run_id))
            session.commit()
            return results[0] if results else ComplexPermitResult(
                complex_no, cx.name or complex_no, cx.name or complex_no, address=cx.address
            )
        except (SeoulApiError, SeoulParseError) as e:
            log.error("단지 %s 온디맨드 허가 수집 실패: %s", complex_no, e)
            repo.finalize_run(session, run, RunStatus.FAILED, error=str(e))
            return ComplexPermitResult(
                complex_no, cx.name or complex_no, cx.name or complex_no,
                address=cx.address, error=f"서울시 API 오류: {e}",
            )


__all__ = ["run_permit_collection", "run_permit_for_one", "PermitRunResult", "ComplexPermitResult"]
