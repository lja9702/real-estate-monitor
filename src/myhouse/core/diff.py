"""변화 감지 엔진 (순수 함수 — DB/네트워크 무의존).

직전 스냅샷(ListingState) 과 이번 수집(ArticleDTO) 을 비교해 적용할 연산(DiffOp) 목록을 만든다.
collector 가 이 연산들을 ORM 에 적용한다.

안전 규칙(최우선): fetch_complete=False(수집 중단/차단) 인 단지는 삭제 판정을 전면 생략한다.
일시적 403/타임아웃이 스냅샷을 통째로 '거래완료' 로 오염시키는 것을 막는다.

삭제 디바운스: 미노출은 즉시 REMOVED 가 아니라 PENDING_REMOVAL 로 두고, missing_since 로부터
removal_debounce_hours 경과(=실제 2회 이상 연속 미노출) 후에야 REMOVED 확정. 경과 '시간' 기준이라
맥북 절전으로 한 번 거른 실행에도 안전하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..constants import ListingStatus
from ..naver.parser import ArticleDTO

# DiffOp.kind 값
NEW = "new"
PRICE_CHANGED = "price_changed"
SEEN = "seen"
PENDING_REMOVAL = "pending_removal"
REMOVED = "removed"
REAPPEARED = "reappeared"


@dataclass
class ListingState:
    """diff 입력용 기존 매물의 최소 상태 (ORM 비의존)."""

    article_no: str
    status: ListingStatus
    price_fingerprint: str
    cluster_key: str
    price_deal: int | None = None
    price_rent: int | None = None
    missing_since: datetime | None = None


@dataclass
class DiffOp:
    kind: str
    article_no: str
    cluster_key: str
    dto: ArticleDTO | None = None
    old_price_deal: int | None = None
    old_price_rent: int | None = None


@dataclass
class ComplexDiff:
    complex_no: str
    fetch_complete: bool
    ops: list[DiffOp] = field(default_factory=list)

    def _of(self, kind: str) -> list[DiffOp]:
        return [o for o in self.ops if o.kind == kind]

    @property
    def new(self) -> list[DiffOp]:
        return self._of(NEW)

    @property
    def price_changed(self) -> list[DiffOp]:
        return self._of(PRICE_CHANGED)

    @property
    def removed(self) -> list[DiffOp]:
        return self._of(REMOVED)

    @property
    def reappeared(self) -> list[DiffOp]:
        return self._of(REAPPEARED)

    @property
    def seen(self) -> list[DiffOp]:
        return self._of(SEEN)

    @property
    def pending_removal(self) -> list[DiffOp]:
        return self._of(PENDING_REMOVAL)


def diff_complex(
    complex_no: str,
    incoming: list[ArticleDTO],
    existing: dict[str, ListingState],
    *,
    now: datetime,
    removal_debounce_hours: float,
    fetch_complete: bool,
) -> ComplexDiff:
    """한 단지의 변화 연산 목록 산출."""
    debounce = timedelta(hours=removal_debounce_hours)

    # 같은 수집 내 중복 article_no 는 첫 항목만
    incoming_by_id: dict[str, ArticleDTO] = {}
    for dto in incoming:
        incoming_by_id.setdefault(dto.article_no, dto)

    ops: list[DiffOp] = []

    # 1) 들어온 매물 분류
    for aid, dto in incoming_by_id.items():
        e = existing.get(aid)
        if e is None:
            ops.append(DiffOp(NEW, aid, dto.cluster_key, dto=dto))
        elif e.status in (ListingStatus.PENDING_REMOVAL, ListingStatus.REMOVED):
            ops.append(
                DiffOp(
                    REAPPEARED,
                    aid,
                    dto.cluster_key,
                    dto=dto,
                    old_price_deal=e.price_deal,
                    old_price_rent=e.price_rent,
                )
            )
        elif dto.price_fingerprint != e.price_fingerprint:
            ops.append(
                DiffOp(
                    PRICE_CHANGED,
                    aid,
                    dto.cluster_key,
                    dto=dto,
                    old_price_deal=e.price_deal,
                    old_price_rent=e.price_rent,
                )
            )
        else:
            ops.append(DiffOp(SEEN, aid, dto.cluster_key, dto=dto))

    # 2) 사라진 매물 처리 — 수집이 완전할 때만(안전 규칙)
    if fetch_complete:
        for aid, e in existing.items():
            if aid in incoming_by_id:
                continue
            if e.status == ListingStatus.ACTIVE:
                ops.append(DiffOp(PENDING_REMOVAL, aid, e.cluster_key))
            elif e.status == ListingStatus.PENDING_REMOVAL:
                if e.missing_since is not None and (now - e.missing_since) >= debounce:
                    ops.append(
                        DiffOp(
                            REMOVED,
                            aid,
                            e.cluster_key,
                            old_price_deal=e.price_deal,
                            old_price_rent=e.price_rent,
                        )
                    )
                # 아직 디바운스 미충족 → 계속 PENDING (연산 없음)
            # REMOVED → 무시

    return ComplexDiff(complex_no, fetch_complete, ops)
