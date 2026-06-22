"""지난 경매 보관기간 정리(repo.purge_old_auctions) + 단지 상세 경매 행(in_progress) 검증."""

from __future__ import annotations

from myhouse.constants import now_kst, to_iso
from myhouse.db import repo
from myhouse.db.engine import get_session, init_db, make_engine
from myhouse.db.models import Auction, Complex
from myhouse.web import queries as q


def _seed(tmp_path):
    """단지 1곳에 지난(오래된/최근) · 진행중(미래) · 기일미상 경매를 적재."""
    engine = make_engine(tmp_path / "auction_retention.db")
    init_db(engine)
    now = to_iso(now_kst())
    with get_session(engine) as s:
        s.add(Complex(
            complex_no="122025", name="테스트단지", address="서울시 강남구 대치동",
            lat=37.5, lon=127.0, is_active=True, first_seen_at=now, updated_at=now,
        ))
        s.commit()
        rows = [
            # (key, sale_date, in_progress) — 날짜는 ISO 'YYYY-MM-DD'
            ("AU_OLD", "2026-01-01", False),     # 오래된 지난 경매(>90일) → 삭제 대상
            ("AU_RECENT", "2026-06-01", False),  # 최근 지난 경매(<90일) → 보존
            ("AU_FUTURE", "2026-09-01", True),   # 미래 매각기일(진행중) → 보존
            ("AU_NODATE", None, True),           # 기일미상 → 보존
        ]
        for key, sale_date, in_progress in rows:
            s.add(Auction(
                auction_key=key, complex_no="122025", case_no=f"2024타경{key}",
                address="강남구 대치동 1", sale_date=sale_date, in_progress=in_progress,
                appraisal_manwon=200000, min_bid_manwon=160000, min_bid_ratio=80,
                court_name="서울중앙지방법원",
            ))
        s.commit()
    return engine


def test_purge_old_auctions_deletes_only_past_beyond_cutoff(tmp_path):
    engine = _seed(tmp_path)
    with get_session(engine) as s:
        # 오늘(2026-06-22 가정)에서 90일 전 컷오프 ≈ 2026-03-24
        deleted = repo.purge_old_auctions(s, "2026-03-24")
        assert deleted == 1  # AU_OLD 만 삭제
        remaining = {a.auction_key for a in repo.get_auctions_for_complex(s, "122025")}
        assert remaining == {"AU_RECENT", "AU_FUTURE", "AU_NODATE"}


def test_purge_is_idempotent(tmp_path):
    engine = _seed(tmp_path)
    with get_session(engine) as s:
        assert repo.purge_old_auctions(s, "2026-03-24") == 1
        assert repo.purge_old_auctions(s, "2026-03-24") == 0  # 재실행 0건


def test_build_auction_rows_exposes_in_progress_for_complex(tmp_path):
    engine = _seed(tmp_path)
    with get_session(engine) as s:
        rows = q.build_auction_rows(s, q.AuctionFilters(complex_no="122025"), None)
        by_key = {r.auction_key: r for r in rows}
        assert by_key["AU_FUTURE"].in_progress is True
        assert by_key["AU_RECENT"].in_progress is False
        # 단지 지정 시 4건 모두 반환(보관 정리 전)
        assert len(rows) == 4
