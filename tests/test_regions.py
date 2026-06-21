"""지역 마커 파싱·필터 테스트 (new.land single-markers)."""

from __future__ import annotations

import json
import pathlib

from myhouse.naver import regions
from myhouse.settings import DiscoverSpec

FIX = pathlib.Path(__file__).parent / "fixtures"


def _markers():
    return json.loads((FIX / "single_markers.json").read_text(encoding="utf-8"))


def test_extract_and_parse_marker():
    items = regions.extract_markers(_markers())
    assert len(items) == 3
    dc = regions.parse_marker(items[0])
    assert dc.complex_no == "947"
    assert dc.name == "삼호1차"
    assert dc.total_households == 419
    assert dc.lat == 37.495335
    assert dc.real_estate_type == "JGC"
    assert dc.deal_count == 45


def test_passes_discover_household():
    items = [regions.parse_marker(m) for m in regions.extract_markers(_markers())]
    spec = DiscoverSpec(min_total_households=1000)
    kept = [d.name for d in items if regions.passes_discover(d, spec)]
    assert kept == ["극동"]  # 1550세대만 통과 (947=419, 470=481 탈락)


def test_passes_discover_name_exclude():
    items = [regions.parse_marker(m) for m in regions.extract_markers(_markers())]
    spec = DiscoverSpec(name_excludes=["삼호"])
    kept = [d.name for d in items if regions.passes_discover(d, spec)]
    assert kept == ["극동"]  # 삼호1차/삼호4차 제외
