"""dedup 단위 테스트 — cluster_key 그룹핑, 가격 범위."""

from __future__ import annotations

from tests.conftest import make_dto

from myhouse.core.dedup import group_by_cluster, price_range


def test_group_by_cluster_merges_same_unit():
    # 같은 유닛(면적/층/향/거래유형), 다른 중개사·가격
    a = make_dto("1", price_deal=158000)
    b = make_dto("2", price_deal=159000)
    # 다른 유닛
    c = make_dto("3", floor_num=5, price_deal=210000)
    groups = group_by_cluster([a, b, c], key=lambda d: d.cluster_key)
    assert a.cluster_key == b.cluster_key
    assert len(groups[a.cluster_key]) == 2
    assert len(groups[c.cluster_key]) == 1


def test_price_range():
    assert price_range([158000, 159000, None]) == (158000, 159000)
    assert price_range([None, None]) == (None, None)
    assert price_range([]) == (None, None)
