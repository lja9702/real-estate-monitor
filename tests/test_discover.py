"""주간 신규편입 단지 탐색 — 마커 파싱·밴드판정·발견 로직·다이제스트 테스트.

네트워크는 가짜 클라이언트(fetch_markers)로 대체한다. run_discovery 에 client 를 주입하면
브라우저를 열지 않으므로 단위 테스트가 가능하다.
"""

from __future__ import annotations

import pytest

from myhouse.core.discover import run_discovery
from myhouse.db import repo
from myhouse.db.engine import get_session
from myhouse.naver import regions
from myhouse.naver.regions import DiscoveredComplex
from myhouse.notify.discover_digest import build_discover_digest
from myhouse.settings import (
    AppConfig,
    Config,
    DiscoverConfig,
    RegionSpec,
    Settings,
    TargetSpec,
)


# ── 마커 파싱 ────────────────────────────────────────────────────────────────
def test_parse_marker_extracts_price_and_area():
    raw = {
        "markerId": "374",
        "markerType": "COMPLEX",
        "complexName": "극동",
        "latitude": 37.49,
        "longitude": 126.97,
        "realEstateTypeCode": "APT",
        "realEstateTypeName": "아파트",
        "totalHouseholdCount": 1550,
        "minArea": "67.01",
        "maxArea": "130.65",
        "minDealPrice": 153000,
        "maxDealPrice": 200000,
        "medianDealPrice": 165000,
        "dealCount": 45,
    }
    dc = regions.parse_marker(raw)
    assert dc is not None
    assert dc.complex_no == "374"
    assert dc.min_deal_price == 153000
    assert dc.max_deal_price == 200000
    assert dc.median_deal_price == 165000
    assert dc.min_area == 67.01
    assert dc.max_area == 130.65
    assert dc.total_households == 1550
    assert dc.real_estate_type_name == "아파트"


def test_parse_marker_without_deals_has_no_price():
    raw = {"markerId": "1", "markerType": "COMPLEX", "complexName": "거래없음",
           "totalHouseholdCount": 10, "minArea": "17", "maxArea": "20"}
    dc = regions.parse_marker(raw)
    assert dc is not None and dc.min_deal_price is None


def test_in_price_band_overlap():
    def mk(lo, hi):
        return DiscoveredComplex("1", "x", None, None, None, "APT",
                                 min_deal_price=lo, max_deal_price=hi)
    assert regions.in_price_band(mk(160000, 200000), 150000, 260000)  # 완전 포함
    assert regions.in_price_band(mk(140000, 160000), 150000, 260000)  # 하단 겹침
    assert regions.in_price_band(mk(250000, 300000), 150000, 260000)  # 상단 겹침
    assert not regions.in_price_band(mk(100000, 140000), 150000, 260000)  # 밴드 아래
    assert not regions.in_price_band(mk(270000, 300000), 150000, 260000)  # 밴드 위
    assert not regions.in_price_band(mk(None, None), 150000, 260000)  # 가격 없음


# ── 발견 로직 ────────────────────────────────────────────────────────────────
def _mk(no: str, *, name: str = "단지", region: str = "A",
        price=(160000, 200000), hh: int = 400, area=(70.0, 110.0)) -> DiscoveredComplex:
    return DiscoveredComplex(
        complex_no=no, name=name, total_households=hh, lat=None, lon=None,
        real_estate_type="APT", deal_count=10, real_estate_type_name="아파트",
        min_deal_price=price[0], max_deal_price=price[1], median_deal_price=price[0],
        min_area=area[0], max_area=area[1], region=region,
    )


class FakeClient:
    """run_discovery 에 주입할 가짜 클라이언트 — 지역별 마커 리스트를 그대로 돌려준다."""

    def __init__(self, by_region: dict[str, list[DiscoveredComplex]]):
        self.by_region = by_region

    def fetch_markers(self, region, disc, *, seed_complex_no):  # noqa: ANN001, ARG002
        return list(self.by_region.get(region.name, []))


def _cfg(tmp_path, *, targets=None) -> Config:
    return Config(
        app=AppConfig(db_path=str(tmp_path / "test.db")),
        discover=DiscoverConfig(
            enabled=True,
            seed_complex_no="947",
            regions=[RegionSpec(name="A", cortar_no="1", bbox=[1.0, 2.0, 3.0, 0.0])],
        ),
        targets=targets or [],
    )


def test_first_run_is_baseline_no_alerts(tmp_path, engine):
    cfg = _cfg(tmp_path)
    fake = FakeClient({"A": [_mk("100"), _mk("200")]})
    sent: list = []
    res = run_discovery(cfg, Settings(), engine, client=fake, notify=sent.append)

    assert res.first_run is True
    assert res.total_found == 2
    assert res.new_candidates == []  # baseline 은 알리지 않음
    assert sent == []  # notify 미호출
    with get_session(engine) as s:
        assert repo.count_discover_candidates(s) == 2
        row = repo.get_discover_candidate(s, "100")
        assert row.notified is True and row.price_min == 160000 and row.households == 400


