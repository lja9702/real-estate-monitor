"""경매 수집기 ORM 반영(_apply_auction_ops) 테스트 — 공유 지번 형제 단지 중복 PK 회피."""

from __future__ import annotations


def test_shared_jibun_no_duplicate_pk(engine):
    """같은 지번에 추적단지 둘(과천 주공8·9=부림동 41) → 동일 물건이 한쪽에만 귀속, 중복 PK 없음.

    diff 는 단지별로 계산되므로 두 번째 단지는 같은 auction_key 를 NEW 로 본다. 가드가 없으면
    session.add 가 전역 PK(auction_key)를 중복 삽입해 IntegrityError 로 run 전체가 롤백된다.
    """
    from sqlmodel import select

    from myhouse.core.auction_collector import _apply_auction_ops
    from myhouse.core.auction_diff import NEW, diff_auctions
    from myhouse.court.auction_parser import AuctionDTO
    from myhouse.db.engine import get_session
    from myhouse.db.models import Auction, Complex

    dto = AuctionDTO(
        auction_key="shared-docid-41", case_no="2024타경41",
        dong_code="41290110", bonbun="0041", bubun="0000",
        address="과천시 부림동 41", usage_name="아파트",
        min_bid_manwon=160000, sale_date="2026-09-01",
    )
    now_s = "2026-05-01T00:00:00+09:00"
    with get_session(engine) as s:
        s.add(Complex(complex_no="A", name="주공8단지", cortar_no="4129011000",
                      bonbun="0041", bubun="0000"))
        s.add(Complex(complex_no="B", name="주공9단지", cortar_no="4129011000",
                      bonbun="0041", bubun="0000"))
        s.commit()
        alerts_a = _apply_auction_ops(s, diff_auctions("A", [dto], {}), {}, "A", 1, now_s, None)
        alerts_b = _apply_auction_ops(s, diff_auctions("B", [dto], {}), {}, "B", 1, now_s, None)
        assert len(alerts_a) == 1 and alerts_a[0].kind == NEW  # A 에 NEW 1건
        assert alerts_b == []  # B 는 중복으로 skip(알림도 1회)
        rows = list(s.exec(select(Auction)))
        assert len(rows) == 1 and rows[0].complex_no == "A"
