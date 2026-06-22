"""추적 해제(is_active=False) 단지는 매물·실거래·급매·토지허가·경매 목록/지도/드롭다운에서
모두 숨긴다 — 단, 단지 상세(complex_no 지정)는 그대로 보여준다(추적관리에서 들어오는 경로)."""

from __future__ import annotations

from myhouse.constants import ListingStatus, TradeType, now_kst, to_iso
from myhouse.db.engine import get_session, init_db, make_engine
from myhouse.db.models import (
    Auction,
    Complex,
    Deal,
    FlashDeal,
    LandPermit,
    Listing,
)
from myhouse.web import queries as q


def _seed(tmp_path):
    """활성 단지 '100' 과 추적 해제 단지 '200' 에 각 카테고리 1건씩 적재."""
    engine = make_engine(tmp_path / "untracked.db")
    init_db(engine)
    now = to_iso(now_kst())
    today = now_kst().date().isoformat()
    with get_session(engine) as s:
        for no, name, active in (("100", "활성단지", True), ("200", "해제단지", False)):
            s.add(Complex(
                complex_no=no, name=name, address="서울시 강남구 대치동",
                lat=37.5, lon=127.0, is_active=active,
                first_seen_at=now, updated_at=now,
            ))
        s.commit()  # 부모(단지) 먼저 커밋 — 자식 행들의 FK(complex_no) 보장
        for no in ("100", "200"):
            s.add(Listing(
                article_no=f"A{no}", complex_no=no, trade_type=TradeType.SALE,
                price_deal=150000, area_excl=84.0, status=ListingStatus.ACTIVE,
                cluster_key=f"ck{no}", first_seen_at=now, last_seen_at=now,
            ))
            s.add(Deal(
                deal_key=f"D{no}", complex_no=no, trade_type=TradeType.SALE,
                deal_date=today, price_deal=148000, area_excl=84.0, cancelled=False,
            ))
            s.add(LandPermit(
                permit_key=f"P{no}", complex_no=no, sgg_cd="11680",
                address="강남구 대치동 1", permit_date=today,
            ))
            s.add(Auction(
                auction_key=f"AU{no}", complex_no=no, case_no=f"2024타경{no}",
                address="강남구 대치동 1", sale_date=today,
            ))
        s.commit()  # 단지·매물 먼저 — flash_deal.article_no FK 보장
        for no in ("100", "200"):
            s.add(FlashDeal(
                article_no=f"A{no}", complex_no=no, trade_type=TradeType.SALE,
                area_excl=84.0, area_key=84, price_deal=150000, prior_floor=170000,
                drop_amount=20000, drop_pct=11.7, trigger="new",
                detected_at=now, detected_run_id=1,
            ))
        s.commit()
    return engine


def test_untracked_complex_hidden_from_all_lists(tmp_path):
    engine = _seed(tmp_path)
    with get_session(engine) as s:
        # 매물 (area-group 목록)
        rows = q.build_area_group_rows(s, q.Filters(), None)
        assert {r.complex_no for r in rows} == {"100"}
        # 실거래
        rows = q.build_deal_rows(s, q.DealFilters(), None)
        assert {r.complex_no for r in rows} == {"100"}
        # 급매
        rows = q.build_flash_rows(s, q.FlashFilters(), None)
        assert {r.complex_no for r in rows} == {"100"}
        # 토지거래허가
        rows = q.build_permit_rows(s, q.PermitFilters(), None)
        assert {r.complex_no for r in rows} == {"100"}
        # 경매
        rows = q.build_auction_rows(s, q.AuctionFilters(), None)
        assert {r.complex_no for r in rows} == {"100"}
        # 지도 마커
        assert {r.complex_no for r in q.get_map_complexes(s)} == {"100"}


def test_untracked_complex_hidden_from_dropdowns(tmp_path):
    engine = _seed(tmp_path)
    with get_session(engine) as s:
        assert {c.complex_no for c in q.list_complexes_filtered(s)} == {"100"}
        assert {c.complex_no for c in q.deal_complexes(s)} == {"100"}
        assert {c.complex_no for c in q.flash_complexes(s)} == {"100"}
        assert {c.complex_no for c in q.permit_complexes(s)} == {"100"}
        assert {c.complex_no for c in q.auction_complexes(s)} == {"100"}


def test_untracked_complex_detail_still_visible(tmp_path):
    """추적관리 페이지에서 해제 단지 상세로 들어오는 경로는 살려둔다."""
    engine = _seed(tmp_path)
    with get_session(engine) as s:
        # 단지 상세 매물 (complex_no 지정 시 필터 미적용)
        rows = q.build_cluster_rows(s, q.Filters(complex_no="200", status="all"), None)
        assert {r.complex_no for r in rows} == {"200"}
        # 단지 상세 실거래
        deals = q.recent_deals_for_complex(s, "200", None)
        assert {d.complex_no for d in deals} == {"200"}