def test_second_run_alerts_only_new(tmp_path, engine):
    cfg = _cfg(tmp_path)
    # 1회차(baseline): 100, 200
    run_discovery(cfg, Settings(), engine, client=FakeClient({"A": [_mk("100"), _mk("200")]}))
    # 2회차: 300 신규 편입
    sent: list = []
    res = run_discovery(
        cfg, Settings(), engine,
        client=FakeClient({"A": [_mk("100"), _mk("200"), _mk("300", name="신규래미안")]}),
        notify=sent.append,
    )
    assert res.first_run is False
    assert [dc.complex_no for dc in res.new_candidates] == ["300"]
    assert len(sent) == 1 and sent[0].new_candidates[0].name == "신규래미안"

    # 3회차: 변화 없음 → 300 재알림 안 함
    res3 = run_discovery(
        cfg, Settings(), engine,
        client=FakeClient({"A": [_mk("100"), _mk("200"), _mk("300")]}),
        notify=sent.append,
    )
    assert res3.new_candidates == []
    assert len(sent) == 1  # 추가 전송 없음


def test_tracked_complex_not_alerted(tmp_path, engine):
    # 400 은 config 고정 타겟(추적 중) → 마커에 새로 떠도 알림 대상 아님
    cfg = _cfg(tmp_path, targets=[TargetSpec(kind="complex", complex_no="400")])
    run_discovery(cfg, Settings(), engine, client=FakeClient({"A": [_mk("100")]}))  # baseline
    res = run_discovery(
        cfg, Settings(), engine,
        client=FakeClient({"A": [_mk("100"), _mk("400", name="이미추적")]}),
    )
    assert [dc.complex_no for dc in res.new_candidates] == []
    with get_session(engine) as s:
        row = repo.get_discover_candidate(s, "400")
        assert row.tracked_at_discovery is True and row.notified is True


def test_active_db_complex_not_alerted(tmp_path, engine):
    cfg = _cfg(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(s, "500", name="텔레추가", source="telegram", is_active=True)
    run_discovery(cfg, Settings(), engine, client=FakeClient({"A": [_mk("100")]}))  # baseline
    res = run_discovery(
        cfg, Settings(), engine, client=FakeClient({"A": [_mk("100"), _mk("500")]})
    )
    assert [dc.complex_no for dc in res.new_candidates] == []


def test_dedup_across_regions(tmp_path, engine):
    cfg = Config(
        app=AppConfig(db_path=str(tmp_path / "test.db")),
        discover=DiscoverConfig(
            enabled=True, seed_complex_no="947",
            regions=[
                RegionSpec(name="A", cortar_no="1", bbox=[1.0, 2.0, 3.0, 0.0]),
                RegionSpec(name="B", cortar_no="2", bbox=[2.0, 3.0, 3.0, 0.0]),
            ],
        ),
    )
    # 같은 단지 999 가 두 지역 bbox 에 겹쳐 나타나도 1개로 집계
    fake = FakeClient({"A": [_mk("999", region="A")], "B": [_mk("999", region="B"), _mk("888", region="B")]})
    res = run_discovery(cfg, Settings(), engine, client=fake)
    assert res.total_found == 2  # 999, 888


# ── 다이제스트 ───────────────────────────────────────────────────────────────
def test_digest_groups_and_shows_add_command(tmp_path, engine):
    cfg = _cfg(tmp_path)
    run_discovery(cfg, Settings(), engine, client=FakeClient({"A": [_mk("100")]}))  # baseline
    res = run_discovery(
        cfg, Settings(), engine,
        client=FakeClient({"A": [
            _mk("100"),
            _mk("700", name="강남자이", region="강남구", price=(180000, 240000), hh=920),
        ]}),
    )
    msg = build_discover_digest(res, "http://localhost:8765")
    assert "신규 편입 단지" in msg
    assert "강남자이" in msg
    assert "/add 700" in msg  # 바로 추가할 수 있게 명령 노출
    assert "18억" in msg  # 가격 표기


def test_digest_empty_when_no_new():
    from datetime import datetime

    from myhouse.constants import KST, RunStatus
    from myhouse.core.discover import DiscoverResult

    res = DiscoverResult(
        run_id=1, started_at=datetime(2026, 6, 22, 9, 0, tzinfo=KST),
        status=RunStatus.SUCCESS, new_candidates=[], total_found=5, first_run=False,
    )
    msg = build_discover_digest(res, "http://localhost:8765")
    assert "새로 편입된 단지가 없습니다" in msg


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
