"""DiscoverResult → 텔레그램 신규편입 단지 다이제스트(HTML).

지역별로 묶어 신규 편입 단지를 나열한다. 각 줄은 가격범위·세대수·면적범위와 /add 명령을 담아
사용자가 바로 추적 추가할 수 있게 한다(추가는 사용자 몫 — 이 알림은 후보 제시까지).
"""

from __future__ import annotations

from html import escape

from ..core.discover import DiscoverResult
from ..naver.regions import DiscoveredComplex
from ..util import format_manwon
from .bands import band_overlaps, format_band


def _price(dc: DiscoveredComplex) -> str:
    lo, hi = dc.min_deal_price, dc.max_deal_price
    if lo is None and hi is None:
        return "-"
    if lo == hi:
        return format_manwon(lo)
    return f"{format_manwon(lo)}~{format_manwon(hi)}"


def _area(dc: DiscoveredComplex) -> str:
    lo, hi = dc.min_area, dc.max_area
    if not lo and not hi:
        return ""
    if lo == hi:
        return f"{lo:g}㎡"
    return f"{lo:g}~{hi:g}㎡"


def _line(dc: DiscoveredComplex) -> str:
    bits = [_price(dc)]
    if dc.total_households:
        bits.append(f"{dc.total_households:,}세대")
    area = _area(dc)
    if area:
        bits.append(area)
    if dc.real_estate_type_name:
        bits.append(escape(dc.real_estate_type_name))
    spec = " · ".join(bits)
    name = escape(dc.name or dc.complex_no)
    return f"• <b>{name}</b>  {spec}\n  <code>/add {escape(dc.complex_no)}</code>"


def build_discover_digest(
    result: DiscoverResult,
    dashboard_url: str,
    *,
    price_min: int | None = None,
    price_max: int | None = None,
    drop_empty: bool = False,
) -> str | None:
    """DiscoverResult → HTML 메시지. 신규 0건이면 간단 요약만.

    price_min/max: 구독자 가격밴드(만원, None=무제한). 단지 호가범위가 밴드와 겹치는 것만
    보여준다. drop_empty=True 면 밴드 안 신규가 없을 때 None 반환(개인화 발송 시 건너뛰기).
    """
    ts = result.started_at.strftime("%Y-%m-%d %H:%M")
    cands = [
        dc
        for dc in result.new_candidates
        if band_overlaps(dc.min_deal_price, dc.max_deal_price, price_min, price_max)
    ]
    n = len(cands)
    head = f"🔭 <b>신규 편입 단지</b> — {ts} KST\n조건에 새로 든 단지 <b>{n}</b>개"
    band_label = format_band(price_min, price_max)
    if band_label:
        head += f" · 🎯 {band_label}"
    if (price_min is None and price_max is None) and result.errors:
        head += f"  ⚠수집오류 {result.errors}개 지역"

    if not cands:
        if drop_empty:
            return None
        return head + "\n\n새로 편입된 단지가 없습니다."

    # 지역별 그룹핑 → 지역명 정렬, 지역 내 가격(min) 오름차순
    by_region: dict[str, list[DiscoveredComplex]] = {}
    for dc in cands:
        by_region.setdefault(dc.region or "기타", []).append(dc)

    body: list[str] = []
    for region in sorted(by_region):
        body.append(f"━━ {escape(region)} ━━")
        for dc in sorted(by_region[region], key=lambda d: (d.min_deal_price or 0)):
            body.append(_line(dc))
        body.append("")

    footer = "추가하려면 <code>/add 단지번호 [별칭]</code> 를 보내세요. 관심 없으면 무시하면 됩니다."
    return head + "\n\n" + "\n".join(body).rstrip() + "\n\n" + footer
