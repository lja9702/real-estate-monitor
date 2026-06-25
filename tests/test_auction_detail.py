"""경매 물건 상세(기일내역) 서비스 — 캐시·응답 조립. 네트워크 없이(allow_fetch=False/캐시주입)."""

from __future__ import annotations

from myhouse.core import auction_detail
from myhouse.core.auction_detail import clear_cache, get_case_events
from myhouse.court.case_dxdy_parser import AuctionDateEvent
from myhouse.db.engine import get_session
from myhouse.db.models import Auction, Complex
from myhouse.web.queries import build_auction_detail


def _seed(s):
    s.add(Complex(complex_no="C1", name="한가람아파트", cortar_no="1117012900"))
    s.commit()
    s.add(Auction(
        auction_key="ak1", complex_no="C1", court_code="B000215", court_name="서울서부지방법원",
        case_no="2025타경1678", item_no="1", address="서울 용산구 이촌동 404",
        building_name="한가람아파트", usage_name="아파트", area_excl=84.0,
        appraisal_manwon=211000, min_bid_manwon=168800, min_bid_ratio=80, fail_count=1,
        sale_date="2026-06-23", outcome="sold", outcome_label="매각", final_bid_manwon=223652,
        outcome_date="2026-06-23", remarks="지분 매각임. 위반건축물 등재",
        first_seen_at="x", last_seen_at="x",
    ))
    s.commit()


def test_get_case_events_no_fetch_returns_cached(engine):
    """allow_fetch=False 면 네트워크 호출 없이 캐시만(없으면 빈)."""
    clear_cache()
    with get_session(engine) as s:
        _seed(s)
        row = s.get(Auction, "ak1")
        assert get_case_events(row, allow_fetch=False) == []  # 캐시 없음 → 빈

        # 캐시 주입 후엔 그대로 반환(여전히 네트워크 없음).
        ev = [AuctionDateEvent(date="2026-06-23", kind="매각기일", result="매각", item_seq="1")]
        auction_detail._CACHE["ak1"] = (auction_detail._now() + 3600, ev)
        assert get_case_events(row, allow_fetch=False) == ev
    clear_cache()


def test_build_auction_detail_shape(engine):
    """저장행 + 기일내역 → 상세 dict(플래그·결과·이벤트 포함)."""
    with get_session(engine) as s:
        _seed(s)
        events = [
            AuctionDateEvent(date="2026-05-19", kind="매각기일", result="유찰",
                             low_price_manwon=211000, item_seq="1"),
            AuctionDateEvent(date="2026-06-23", kind="매각기일", result="매각(2,236,524,000원)",
                             low_price_manwon=168800, item_seq="1"),
        ]
        d = build_auction_detail(s, "ak1", events)
    assert d is not None
    assert d["complex_name"] == "한가람아파트"
    assert d["outcome"] == "sold" and d["final_bid_manwon"] == 223652
    assert d["flags"] == ["지분매각", "위반건축물"]
    assert len(d["events"]) == 2
    assert d["events"][1]["result"].startswith("매각")
    assert d["events"][0]["kind"] == "매각기일"


def test_build_auction_detail_missing(engine):
    with get_session(engine) as s:
        assert build_auction_detail(s, "nope", []) is None
