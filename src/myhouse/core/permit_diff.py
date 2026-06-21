"""토지거래허가 변화 감지 (순수 함수 — DB/네트워크 무의존).

허가도 실거래처럼 과거 사실의 누적이라 '사라짐' 판정이 없다. 변화는 NEW(처음 보는 허가)뿐.
같은 접수가 허가→취소로 바뀌는 경우는 같은 permit_key 로 재관측되어 SEEN(행 갱신)으로
흐른다 — 사용자 설정상 알림은 '신규 허가'만이므로 취소/불허가는 저장만 하고 알리지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..seoul.permit_parser import PermitDTO

NEW = "new"
SEEN = "seen"


@dataclass
class PermitOp:
    kind: str
    dto: PermitDTO


@dataclass
class ComplexPermitDiff:
    complex_no: str
    ops: list[PermitOp] = field(default_factory=list)

    @property
    def new(self) -> list[PermitOp]:
        return [o for o in self.ops if o.kind == NEW]

    @property
    def seen(self) -> list[PermitOp]:
        return [o for o in self.ops if o.kind == SEEN]


def diff_permits(
    complex_no: str,
    incoming: list[PermitDTO],
    existing_keys: set[str],
) -> ComplexPermitDiff:
    """한 단지에 매칭된 허가들의 변화 연산. existing_keys 는 이미 저장된 permit_key 집합."""
    ops: list[PermitOp] = []
    handled: set[str] = set()
    for dto in incoming:
        if dto.permit_key in handled:
            continue
        handled.add(dto.permit_key)
        ops.append(PermitOp(NEW if dto.permit_key not in existing_keys else SEEN, dto))
    return ComplexPermitDiff(complex_no, ops)
