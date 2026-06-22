"""급매 탐지 단위 테스트 — 하한가 계산·임계치·트리거·평형/거래유형 스코프 (순수 함수)."""

from __future__ import annotations

from tests.conftest import make_dto

from myhouse.constants import ListingStatus, TradeType, now_kst
from myhouse.core.diff import ListingState, diff_complex
from myhouse.core.flash import detect_flash_deals
from myhouse.db.models import Listing


def _listing(
    article_no: str,
    price_deal: int,
    *,
    area_excl: float = 81.0,
    trade_type: TradeType = TradeType.SALE,
    status: ListingStatus = ListingStatus.ACTIVE,
) -> Listing:
    return Listing(
        article_no=article_no,
        complex_no="111",
        trade_type=trade_type,
        price_deal=price_deal,
        area_excl=area_excl,
        status=status,
        price_fingerprint=f"{price_deal}|None",
    )


def _diff(incoming, existing_states=None):
    return diff_complex(
        "111", incoming, existing_states or {}, now=now_kst(),
        removal_debounce_hours=20, fetch_complete=True,
    )


def _detect(diff, existing, **kw):
    kw.setdefault("trade_types", {TradeType.SALE})
    kw.setdefault("min_drop_pct", 3.0)
    return detect_flash_deals(diff, existing, **kw)


def test_new_below_floor_is_flash():
    floor = [_listing("old", 120000)]
    d = _diff([make_dto("new", price_deal=110000)])  # NEW
    sigs = _detect(d, floor)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.article_no == "new"
    assert s.prior_floor == 120000
    assert s.price_deal == 110000
    assert s.drop_amount == 10000
    assert round(s.drop_pct, 1) == 8.3
    assert s.trigger == "new"


def test_at_or_above_floor_not_flash():
    floor = [_listing("old", 120000)]
    d = _diff([make_dto("eq", price_deal=120000), make_dto("hi", price_deal=121000)])
    assert _detect(d, floor) == []


def test_below_floor_under_threshold_not_flash():
    floor = [_listing("old", 120000)]
    d = _diff([make_dto("new", price_deal=118000)])  # 1.67% < 3%
    assert _detect(d, floor) == []


def test_no_prior_listing_in_pyeong_not_flash():
    # 직전 매물이 다른 평형(110㎡)뿐 → 81㎡ 신규는 비교할 하한가 없음
    floor = [_listing("other", 90000, area_excl=110.0)]
    d = _diff([make_dto("new", price_deal=80000, area_excl=81.0, area_name="82A")])
    assert _detect(d, floor) == []


def test_multiple_new_same_run_each_vs_prerun_floor():
    # 같은 회차 같은 평형 급매 2건 — 둘 다 '회차 이전 하한가(120000)' 기준으로 잡혀야 한다.
    floor = [_listing("old", 120000)]
    d = _diff([make_dto("n1", price_deal=110000), make_dto("n2", price_deal=108000)])
    sigs = _detect(d, floor)
    assert {s.article_no for s in sigs} == {"n1", "n2"}
    assert all(s.prior_floor == 120000 for s in sigs)


def test_price_drop_breaks_floor_is_flash():
    existing = [_listing("a", 120000)]
    states = {"a": ListingState("a", ListingStatus.ACTIVE, "120000|None", "", 120000, None)}
    d = _diff([make_dto("a", price_deal=110000)], states)  # PRICE_CHANGED ↓
    sigs = _detect(d, existing, include_price_drops=True)
    assert len(sigs) == 1 and sigs[0].trigger == "price_drop"
    # 가격인하 트리거를 끄면 잡지 않는다
    assert _detect(d, existing, include_price_drops=False) == []


def test_trade_type_scope_excludes_other():
    floor = [_listing("old", 120000)]
    d = _diff([make_dto("j", price_deal=10000, trade_type=TradeType.JEONSE)])
    assert _detect(d, floor, trade_types={TradeType.SALE}) == []


def test_floor_ignores_inactive_listings():
    # REMOVED(거래완료) 100000 은 하한가 계산에서 빠진다 → 하한은 ACTIVE 120000.
    floor = [
        _listing("removed", 100000, status=ListingStatus.REMOVED),
        _listing("active", 120000),
    ]
    d = _diff([make_dto("new", price_deal=110000)])
    sigs = _detect(d, floor)
    assert len(sigs) == 1 and sigs[0].prior_floor == 120000


def test_min_drop_manwon_cut():
    floor = [_listing("old", 120000)]
    d = _diff([make_dto("new", price_deal=115000)])  # 4.17% ≥ 3%, 하락 5000만
    assert _detect(d, floor, min_drop_manwon=3000)  # 5000 ≥ 3000 → 급매
    assert _detect(d, floor, min_drop_manwon=8000) == []  # 5000 < 8000 → 컷
