"""온디맨드(텔레그램) 단건 작업 — 단지 추가 / 매물 갱신 / 실거래 갱신.

봇 명령이 호출하는 얇은 오케스트레이션 계층. 정기 수집기(collector/deal_collector)의
`run_*_for` 진입점을 단건 타겟으로 재사용한다. 웹/포매팅에 의존하지 않는다(코어 계층).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, select

from ..constants import SOURCE_PINNED, SOURCE_TELEGRAM, SOURCE_WEB
from ..db import repo
from ..db.engine import get_session
from ..db.models import Complex
from ..naver.client import NaverLandClient
from ..naver.search_parser import SearchHit
from ..settings import Config, Settings
from .collector import RunResult, run_collection_for
from .deal_collector import DealRunResult, run_deal_collection_for
from .targets import ResolvedTarget, resolve_one

log = logging.getLogger(__name__)


# ── 단지 이름/검색 해석 ──────────────────────────────────────────────────────
@dataclass
class Candidate:
    complex_no: str
    name: str


@dataclass
class Resolution:
    """사용자 입력(번호 또는 이름)을 단지로 해석한 결과."""

    complex_no: str | None = None  # 확정된 단지번호(있으면 바로 사용)
    candidates: list[Candidate] = field(default_factory=list)  # 이름이 모호할 때 후보들
    is_number: bool = False

    @property
    def found(self) -> bool:
        return self.complex_no is not None


_DISCOVERED_CACHE: dict[str, dict[str, str]] = {}


def _discovered_names(config: Config) -> dict[str, str]:
    """data/discovered*.json 에서 {단지번호: 이름} 맵을 로드(캐시). 파일 없으면 빈 맵."""
    data_dir = str(Path(config.app.db_path).parent)
    cached = _DISCOVERED_CACHE.get(data_dir)
    if cached is not None:
        return cached
    names: dict[str, str] = {}
    for fname in ("discovered_accurate.json", "discovered.json"):
        path = Path(data_dir) / fname
        if not path.exists():
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.debug("%s 로드 실패: %s", path, e)
            continue
        for r in rows if isinstance(rows, list) else []:
            no, nm = str(r.get("complex_no") or ""), r.get("name")
            if no and nm and no not in names:
                names[no] = nm
    _DISCOVERED_CACHE[data_dir] = names
    return names


def resolve_name(
    config: Config,
    engine,
    complex_no: str,
    alias: str | None,
    client: NaverLandClient | None,
) -> str | None:
    """단지번호 → 표시 이름. 우선순위: 별칭 > config 라벨 > DB > discovered > 라이브.

    어느 것도 못 찾으면 None(호출측이 '단지 {번호}' 로 대체).
    """
    if alias and alias.strip():
        return alias.strip()
    for t in config.targets:
        if t.kind == "complex" and t.complex_no == complex_no and t.label:
            return t.label
    with get_session(engine) as session:
        cx = repo.get_complex(session, complex_no)
        if cx and cx.name and not cx.name.startswith("단지 "):
            return cx.name
    nm = _discovered_names(config).get(complex_no)
    if nm:
        return nm
    if client is not None:
        try:
            nm = client.fetch_complex_name(complex_no)
        except Exception as e:  # noqa: BLE001
            log.debug("라이브 단지명 조회 실패 %s: %s", complex_no, e)
            nm = None
        if nm:
            return nm
    return None


def resolve_query(config: Config, engine, query: str) -> Resolution:
    """입력 텍스트를 단지로 해석. 숫자면 단지번호, 아니면 이름(부분일치) 검색.

    이름이 정확히 1개로 좁혀지면 complex_no 확정, 여러 개면 candidates 로 반환.
    """
    q = (query or "").strip()
    if not q:
        return Resolution()
    if q.isdigit():
        return Resolution(complex_no=q, is_number=True)

    # config 라벨 + DB 이름을 함께 검색(부분일치, 대소문자 무시)
    pool: dict[str, str] = {}
    for t in config.targets:
        if t.kind == "complex" and t.complex_no and t.label and q.lower() in t.label.lower():
            pool[t.complex_no] = t.label
    with get_session(engine) as session:
        rows = session.exec(select(Complex)).all()
    for cx in rows:
        nm = cx.name or ""
        if nm and q.lower() in nm.lower():
            pool[cx.complex_no] = nm

    if not pool:
        return Resolution()
    # 정확히 일치하는 이름이 있으면 그것만
    exact = {no: nm for no, nm in pool.items() if nm == q}
    chosen = exact or pool
    if len(chosen) == 1:
        no = next(iter(chosen))
        return Resolution(complex_no=no)
    cands = [Candidate(no, nm) for no, nm in sorted(chosen.items(), key=lambda kv: kv[1])]
    return Resolution(candidates=cands)


def is_tracked(config: Config, engine, complex_no: str) -> bool:
    """정기 수집 대상(추적 중)인지 — config 고정 타겟이거나 활성 DB 단지."""
    if any(t.kind == "complex" and t.complex_no == complex_no for t in config.targets):
        return True
    with get_session(engine) as session:
        cx = repo.get_complex(session, complex_no)
        return bool(
            cx and cx.is_active and cx.source in (SOURCE_PINNED, SOURCE_TELEGRAM, SOURCE_WEB)
        )


# ── 단건 작업 ────────────────────────────────────────────────────────────────
@dataclass
class AddResult:
    complex_no: str
    name: str
    name_resolved: bool  # 이름을 자동으로 찾았는지(별칭 권유 여부 판단)
    run: RunResult


def add_complex(
    config: Config,
    settings: Settings,
    engine,
    complex_no: str,
    *,
    alias: str | None = None,
    client: NaverLandClient,
    source: str = SOURCE_TELEGRAM,
) -> AddResult:
    """단지를 추적 목록에 추가(정기 수집 포함)하고 즉시 1회 수집.

    source 로 출처를 지정한다(텔레그램 /add → telegram, 대시보드 추가 → web).
    config.yaml 고정 단지면 출처는 pinned 로 유지된다(resolve_one).
    """
    name = resolve_name(config, engine, complex_no, alias, client)

    def builder(session: Session) -> list[ResolvedTarget]:
        return [resolve_one(config, session, complex_no, track=True, name=name, source=source)]

    run = run_collection_for(
        config, settings, engine, targets_builder=builder, trigger=source, client=client
    )
    return AddResult(
        complex_no=complex_no,
        name=name or f"단지 {complex_no}",
        name_resolved=name is not None,
        run=run,
    )


# ── 추적 토글(대시보드용 — DB 만, 즉시 수집 없음) ──────────────────────────────
def track_complex(
    config: Config,
    engine,
    complex_no: str,
    *,
    alias: str | None = None,
    source: str = SOURCE_WEB,
) -> Complex:
    """단지를 추적 목록에 등록(is_active=True)만 한다. 수집은 호출측이 별도로 트리거.

    config.yaml 고정 단지면 출처를 pinned 로 유지, 그 외엔 source(기본 web).
    이미 있던 단지(추적 해제됨 포함)는 재활성화하고 출처는 보존한다.
    """
    spec = next(
        (t for t in config.targets if t.kind == "complex" and t.complex_no == complex_no), None
    )
    name = resolve_name(config, engine, complex_no, alias, client=None)
    with get_session(engine) as session:
        existing = repo.get_complex(session, complex_no)
        if spec is not None:
            src = SOURCE_PINNED
        elif existing is not None:
            src = existing.source  # 기존 출처 보존(예: 텔레그램 단지 재추적)
        else:
            src = source
        return repo.upsert_complex(
            session,
            complex_no,
            name=name or (existing.name if existing else None) or f"단지 {complex_no}",
            source=src,
            is_active=True,
        )


def untrack_complex(engine, complex_no: str) -> bool:
    """단지 추적 해제(is_active=False). 정기 수집에서 빠진다. 기존 매물/큐레이션은 보존."""
    with get_session(engine) as session:
        return repo.set_complex_active(session, complex_no, active=False) is not None


def check_complex(
    config: Config,
    settings: Settings,
    engine,
    complex_no: str,
    *,
    client: NaverLandClient,
    name: str | None = None,
) -> RunResult:
    """단지 매물을 즉시 1회 갱신. 미추적 단지는 source=adhoc(추적 안 함)으로 1회만 수집.

    name 은 검색으로 찾은 단지명(미추적 신규 단지의 표시 이름) — 있으면 adhoc 행에 저장한다.
    """

    def builder(session: Session) -> list[ResolvedTarget]:
        return [resolve_one(config, session, complex_no, track=False, name=name)]

    return run_collection_for(
        config, settings, engine, targets_builder=builder, trigger="telegram", client=client
    )


def check_deals(
    config: Config,
    settings: Settings,
    engine,
    complex_no: str,
    *,
    client: NaverLandClient,
    name: str | None = None,
) -> DealRunResult:
    """단지 실거래를 즉시 1회 갱신(평형 면적필터 적용). scope 설정과 무관.

    name 은 검색으로 찾은 단지명 — 있으면 adhoc 행에 저장해 응답에 단지명이 보이게 한다.
    """

    def builder(session: Session) -> list[ResolvedTarget]:
        return [resolve_one(config, session, complex_no, track=False, name=name)]

    return run_deal_collection_for(
        config, settings, engine, targets_builder=builder, trigger="telegram", client=client
    )


# ── 주소/단지명 역추적(검색) ──────────────────────────────────────────────────
def _seed_complex_no(config: Config, engine) -> str:
    """검색 토큰 발급용 seed 단지번호 — config 고정 타겟 > 활성 DB 단지 > 947(프로젝트 기준)."""
    for t in config.targets:
        if t.kind == "complex" and t.complex_no:
            return t.complex_no
    with get_session(engine) as session:
        rows = repo.list_active_complexes(session)
        if rows:
            return rows[0].complex_no
    return "947"  # 메모리/예시에 등장하는 기준 단지(방배 삼호1차) — 최후 폴백


def search_address(
    config: Config, engine, client: NaverLandClient, keyword: str
) -> list[SearchHit]:
    """주소/단지명 키워드 → 단지 후보(SearchHit) 리스트. new.land 검색 경유."""
    kw = (keyword or "").strip()
    if not kw:
        return []
    return client.search_complexes(kw, seed_complex_no=_seed_complex_no(config, engine))
