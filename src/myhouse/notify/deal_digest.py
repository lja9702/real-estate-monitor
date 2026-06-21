"""DealRunResult → 텔레그램 실거래 다이제스트(HTML).

단지별로 🆕신규 실거래 / ❌거래취소 섹션으로 나눈다. 신규는 거래일 최신순.
별표(★) 단지는 강조한다. (매물 다이제스트와 별개 메시지.)
"""

from __future__ import annotations

from html import escape

from ..constants import TRADE_TYPE_KO
from ..core.deal_collector import ComplexDealResult, DealRunResult
from ..naver.deal_parser import DealDTO
from ..util import format_manwon
from .bands import format_band, in_band


def _d(iso: str) -> str:
    """'2026-05-23' → '26.05.23'."""
    if len(iso) >= 10 and iso[4] == "-":
        return f"{iso[2:4]}.{iso[5:7]}.{iso[8:10]}"
    return iso


def _pyeong(dto: DealDTO) -> str:
    """'82A(81㎡)' / '82A' / '81㎡' 중 가능한 형태."""
    name = escape(dto.pyeong_name) if dto.pyeong_name else ""
    area = f"{dto.area_excl:g}㎡" if dto.area_excl else ""
    if name and area:
        return f"{name}({area})"
    return name or area


def _floor(dto: DealDTO) -> str:
    return f"{dto.floor}층" if dto.floor is not None else ""


def _deal_line(dto: DealDTO) -> str:
    trade_ko = TRADE_TYPE_KO[dto.trade_type]
    price = format_manwon(dto.price_deal)
    if dto.price_rent:
        price += f"/{format_manwon(dto.price_rent)}"
    bits = [f"{trade_ko} {price}"]
    py = _pyeong(dto)
    if py:
        bits.append(py)
    fl = _floor(dto)
    if fl:
        bits.append(fl)
    bits.append(_d(dto.deal_date))
    return "• " + " · ".join(bits)


def _cancel_line(dto: DealDTO) -> str:
    trade_ko = TRADE_TYPE_KO[dto.trade_type]
    py = _pyeong(dto)
    spec = " · ".join(filter(None, [py, _floor(dto), _d(dto.deal_date)]))
    return f"• {trade_ko} {format_manwon(dto.price_deal)} ({spec}) 취소"


def _complex_block(
    cr: ComplexDealResult, starred: set[str], lo: int | None, hi: int | None
) -> tuple[list[str], int, int]:
    """(라인, 신규수, 취소수) — 가격밴드 밖 실거래는 제외."""
    new = [d for d in cr.new_deals if in_band(d.price_deal, lo, hi)]
    cancelled = [d for d in cr.cancelled_deals if in_band(d.price_deal, lo, hi)]
    if not (new or cancelled):
        return ([], 0, 0)  # 수집오류·밴드밖은 무음(헤더 소음 줄임)

    star = "★ " if cr.complex_no in starred else ""
    header = star + escape(cr.name or cr.label)
    if cr.address:
        header += f"  <i>{escape(cr.address)}</i>"
    lines = [f"━━ {header} ━━"]

    if new:
        lines.append("🆕 신규 실거래")
        for dto in sorted(new, key=lambda d: d.deal_date, reverse=True):
            lines.append(_deal_line(dto))
    if cancelled:
        lines.append("❌ 거래취소")
        for dto in sorted(cancelled, key=lambda d: d.deal_date, reverse=True):
            lines.append(_cancel_line(dto))
    lines.append("")
    return (lines, len(new), len(cancelled))


def build_deal_digest(
    result: DealRunResult,
    dashboard_url: str,
    *,
    price_min: int | None = None,
    price_max: int | None = None,
    only_complexes: set[str] | None = None,
    drop_empty: bool = False,
) -> str | None:
    """DealRunResult → HTML 메시지 문자열.

    price_min/max: 구독자 가격밴드(만원, None=무제한). only_complexes: 받을 단지번호 집합
    (None=전체=운영자). drop_empty=True 면 밴드 안에 보여줄 실거래가 없을 때 None 반환.
    """
    body: list[str] = []
    n_new = n_cancel = 0
    for cr in result.complexes:
        if only_complexes is not None and cr.complex_no not in only_complexes:
            continue
        lines, a, b = _complex_block(cr, result.starred_complexes, price_min, price_max)
        body.extend(lines)
        n_new += a
        n_cancel += b

    ts = result.started_at.strftime("%Y-%m-%d %H:%M")
    head = f"🏛 <b>실거래가 업데이트</b> — {ts} KST\n신규 {n_new} · 취소 {n_cancel}"
    band_label = format_band(price_min, price_max)
    if band_label:
        head += f" · 🎯 {band_label}"
    if (price_min is None and price_max is None) and result.errors:
        head += f"  ⚠수집오류 {result.errors}"

    if not body:
        if drop_empty:
            return None
        return head + "\n\n새 실거래 없음."

    deals_url = dashboard_url.rstrip("/") + "/deals"
    footer = f'📊 <a href="{escape(deals_url, quote=True)}">실거래가 대시보드 열기</a>'
    return head + "\n\n" + "\n".join(body).rstrip() + "\n\n" + footer
