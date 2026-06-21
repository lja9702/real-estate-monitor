"""다중 중개사 중복 처리 — cluster_key 로 같은 유닛을 묶는다.

diff/수명주기는 article_no 단위(진실)지만, 알림·대시보드 표시는 cluster_key 로 그룹핑해
"중개 N곳, 최저~최고가" 로 보여줘 중개사 churn 스팸을 줄인다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def group_by_cluster(items: list[T], key: Callable[[T], str]) -> dict[str, list[T]]:
    """key(item) → cluster_key 로 그룹핑. 입력 순서를 보존한다."""
    out: dict[str, list[T]] = defaultdict(list)
    for it in items:
        out[key(it)].append(it)
    return dict(out)


def price_range(prices: list[int | None]) -> tuple[int | None, int | None]:
    """None 을 제외한 (최저가, 최고가). 비어 있으면 (None, None)."""
    vals = [p for p in prices if p is not None]
    if not vals:
        return None, None
    return min(vals), max(vals)
