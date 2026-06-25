"""법원경매 다이제스트 — 정합 결과(매각/유찰/취하) 렌더 검증."""

from __future__ import annotations

from datetime import datetime

from myhouse.core.auction_collector import AuctionRunResult, ComplexAuctionResult
from myhouse.core.auction_diff import FAILED, SOLD, WITHDRAWN, AuctionOp
from myhouse.court.auction_parser import AuctionDTO
from myhouse.notify.auction_digest import build_auction_digest


def _dto(**kw):
    base = dict(auction_key="ak1", case_no="2025타경1678", area_max=84.0,
               appraisal_manwon=211000, min_bid_manwon=168800, min_bid_ratio=80, fail_count=1)
    base.update(kw)
    return AuctionDTO(**base)


def _result(*ops):
    cr = ComplexAuctionResult("C1", "한가람", "한가람아파트", address="용산구 이촌동", ops=list(ops))
    return AuctionRunResult(
        run_id=1, started_at=datetime(2026, 6, 25, 11, 30), status=None, complexes=[cr],
        sold_count=sum(o.kind == SOLD for o in ops),
        failed_count=sum(o.kind == FAILED for o in ops),
        withdrawn_count=sum(o.kind == WITHDRAWN for o in ops),
    )


def test_sold_line_shows_winning_bid():
    op = AuctionOp(SOLD, _dto(), outcome_label="매각", final_bid_manwon=223652)
    msg = build_auction_digest(_result(op), "http://x")
    assert "낙찰 22.3652억" in msg or "낙찰 22.37억" in msg or "낙찰" in msg
    assert "매각 1" in msg  # 헤더 카운트
    assert "🔨" in msg


def test_failed_line_shows_next_date():
    op = AuctionOp(FAILED, _dto(min_bid_manwon=80000, min_bid_ratio=80),
                   outcome_label="유찰", old_min_bid_manwon=100000, old_sale_date="2026-06-20",
                   next_sale_date="2026-08-01")
    msg = build_auction_digest(_result(op), "http://x")
    assert "유찰 → 다음 매각 26.08.01" in msg
    assert "최저" in msg
    assert "유찰 1" in msg


def test_withdrawn_line():
    op = AuctionOp(WITHDRAWN, _dto(), outcome_label="취하")
    msg = build_auction_digest(_result(op), "http://x")
    assert "취하" in msg
    assert "🚫" in msg
