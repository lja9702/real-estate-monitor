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


# ── 사후 정합(_reconcile_matured) ──────────────────────────────────────────────
class _StubDxdyClient:
    """fetch_case_dxdy 만 가진 스텁 — 사건번호별 기일내역 응답을 미리 심는다."""

    def __init__(self, by_case):
        self._by_case = by_case  # csNo → payload dict
        self.calls = []

    def fetch_case_dxdy(self, court_code, cs_no):
        from myhouse.court.case_dxdy_parser import parse_case_dxdy

        self.calls.append((court_code, cs_no))
        return parse_case_dxdy(self._by_case.get(cs_no, {"data": {"dlt_dxdyDtsLst": []}}))


def _config():
    from types import SimpleNamespace

    from myhouse.settings import AuctionsConfig

    return SimpleNamespace(auctions=AuctionsConfig())


def _seed_matured(s, *, case_no, court_code, item_no, sale_date, min_bid, appraisal):
    from myhouse.db.models import Auction, Complex

    s.add(Complex(complex_no="C1", name="한가람아파트", cortar_no="1117012900",
                  bonbun="0404", bubun="0000"))
    s.commit()
    s.add(Auction(
        auction_key="ak1", complex_no="C1", court_code=court_code, court_name="서울서부지방법원",
        case_no=case_no, item_no=item_no, address="서울 용산구 이촌동 404", building_name="한가람아파트",
        usage_name="아파트", area_excl=84.0, appraisal_manwon=appraisal, min_bid_manwon=min_bid,
        min_bid_ratio=100, fail_count=1, sale_date=sale_date, in_progress=True,
        first_seen_at="2026-01-01T00:00:00+09:00", last_seen_at="2026-01-01T00:00:00+09:00",
    ))
    s.commit()


# 라이브 검증된 한가람 페이로드(매각→미납→유찰→매각 22.36억).
_HANGARAM = {"data": {"dlt_dxdyDtsLst": [
    {"dspslGdsSeq": "1", "tsLwsDspslPrc": "2,110,000,000원",
     "dxdyTime": "2026.05.19(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "유찰"},
    {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,688,000,000원",
     "dxdyTime": "2026.06.23(10:00)", "auctnDxdyKndNm": "매각기일",
     "dxdyRslt": "매각<br />(2,236,524,000원)"},
]}}


def test_reconcile_marks_sold(engine):
    """매각기일 지난 미확정 물건 → 사건 기일내역으로 '매각' 확정 + 낙찰가 + 알림."""
    from myhouse.core.auction_collector import SOLD, _reconcile_matured
    from myhouse.db.engine import get_session
    from myhouse.db.models import Auction

    with get_session(engine) as s:
        _seed_matured(s, case_no="2025타경1678", court_code="B000215", item_no="1",
                      sale_date="2026-06-23", min_bid=168800, appraisal=211000)
        client = _StubDxdyClient({"20250130001678": _HANGARAM})
        res = _reconcile_matured(s, client, _config(), "2026-06-25", "2026-06-25T11:30:00+09:00")

        assert client.calls == [("B000215", "20250130001678")]  # csNo 재구성 정확
        assert res.sold == 1 and res.polled == 1
        row = s.get(Auction, "ak1")
        assert row.outcome == "sold"
        assert row.outcome_label == "매각"
        assert row.final_bid_manwon == 223652  # 2,236,524,000 ÷ 10000
        assert row.outcome_date == "2026-06-23"
        assert row.in_progress is False
        ops = res.ops_by_complex["C1"]
        assert len(ops) == 1 and ops[0].kind == SOLD and ops[0].final_bid_manwon == 223652


def test_reconcile_reactivates_on_failed_reschedule(engine):
    """유찰 + 재공고된 다음 매각기일 → 다음 회차로 재활성(outcome 미확정 유지)·유찰 알림."""
    from myhouse.core.auction_collector import FAILED, _reconcile_matured
    from myhouse.db.engine import get_session
    from myhouse.db.models import Auction

    payload = {"data": {"dlt_dxdyDtsLst": [
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,000,000,000원",
         "dxdyTime": "2026.06.20(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "유찰"},
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "800,000,000원",
         "dxdyTime": "2026.08.01(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": ""},
    ]}}
    with get_session(engine) as s:
        _seed_matured(s, case_no="2025타경1678", court_code="B000215", item_no="1",
                      sale_date="2026-06-20", min_bid=100000, appraisal=100000)
        client = _StubDxdyClient({"20250130001678": payload})
        res = _reconcile_matured(s, client, _config(), "2026-06-25", "2026-06-25T11:30:00+09:00")

        assert res.failed == 1 and res.sold == 0
        row = s.get(Auction, "ak1")
        assert row.outcome is None  # 재활성 — 종국 아님(다음 회차 추적 계속)
        assert row.sale_date == "2026-08-01"  # 다음 매각기일로 갱신
        assert row.min_bid_manwon == 80000  # 다음 회차 최저가
        assert row.min_bid_ratio == 80
        assert row.fail_count == 2  # 유찰 +1
        ops = res.ops_by_complex["C1"]
        assert len(ops) == 1 and ops[0].kind == FAILED and ops[0].next_sale_date == "2026-08-01"


def test_reconcile_pending_keeps_polling(engine):
    """결과 미확정·다음기일 없음 → outcome 미확정 유지·알림 없음(다음 회차 재폴링)."""
    from myhouse.core.auction_collector import _reconcile_matured
    from myhouse.db.engine import get_session
    from myhouse.db.models import Auction

    payload = {"data": {"dlt_dxdyDtsLst": [
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,000,000,000원",
         "dxdyTime": "2026.06.20(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "유찰"},
    ]}}  # 유찰만, 재공고 다음기일 아직 없음
    with get_session(engine) as s:
        _seed_matured(s, case_no="2025타경1678", court_code="B000215", item_no="1",
                      sale_date="2026-06-20", min_bid=100000, appraisal=100000)
        client = _StubDxdyClient({"20250130001678": payload})
        res = _reconcile_matured(s, client, _config(), "2026-06-25", "2026-06-25T11:30:00+09:00")

        assert res.sold == 0 and res.failed == 0 and res.withdrawn == 0
        row = s.get(Auction, "ak1")
        assert row.outcome is None
        assert row.reconciled_at == "2026-06-25T11:30:00+09:00"  # 폴링은 함
        assert res.ops_by_complex.get("C1") is None  # 알림 없음
