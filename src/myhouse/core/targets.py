"""config 타겟 → 수집 대상(ResolvedTarget) 해석.

new.land 는 단지번호(complexNo)만으로 매물을 조회하므로 좌표가 필요 없다.
Phase 1: kind="complex"(단지 직접 지정). kind="region"(지역 자동탐색)은 추후 markers 기반 지원.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session

from ..constants import SOURCE_ADHOC, SOURCE_PINNED, SOURCE_TELEGRAM
from ..db import repo
from ..db.models import Complex
from ..settings import Config, FilterSpec, TargetSpec

log = logging.getLogger(__name__)


@dataclass
class ResolvedTarget:
    complex: Complex
    filt: FilterSpec
    label: str


def resolve_targets(config: Config, session: Session, client) -> list[ResolvedTarget]:
    resolved: list[ResolvedTarget] = []
    seen: set[str] = set()
    # 사용자가 UI/봇에서 추적 해제(is_active=False)한 단지는 config 고정 타겟이라도 제외한다.
    inactive = repo.list_inactive_complex_nos(session)
    for t in config.targets:
        if t.kind == "complex":
            if t.complex_no and t.complex_no in inactive:
                continue  # 추적 해제됨 → 정기 수집에서 빼고, 재활성화 전까지 그대로 둔다
            for rt in _resolve_complex(t, config, session):
                resolved.append(rt)
                seen.add(rt.complex.complex_no)
        elif t.kind == "region":
            log.warning(
                "region 타겟('%s')은 추후 new.land markers 기반으로 지원 예정 — 지금은 "
                "kind: complex(단지 직접 지정)를 사용하세요.",
                t.label or t.cortar_no,
            )
        else:
            log.warning("알 수 없는 타겟 kind=%s 건너뜀", t.kind)

    # config 에 없는 런타임 추적 단지(텔레그램 /add · 대시보드 추가)를 정기 수집에 병합한다.
    # is_active=True 인 단지만 대상이므로 adhoc(1회조회)·추적해제 단지는 자연히 빠진다.
    for cx in repo.list_active_complexes(session):
        if cx.complex_no in seen:
            continue
        resolved.append(
            ResolvedTarget(complex=cx, filt=config.defaults, label=cx.name or cx.complex_no)
        )
        seen.add(cx.complex_no)
    return resolved


def resolve_one(
    config: Config,
    session: Session,
    complex_no: str,
    *,
    track: bool,
    name: str | None = None,
    source: str = SOURCE_TELEGRAM,
) -> ResolvedTarget:
    """온디맨드(텔레그램/대시보드) 단건 수집용 타겟 1개 해석.

    - track=True (/add · 대시보드 추가): source(기본 telegram), is_active=True 로 upsert →
      정기 수집에도 포함. 단, config.yaml 에 이미 있는 단지면 출처를 pinned 로 유지한다.
    - track=False (/check 미추적): 기존 단지는 상태를 건드리지 않고, 없으면
      source=adhoc, is_active=False 로 만들어(정기 수집 제외) 매물만 1회 수집한다.
    필터는 config 에 해당 타겟이 있으면 그 유효필터, 없으면 defaults 를 쓴다.
    """
    spec = next(
        (t for t in config.targets if t.kind == "complex" and t.complex_no == complex_no), None
    )
    filt = config.effective_filter(spec) if spec else config.defaults
    existing = repo.get_complex(session, complex_no)
    label = name or (spec.label if spec and spec.label else None)

    if track:
        source = SOURCE_PINNED if spec is not None else source
        resolved_name = label or (existing.name if existing and existing.name else None) or f"단지 {complex_no}"
        row = repo.upsert_complex(
            session, complex_no, name=resolved_name, source=source, is_active=True
        )
    elif existing is None:
        row = repo.upsert_complex(
            session,
            complex_no,
            name=label or f"단지 {complex_no}",
            source=SOURCE_ADHOC,
            is_active=False,
        )
    else:
        row = existing  # 이미 등록된 단지면 추적 상태를 바꾸지 않고 그대로 수집

    return ResolvedTarget(complex=row, filt=filt, label=row.name or complex_no)


def _resolve_complex(t: TargetSpec, config: Config, session: Session) -> list[ResolvedTarget]:
    if not t.complex_no:
        log.warning("complex 타겟에 complex_no 가 없습니다: %s", t.label)
        return []
    filt = config.effective_filter(t)
    row = repo.upsert_complex(
        session,
        t.complex_no,
        name=t.label or t.complex_no,
        lat=t.lat,
        lon=t.lon,
        cortar_no=t.cortar_no,
        source="pinned",
        is_active=True,
    )
    return [ResolvedTarget(complex=row, filt=filt, label=t.label or row.name or t.complex_no)]
