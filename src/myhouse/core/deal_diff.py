"""실거래 변화 감지 (순수 함수 — DB/네트워크 무의존).

실거래는 과거 사실이라 매물처럼 '사라짐=거래완료' 판정이 없다. 변화는 두 가지뿐:
  - NEW       : 처음 보는 거래 (신규 신고)
  - CANCELLED : 이전에 본 거래가 취소(deleteYn="O")됐거나, 처음부터 취소 상태로 신고된 거래
누락(이번 수집에서 안 보임)은 무시한다 — 일시적 수집 실패가 데이터를 훼손하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..naver.deal_parser import DealDTO

NEW = "new"
CANCELLED = "cancelled"
SEEN = "seen"


@dataclass
class DealState:
    """diff 입력용 기존 거래의 최소 상태 (ORM 비의존)."""

    deal_key: str
    cancelled: bool


@dataclass
class DealOp:
    kind: str
    dto: DealDTO


@dataclass
class ComplexDealDiff:
    complex_no: str
    ops: list[DealOp] = field(default_factory=list)

    def _of(self, kind: str) -> list[DealOp]:
        return [o for o in self.ops if o.kind == kind]

    @property
    def new(self) -> list[DealOp]:
        return self._of(NEW)

    @property
    def cancelled(self) -> list[DealOp]:
        return self._of(CANCELLED)

    @property
    def seen(self) -> list[DealOp]:
        return self._of(SEEN)


def diff_deals(
    complex_no: str,
    incoming: list[DealDTO],
    existing: dict[str, DealState],
) -> ComplexDealDiff:
    """한 단지의 실거래 변화 연산 목록 산출."""
    ops: list[DealOp] = []
    handled: set[str] = set()

    for dto in incoming:
        if dto.deal_key in handled:
            continue
        handled.add(dto.deal_key)
        e = existing.get(dto.deal_key)
        if e is None:
            # 처음 보는 거래 — 취소 상태로 등장하면 취소로 분류(신규로 알리지 않음)
            ops.append(DealOp(CANCELLED if dto.cancelled else NEW, dto))
        elif dto.cancelled and not e.cancelled:
            ops.append(DealOp(CANCELLED, dto))
        else:
            ops.append(DealOp(SEEN, dto))

    return ComplexDealDiff(complex_no, ops)
