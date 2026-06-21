"""실거래 diff + 평형 선택 테스트."""

from __future__ import annotations

from myhouse.constants import TradeType
from myhouse.core.deal_collector import select_pyeongs
from myhouse.core.deal_diff import CANCELLED, NEW, SEEN, DealState, diff_deals
from myhouse.naver.deal_parser import DealDTO, PyeongInfo
from myhouse.settings import FilterSpec


def _dto(key: str, *, price: int = 200000, cancelled: bool = False) -> DealDTO:
    return DealDTO(
        deal_key=key,
        complex_no="9",
        trade_type=TradeType.SALE,
        deal_date="2026-01-01",
        price_deal=price,
        cancelled=cancelled,
    )


def test_diff_classifies_new_cancel_seen():
    existing = {
        "k_seen": DealState("k_seen", cancelled=False),
        "k_cancel": DealState("k_cancel", cancelled=False),
        "k_gone": DealState("k_gone", cancelled=False),  # 이번에 안 보임 → 무시
    }
    incoming = [
        _dto("k_seen"),  # 그대로 → SEEN
        _dto("k_cancel", cancelled=True),  # 기존이 취소됨 → CANCELLED
        _dto("k_new"),  # 처음 → NEW
        _dto("k_born_cancelled", cancelled=True),  # 처음부터 취소 → CANCELLED
    ]
    diff = diff_deals("9", incoming, existing)

    kinds = {o.dto.deal_key: o.kind for o in diff.ops}
    assert kinds["k_seen"] == SEEN
    assert kinds["k_cancel"] == CANCELLED
    assert kinds["k_new"] == NEW
    assert kinds["k_born_cancelled"] == CANCELLED
    assert "k_gone" not in kinds  # 누락은 연산 없음

    assert {o.dto.deal_key for o in diff.new} == {"k_new"}
    assert {o.dto.deal_key for o in diff.cancelled} == {"k_cancel", "k_born_cancelled"}


def test_diff_dedups_incoming():
    diff = diff_deals("9", [_dto("k"), _dto("k")], {})
    assert len(diff.ops) == 1


def test_diff_already_cancelled_is_seen():
    """이미 취소로 기록된 거래가 또 취소로 들어와도 새 이벤트 아님."""
    existing = {"k": DealState("k", cancelled=True)}
    diff = diff_deals("9", [_dto("k", cancelled=True)], existing)
    assert diff.ops[0].kind == SEEN


def _p(no: str, supply: float, excl: float | None = None) -> PyeongInfo:
    return PyeongInfo(pyeong_no=no, area_supply=supply, area_excl=excl)


def test_select_pyeongs_by_supply_area():
    pyeongs = [_p("1", 60), _p("2", 82), _p("3", 140)]
    filt = FilterSpec(area_supply_min_m2=66, area_supply_max_m2=131)
    assert [p.pyeong_no for p in select_pyeongs(pyeongs, filt)] == ["2"]


def test_select_pyeongs_no_filter_returns_all():
    pyeongs = [_p("1", 60), _p("2", 140)]
    filt = FilterSpec(area_supply_min_m2=66, area_supply_max_m2=131)
    assert len(select_pyeongs(pyeongs, filt, use_area_filter=False)) == 2


def test_select_pyeongs_excl_bounds():
    pyeongs = [_p("1", 100, excl=70), _p("2", 100, excl=120)]
    filt = FilterSpec(area_excl_min_m2=None, area_excl_max_m2=100)
    assert [p.pyeong_no for p in select_pyeongs(pyeongs, filt)] == ["1"]
