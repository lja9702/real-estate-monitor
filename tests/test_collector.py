"""collector 엔드투엔드 — FakeClient + 시간여행으로 NEW→가격변동→PENDING→REMOVED 검증."""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import select
from tests.conftest import make_dto

import myhouse.core.collector as collector_mod
from myhouse.constants import ListingStatus, RunStatus, TradeType, now_kst
from myhouse.core.collector import run_collection
from myhouse.db import repo
from myhouse.db.engine import get_session
from myhouse.db.models import ListingHistory
from myhouse.naver.client import FetchResult
from myhouse.settings import AppConfig, Config, FilterSpec, Settings, TargetSpec


class FakeClient:
    def __init__(self, fetch_results: list[FetchResult]):
        self._q = list(fetch_results)

    def fetch_articles(self, complex_row, filt) -> FetchResult:
        return self._q.pop(0)

    def fetch_complex_meta(self, complex_no: str):
        return None

    def fetch_complex_address(self, complex_no: str, article_no: str) -> str | None:
        return None

    def fetch_complex_coords(self, complex_no: str) -> tuple[float, float] | None:
        return None

    def close(self) -> None:
        pass


def _config(tmp_path) -> Config:
    return Config(
        app=AppConfig(
            db_path=str(tmp_path / "test.db"),
            removal_debounce_hours=20,
            request_delay_seconds=(0.0, 0.0),
        ),
        defaults=FilterSpec(trade_types=[TradeType.SALE]),
        targets=[
            TargetSpec(kind="complex", complex_no="111", label="테스트단지", lat=37.0, lon=127.0)
        ],
    )


def test_full_lifecycle(tmp_path, engine, monkeypatch):
    cfg = _config(tmp_path)
    settings = Settings()
    base = now_kst()
    clock = {"now": base}
    monkeypatch.setattr(collector_mod, "now_kst", lambda: clock["now"])

    def run(now, fetch_result) -> object:
        clock["now"] = now
        return run_collection(
            cfg, settings, engine, trigger="manual", client=FakeClient([fetch_result])
        )

    # run1: 신규 등장
    r1 = run(
        base, FetchResult("111", [make_dto("1", price_deal=158000)], complete=True, raw_count=1)
    )
    assert r1.new_count == 1 and r1.status == RunStatus.SUCCESS
    with get_session(engine) as s:
        lst = repo.get_listing(s, "1")
        assert lst is not None and lst.status == ListingStatus.ACTIVE
        assert lst.price_deal == 158000 and lst.first_seen_run_id == r1.run_id

    # run2: 가격 변동
    r2 = run(
        base + timedelta(hours=12),
        FetchResult("111", [make_dto("1", price_deal=152000)], complete=True, raw_count=1),
    )
    assert r2.price_changed_count == 1
    with get_session(engine) as s:
        assert repo.get_listing(s, "1").price_deal == 152000

    # run3: 미노출 1회 → PENDING (아직 거래완료 아님)
    r3 = run(base + timedelta(hours=24), FetchResult("111", [], complete=True, raw_count=0))
    assert r3.removed_count == 0
    with get_session(engine) as s:
        assert repo.get_listing(s, "1").status == ListingStatus.PENDING_REMOVAL

    # run4: 디바운스 경과 후 미노출 → REMOVED
    r4 = run(base + timedelta(hours=50), FetchResult("111", [], complete=True, raw_count=0))
    assert r4.removed_count == 1
    with get_session(engine) as s:
        assert repo.get_listing(s, "1").status == ListingStatus.REMOVED
        events = [
            h.event_type.value
            for h in s.exec(select(ListingHistory).where(ListingHistory.article_no == "1"))
        ]
        assert "NEW" in events and "PRICE_CHANGED" in events and "REMOVED" in events


def test_incomplete_fetch_does_not_remove(tmp_path, engine, monkeypatch):
    """수집 불완전이면 사라진 매물을 거래완료 처리하지 않는다."""
    cfg = _config(tmp_path)
    settings = Settings()
    base = now_kst()
    clock = {"now": base}
    monkeypatch.setattr(collector_mod, "now_kst", lambda: clock["now"])

    # 등장
    clock["now"] = base
    run_collection(
        cfg,
        settings,
        engine,
        trigger="manual",
        client=FakeClient([FetchResult("111", [make_dto("1")], complete=True, raw_count=1)]),
    )
    # 오랜 시간 뒤, 빈 결과지만 수집 불완전(complete=False)
    clock["now"] = base + timedelta(hours=99)
    r = run_collection(
        cfg,
        settings,
        engine,
        trigger="manual",
        client=FakeClient([FetchResult("111", [], complete=False, raw_count=0)]),
    )
    assert r.removed_count == 0
    assert r.status == RunStatus.PARTIAL  # http_errors 로 집계
    with get_session(engine) as s:
        # 여전히 ACTIVE (PENDING 도 아님 — 안전 규칙)
        assert repo.get_listing(s, "1").status == ListingStatus.ACTIVE
