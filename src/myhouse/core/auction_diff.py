"""법원경매 변화 감지 (순수 함수 — DB/네트워크 무의존).

실거래·허가와 달리 경매 물건은 '살아 움직인다' — 유찰되면 최저가가 내려가고 매각기일이
바뀐다. 따라서 변화는 NEW(처음 보는 물건)뿐 아니라:
  - PRICE_DOWN: 최저가 하락(유찰) — 가장 유용한 신호
  - DATE_CHANGED: 매각기일 변경(연기 등)
  - SEEN: 변동 없음 — 저장만 갱신(알림 없음)
종결(매각/취하)은 검색 결과에서 빠지면서 사라지므로 이 '전진(forward)' diff 에서는 다루지
않는다(매물 removal 디바운스처럼 추후 보강). 알림 대상은 NEW + PRICE_DOWN (+옵션 DATE_CHANGED).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..court.auction_parser import AuctionDTO

NEW = "new"
PRICE_DOWN = "price_down"
DATE_CHANGED = "date_changed"
SEEN = "seen"
# 사후 정합(사건 기일내역) 결과 op — forward 검색에서 사라진 매각기일 지난 물건.
SOLD = "sold"  # 매각(낙찰)
FAILED = "failed"  # 유찰 또는 대금미납 재매각(재공고 시 다음기일 동봉)
WITHDRAWN = "withdrawn"  # 취하·취소·기각 등 종국

# 정합으로 확정된 결과(알림 대상) op kind 집합.
OUTCOME_KINDS = (SOLD, FAILED, WITHDRAWN)


@dataclass
class AuctionOp:
    kind: str
    dto: AuctionDTO
    old_min_bid_manwon: int | None = None  # PRICE_DOWN: 직전 최저가
    old_sale_date: str | None = None  # PRICE_DOWN/DATE_CHANGED: 직전 매각기일
    view_url: str | None = None  # 옥션원 물건 직링크(해석됐을 때) — 알림 링크용
    outcome_label: str | None = None  # SOLD/FAILED/WITHDRAWN: 사람용 라벨
    final_bid_manwon: int | None = None  # SOLD: 낙찰가(만원)
    next_sale_date: str | None = None  # FAILED: 재공고된 다음 매각기일


@dataclass
class ComplexAuctionDiff:
    complex_no: str
    ops: list[AuctionOp] = field(default_factory=list)

    @property
    def alerts(self) -> list[AuctionOp]:
        """알림 대상 op(NEW·PRICE_DOWN·DATE_CHANGED). SEEN 제외."""
        return [o for o in self.ops if o.kind != SEEN]


def diff_auctions(
    complex_no: str,
    incoming: list[AuctionDTO],
    existing: dict[str, StoredAuction],
) -> ComplexAuctionDiff:
    """한 단지에 매칭된 물건들의 변화 연산.

    existing: auction_key → 저장행(min_bid_manwon·sale_date 를 가진 객체). DB 모델이든
    테스트 더블이든 두 속성만 있으면 된다(덕타이핑).
    """
    ops: list[AuctionOp] = []
    handled: set[str] = set()
    for dto in incoming:
        if dto.auction_key in handled:
            continue
        handled.add(dto.auction_key)
        row = existing.get(dto.auction_key)
        if row is None:
            ops.append(AuctionOp(NEW, dto))
            continue
        old_min = getattr(row, "min_bid_manwon", None)
        old_date = getattr(row, "sale_date", None)
        if (
            dto.min_bid_manwon is not None
            and old_min is not None
            and dto.min_bid_manwon < old_min
        ):
            ops.append(
                AuctionOp(PRICE_DOWN, dto, old_min_bid_manwon=old_min, old_sale_date=old_date)
            )
        elif dto.sale_date and old_date and dto.sale_date != old_date:
            ops.append(AuctionOp(DATE_CHANGED, dto, old_sale_date=old_date))
        else:
            ops.append(AuctionOp(SEEN, dto))
    return ComplexAuctionDiff(complex_no, ops)


# 타입 힌트용 프로토콜 대용(런타임 무의존) — 실제로는 db.models.Auction 또는 테스트 더블.
class StoredAuction:  # noqa: D101 - 덕타이핑 마커
    min_bid_manwon: int | None
    sale_date: str | None
