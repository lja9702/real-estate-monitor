"""급매 탐지 (순수 함수 — DB/네트워크 무의존).

급매 = 같은 단지·평수·거래유형의 *직전* 활성 매물 최저 호가(하한가)보다 일정 비율 이상
낮은 매물이 발생한 것. 신규 매물뿐 아니라 기존 매물의 가격인하로 하한을 깬 경우도 잡는다.

핵심 규칙: 하한가는 반드시 *수집 전* 스냅샷(existing)에서 계산한다. 같은 회차에 같은 평형
급매가 여러 건 와도 모두 '회차 이전 하한가' 기준으로 각각 판정되어야 하기 때문이다(먼저
적용된 급매가 하한을 끌어내려 뒤의 급매를 가리는 일 방지). 그래서 collector 는 _apply_ops
*전에* 이 함수를 호출한다.

평형 매칭은 전용면적 버림 정수(util.area_match_key) — 매물·실거래와 같은 단일 기준.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..constants import ListingStatus, TradeType
from ..db.models import Listing
from ..util import area_match_key
from .diff import ComplexDiff


@dataclass
class FlashSignal:
    """급매 1건 — detect_flash_deals 의 산출물(collector 가 FlashDeal 로 적재)."""

    article_no: str
    complex_no: str
    cluster_key: str
    trade_type: TradeType
    area_excl: float | None
    area_key: int
    price_deal: int       # 급매 발생 당시 가격(만원)
    prior_floor: int      # 직전 같은 평수 하한가(만원) — 기준
    drop_amount: int      # prior_floor - price_deal (만원, 양수)
    drop_pct: float       # drop_amount / prior_floor * 100
    trigger: str          # "new"(신규) | "price_drop"(가격인하)


def _prior_floors(
    existing: list[Listing], trade_types: set[TradeType]
) -> dict[tuple[int, TradeType], int]:
    """수집 전 스냅샷에서 (평형키, 거래유형) → 최저 호가(만원). ACTIVE 매물만 센다."""
    floors: dict[tuple[int, TradeType], int] = {}
    for lst in existing:
        if lst.status != ListingStatus.ACTIVE:
            continue
        if lst.trade_type not in trade_types:
            continue
        if lst.price_deal is None or lst.area_excl is None:
            continue
        akey = area_match_key(lst.area_excl)
        if akey < 0:
            continue
        key = (akey, lst.trade_type)
        cur = floors.get(key)
        if cur is None or lst.price_deal < cur:
            floors[key] = lst.price_deal
    return floors


def detect_flash_deals(
    diff: ComplexDiff,
    existing: list[Listing],
    *,
    trade_types: set[TradeType],
    min_drop_pct: float,
    min_drop_manwon: int = 0,
    include_price_drops: bool = True,
) -> list[FlashSignal]:
    """한 단지의 급매 신호 목록. existing 은 *수집 전* 스냅샷이어야 한다(핵심 규칙).

    후보: diff.new(신규) + (include_price_drops 면) 가격이 내린 diff.price_changed.
    각 후보 가격이 같은 평형 하한가보다 min_drop_pct% 이상이고 min_drop_manwon 이상 낮으면 급매.
    """
    floors = _prior_floors(existing, trade_types)

    candidates: list[tuple] = []  # (ArticleDTO, trigger)
    for op in diff.new:
        if op.dto is not None:
            candidates.append((op.dto, "new"))
    if include_price_drops:
        for op in diff.price_changed:
            dto = op.dto
            if (
                dto is not None
                and op.old_price_deal is not None
                and dto.price_deal is not None
                and dto.price_deal < op.old_price_deal
            ):
                candidates.append((dto, "price_drop"))

    signals: list[FlashSignal] = []
    for dto, trigger in candidates:
        if dto.trade_type not in trade_types:
            continue
        if dto.price_deal is None or dto.area_excl is None:
            continue
        akey = area_match_key(dto.area_excl)
        if akey < 0:
            continue
        floor = floors.get((akey, dto.trade_type))
        if floor is None:
            continue  # 직전 같은 평수 매물 없음 → 하한 없음 → 급매 아님(이 매물이 하한을 새로 세움)
        drop = floor - dto.price_deal
        if drop <= 0:
            continue  # 하한 이상(동가 포함) → 급매 아님
        pct = drop / floor * 100
        if pct < min_drop_pct:
            continue
        if min_drop_manwon and drop < min_drop_manwon:
            continue
        signals.append(
            FlashSignal(
                article_no=dto.article_no,
                complex_no=dto.complex_no,
                cluster_key=dto.cluster_key,
                trade_type=dto.trade_type,
                area_excl=dto.area_excl,
                area_key=akey,
                price_deal=dto.price_deal,
                prior_floor=floor,
                drop_amount=drop,
                drop_pct=round(pct, 2),
                trigger=trigger,
            )
        )
    return signals
