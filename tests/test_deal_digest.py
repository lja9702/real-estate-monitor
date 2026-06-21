"""실거래 다이제스트 메시지 구성 테스트."""

from __future__ import annotations

from myhouse.constants import RunStatus, TradeType, now_kst
from myhouse.core.deal_collector import ComplexDealResult, DealRunResult
from myhouse.naver.deal_parser import DealDTO
from myhouse.notify.deal_digest import build_deal_digest


def _dto(
    date: str, price: int, floor: int, name: str, area: float, cancelled: bool = False
) -> DealDTO:
    return DealDTO(
        deal_key=f"{date}-{price}-{floor}",
        complex_no="947",
        trade_type=TradeType.SALE,
        deal_date=date,
        price_deal=price,
        floor=floor,
        pyeong_no="3",
        pyeong_name=name,
        area_excl=area,
        cancelled=cancelled,
    )


def _result() -> DealRunResult:
    cr = ComplexDealResult(
        complex_no="947",
        label="방배 삼호1차",
        name="삼호1차",
        address="서울시 서초구 방배동",
        new_deals=[_dto("2026-05-23", 225000, 10, "82A", 81.39)],
        cancelled_deals=[_dto("2024-12-04", 170000, 10, "82A", 81.39, cancelled=True)],
    )
    return DealRunResult(
        run_id=5,
        started_at=now_kst(),
        status=RunStatus.SUCCESS,
        complexes=[cr],
        targets_count=1,
        new_count=1,
        cancelled_count=1,
        starred_complexes={"947"},
    )


def test_deal_digest_sections_and_link():
    msg = build_deal_digest(_result(), "http://localhost:8765")
    assert "실거래가 업데이트" in msg
    assert "신규 1 · 취소 1" in msg
    assert "삼호1차" in msg
    assert "🆕 신규 실거래" in msg and "❌ 거래취소" in msg
    assert "82A" in msg
    assert "★" in msg  # 별표 단지 강조
    assert "26.05.23" in msg  # 날짜 포맷
    assert 'href="http://localhost:8765/deals"' in msg


def test_deal_digest_no_change():
    rr = DealRunResult(run_id=6, started_at=now_kst(), status=RunStatus.SUCCESS)
    msg = build_deal_digest(rr, "http://localhost:8765")
    assert "새 실거래 없음" in msg
