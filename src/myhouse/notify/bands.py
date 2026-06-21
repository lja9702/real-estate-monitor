"""가격밴드 공통 헬퍼 — 구독자별 다이제스트 필터에 쓰는 순수 함수.

밴드는 (price_min, price_max) 만원 튜플. 각 끝이 None 이면 그 방향 무제한.
가격이 None(불명) 인 항목은 보수적으로 '포함'으로 본다 — 수집 단계 필터(_passes_filter)와
동일하게, 가격을 모른다는 이유로 떨궈서 놓치지 않게 한다.
"""

from __future__ import annotations

from ..util import format_manwon

EOK = 10000  # 1억 = 10,000만원


def in_band(price: int | None, lo: int | None, hi: int | None) -> bool:
    """단일 가격이 [lo, hi] 밴드 안인가. price=None 은 포함(보수적)."""
    if price is None:
        return True
    if lo is not None and price < lo:
        return False
    if hi is not None and price > hi:
        return False
    return True


def band_overlaps(
    val_lo: int | None, val_hi: int | None, lo: int | None, hi: int | None
) -> bool:
    """가격범위 [val_lo, val_hi] 가 밴드 [lo, hi] 와 겹치는가(단지 호가범위 판정용).

    범위 끝이 None 이면 그 방향 열림으로 본다. 둘 다 None 인 범위는 항상 겹침(포함).
    """
    if lo is not None and val_hi is not None and val_hi < lo:
        return False
    if hi is not None and val_lo is not None and val_lo > hi:
        return False
    return True


def is_unbounded(lo: int | None, hi: int | None) -> bool:
    return lo is None and hi is None


def format_band(lo: int | None, hi: int | None) -> str | None:
    """밴드를 사람이 읽는 라벨로. 무제한이면 None. 예: '7억~12억', '15억↑', '~12억'."""
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None:
        return f"{format_manwon(lo)}~{format_manwon(hi)}"
    if lo is not None:
        return f"{format_manwon(lo)}↑"
    return f"~{format_manwon(hi)}"
