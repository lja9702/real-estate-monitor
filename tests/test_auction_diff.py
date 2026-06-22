"""경매 diff 테스트 — NEW·PRICE_DOWN·DATE_CHANGED·SEEN 판정 + 중복 dedup + 우선순위."""

from __future__ import annotations

from dataclasses import dataclass

from myhouse.core.auction_diff import (
    DATE_CHANGED,
    NEW,
    PRICE_DOWN,
    SEEN,
    diff_auctions,
)
from myhouse.court.auction_parser import AuctionDTO


def _dto(key: str, *, min_bid=None, sale_date=None, fail=0) -> AuctionDTO:
    return AuctionDTO(
        auction_key=key, case_no="2024타경1",
        min_bid_manwon=min_bid, sale_date=sale_date, fail_count=fail,
    )


@dataclass
class _Stored:  # db.models.Auction 더블(덕타이핑)
    min_bid_manwon: int | None = None
    sale_date: str | None = None


def test_new_when_not_existing():
    diff = diff_auctions("C1", [_dto("a", min_bid=1000)], {})
    assert [o.kind for o in diff.ops] == [NEW]
    assert diff.alerts[0].kind == NEW


def test_price_down_captures_old_values():
    existing = {"a": _Stored(min_bid_manwon=1000, sale_date="2026-07-01")}
    diff = diff_auctions("C1", [_dto("a", min_bid=800, sale_date="2026-08-01")], existing)
    op = diff.ops[0]
    assert op.kind == PRICE_DOWN
    assert op.old_min_bid_manwon == 1000
    assert op.old_sale_date == "2026-07-01"


def test_date_changed_without_price_change():
    existing = {"a": _Stored(min_bid_manwon=1000, sale_date="2026-07-01")}
    diff = diff_auctions("C1", [_dto("a", min_bid=1000, sale_date="2026-08-05")], existing)
    assert diff.ops[0].kind == DATE_CHANGED
    assert diff.ops[0].old_sale_date == "2026-07-01"


def test_seen_when_unchanged_not_alerted():
    existing = {"a": _Stored(min_bid_manwon=1000, sale_date="2026-07-01")}
    diff = diff_auctions("C1", [_dto("a", min_bid=1000, sale_date="2026-07-01")], existing)
    assert diff.ops[0].kind == SEEN
    assert diff.alerts == []  # SEEN 은 알림에서 제외


def test_price_down_takes_priority_over_date_change():
    """유찰은 보통 가격↓ + 기일변경이 동시 — PRICE_DOWN 으로 묶는다."""
    existing = {"a": _Stored(min_bid_manwon=1000, sale_date="2026-07-01")}
    diff = diff_auctions("C1", [_dto("a", min_bid=640, sale_date="2026-08-05")], existing)
    assert diff.ops[0].kind == PRICE_DOWN


def test_price_up_is_seen_not_alert():
    """최저가 상승(드묾)은 알림 아님(SEEN)."""
    existing = {"a": _Stored(min_bid_manwon=1000, sale_date="2026-07-01")}
    diff = diff_auctions("C1", [_dto("a", min_bid=1200, sale_date="2026-07-01")], existing)
    assert diff.ops[0].kind == SEEN


def test_dedup_same_key():
    diff = diff_auctions("C1", [_dto("a", min_bid=1000), _dto("a", min_bid=900)], {})
    assert len(diff.ops) == 1  # 같은 auction_key 중복 제거(첫 건만)
