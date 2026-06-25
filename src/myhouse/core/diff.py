"""변화 감지 엔진 (순수 함수 — DB/네트워크 무의존).

직전 스냅샷(ListingState) 과 이번 수집(ArticleDTO) 을 비교해 적용할 연산(DiffOp) 목록을 만든다.
collector 가 이 연산들을 ORM 에 적용한다.

안전 규칙(최우선): fetch_complete=False(수집 중단/차단) 인 단지는 삭제 판정을 전면 생략한다.
일시적 403/타임아웃이 스냅샷을 통째로 '거래완료' 로 오염시키는 것을 막는다.

삭제 디바운스: 미노출은 즉시 REMOVED 가 아니라 PENDING_REMOVAL 로 두고, missing_since 로부터
removal_debounce_hours 경과(=실제 2회 이상 연속 미노출) 후에야 REMOVED 확정. 경과 '시간' 기준이라
맥북 절전으로 한 번 거른 실행에도 안전하다.

재등록(확인갱신) 흡수: 네이버는 중개사가 매물 확인을 갱신(확인 기간 만료 후 재등록)하면 *새*
articleNo 를 발급한다. 그래서 같은 물건(논리적 매물 = cluster_key + 중개사 + 가격지문)이 새 번호로
다시 들어오면 NEW(신규)·옛 번호 REMOVED(거래완료) 한 쌍의 오탐이 난다. 이를 막기 위해:
  - 들어온 새 번호가 같은 논리적 매물의 살아있는(ACTIVE/PENDING) 번호를 이미 갖고 있으면
    NEW 대신 REREGISTERED(무음) 로 분류한다 — DB 엔 적재하되 알림엔 안 띄운다.
  - REMOVED 직전, 같은 논리적 매물이 이번 수집에 다른 번호로 살아있으면 REMOVED 대신
    SUPERSEDED(무음) 로 분류한다 — 거래완료가 아니라 번호 교체이므로.
중개사명이 없으면(논리키 None) 보수적으로 흡수하지 않는다(같은 중개사 확인 여부 불명).
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
REREGISTERED = "reregistered"  # 같은 물건 재등록(확인갱신→새 번호) — 무음 적재
SUPERSEDED = "superseded"  # 재등록으로 대체된 옛 번호 정리 — 무음(거래완료 아님)


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
    realtor_name: str | None = None


def logical_key(cluster_key: str, realtor_name: str | None, price_fingerprint: str) -> str | None:
    """'논리적 매물' 키 — 같은 물건이 새 매물번호로 재등록돼도 동일하게 식별.

    cluster_key(단지·평형·층·향·거래유형) + 중개사 + 가격지문(매매가|월세). 중개사명이 없으면
    같은 중개사의 확인갱신인지 확신할 수 없어 None 을 돌려준다(흡수 대상에서 제외).
    """
    if not realtor_name:
        return None
    return f"{cluster_key}|{realtor_name}|{price_fingerprint}"


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

    @property
    def reregistered(self) -> list[DiffOp]:
        return self._of(REREGISTERED)

    @property
    def superseded(self) -> list[DiffOp]:
        return self._of(SUPERSEDED)


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

    # 재등록(확인갱신) 흡수용 논리적 매물 색인.
    #  - incoming_logical: 이번 수집에 (어떤 번호로든) 보이는 논리적 매물 → 옛 번호 거래완료 흡수 판정
    #  - existing_live_logical: 직전 스냅샷의 살아있는(ACTIVE/PENDING) 논리적 매물 → 새 번호 신규 억제 판정
    incoming_logical: set[str] = set()
    for dto in incoming_by_id.values():
        lk = logical_key(dto.cluster_key, dto.realtor_name, dto.price_fingerprint)
        if lk is not None:
            incoming_logical.add(lk)
    existing_live_logical: set[str] = set()
    for e in existing.values():
        if e.status in (ListingStatus.ACTIVE, ListingStatus.PENDING_REMOVAL):
            lk = logical_key(e.cluster_key, e.realtor_name, e.price_fingerprint)
            if lk is not None:
                existing_live_logical.add(lk)

    ops: list[DiffOp] = []

    # 1) 들어온 매물 분류
    for aid, dto in incoming_by_id.items():
        e = existing.get(aid)
        if e is None:
            lk = logical_key(dto.cluster_key, dto.realtor_name, dto.price_fingerprint)
            if lk is not None and lk in existing_live_logical:
                # 같은 중개사가 같은 물건을 같은 값으로 재등록(확인갱신→새 번호). 신규 아님 — 무음 적재.
                ops.append(DiffOp(REREGISTERED, aid, dto.cluster_key, dto=dto))
            else:
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
                    lk = logical_key(e.cluster_key, e.realtor_name, e.price_fingerprint)
                    if lk is not None and lk in incoming_logical:
                        # 같은 물건이 이번 수집에 새 번호로 살아있음 → 거래완료 아님, 번호 교체. 무음 정리.
                        ops.append(
                            DiffOp(
                                SUPERSEDED,
                                aid,
                                e.cluster_key,
                                old_price_deal=e.price_deal,
                                old_price_rent=e.price_rent,
                            )
                        )
                    else:
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
