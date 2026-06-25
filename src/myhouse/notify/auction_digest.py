"""AuctionRunResult → 텔레그램 법원경매 다이제스트(HTML).

단지별로 🔨 신규/최저가하락/기일변경 물건을 매각기일 순으로 나열한다. 각 물건에 옥션원
검색 딥링크 + 사건번호를 붙인다(상세·사진·권리분석은 옥션원에서 확인). 별표(★) 단지는 강조.
"""

from __future__ import annotations

from html import escape

from ..core.auction_collector import AuctionRunResult, ComplexAuctionResult
from ..core.auction_diff import (
    DATE_CHANGED,
    FAILED,
    NEW,
    PRICE_DOWN,
    SOLD,
    WITHDRAWN,
    AuctionOp,
)
from ..court.auction1_link import court_case_search_url

_TAG = {
    NEW: "🆕", PRICE_DOWN: "🔻", DATE_CHANGED: "📅",
    SOLD: "🔨", FAILED: "🔁", WITHDRAWN: "🚫",
}


def _d(iso: str | None) -> str:
    """'2026-06-25' → '26.06.25'."""
    if iso and len(iso) >= 10 and iso[4] == "-":
        return f"{iso[2:4]}.{iso[5:7]}.{iso[8:10]}"
    return iso or "-"


def _money(manwon: int | None) -> str:
    """만원 정수 → '28억' / '1.94억' / '8000만'."""
    if manwon is None:
        return "?"
    if manwon >= 10000:
        return f"{manwon / 10000:g}억"
    return f"{manwon}만"


def _fail_label(n: int) -> str:
    return "신건" if n <= 0 else f"{n}회유찰"


def _outcome_line(op: AuctionOp) -> str:
    """정합 결과(매각/유찰/취하) op 한 줄."""
    dto = op.dto
    bits: list[str] = [f"<code>{escape(dto.case_no)}</code>"]
    area = dto.area_max or dto.area_min
    if area:
        bits.append(f"전용{int(area)}㎡")
    if op.kind == SOLD:
        bits.append(f"낙찰 {_money(op.final_bid_manwon)}")
        if op.final_bid_manwon and dto.appraisal_manwon:
            bits.append(f"감정 {_money(dto.appraisal_manwon)}({round(op.final_bid_manwon / dto.appraisal_manwon * 100)}%)")
    elif op.kind == FAILED:
        label = op.outcome_label or "유찰"
        if op.next_sale_date:
            bits.append(f"{label} → 다음 매각 {_d(op.next_sale_date)}")
            bits.append(f"최저 {_money(op.old_min_bid_manwon)}→{_money(dto.min_bid_manwon)}({dto.min_bid_ratio}%)")
        else:
            bits.append(label)
        bits.append(_fail_label(dto.fail_count))
    else:  # WITHDRAWN
        bits.append(op.outcome_label or "취하")
    return f"{_TAG.get(op.kind, '•')} " + " · ".join(bits)


def _op_line(op: AuctionOp) -> str:
    if op.kind in (SOLD, FAILED, WITHDRAWN):
        return _outcome_line(op)
    dto = op.dto
    bits: list[str] = [f"<code>{escape(dto.case_no)}</code>"]  # 사건번호 — 탭하면 복사
    area = dto.area_max or dto.area_min
    if area:
        bits.append(f"전용{int(area)}㎡")

    if op.kind == PRICE_DOWN:
        old = _money(op.old_min_bid_manwon)
        bits.append(f"최저 {old}→{_money(dto.min_bid_manwon)}({dto.min_bid_ratio}%)")
    elif op.kind == DATE_CHANGED:
        bits.append(f"기일 {_d(op.old_sale_date)}→{_d(dto.sale_date)}")
    else:  # NEW
        bits.append(f"감정 {_money(dto.appraisal_manwon)}")
        bits.append(f"최저 {_money(dto.min_bid_manwon)}({dto.min_bid_ratio}%)")

    if op.kind != DATE_CHANGED:
        bits.append(f"매각 {_d(dto.sale_date)}")
    bits.append(_fail_label(dto.fail_count))
    line = f"{_TAG.get(op.kind, '•')} " + " · ".join(bits)
    if op.kind == NEW and dto.flags:  # ⚠ 지분매각·위반건축물 등 위험 플래그
        line += "\n   ⚠️ " + " · ".join(escape(f) for f in dto.flags)
    return line


def _complex_block(cr: ComplexAuctionResult, starred: set[str]) -> list[str]:
    if not cr.ops:
        return []
    star = "★ " if cr.complex_no in starred else ""
    header = star + escape(cr.name or cr.label)
    if cr.address:
        header += f"  <i>{escape(cr.address)}</i>"
    lines = [f"━━ {header} ━━", f"🔨 경매 변동 {len(cr.ops)}건"]
    for op in sorted(cr.ops, key=lambda o: o.dto.sale_date or ""):
        lines.append(_op_line(op))
    ct = escape(court_case_search_url(), quote=True)
    lines.append(f'   📄 <a href="{ct}">법원경매에서 사건 검색</a>')
    lines.append("")
    return lines


def build_auction_digest(result: AuctionRunResult, dashboard_url: str) -> str:
    """AuctionRunResult → HTML 메시지 문자열."""
    ts = result.started_at.strftime("%Y-%m-%d %H:%M")
    matched = sum(1 for cr in result.complexes if cr.ops)
    head = (
        f"🔨 <b>법원경매</b> — {ts} KST\n"
        f"신규 {result.new_count} · 최저가하락 {result.price_down_count}"
    )
    if result.date_changed_count:
        head += f" · 기일변경 {result.date_changed_count}"
    if result.sold_count:
        head += f" · 매각 {result.sold_count}"
    if result.failed_count:
        head += f" · 유찰 {result.failed_count}"
    if result.withdrawn_count:
        head += f" · 취하 {result.withdrawn_count}"
    head += f" · 단지 {matched}곳"
    if result.missing_jibun:
        head += f"  ⚠지번미보유 {result.missing_jibun}"
    if result.unmatched_court:
        head += f"  ⚠관할미상 {result.unmatched_court}"
    if result.errors:
        head += f"  ⚠수집오류 {result.errors}"

    body: list[str] = []
    for cr in result.complexes:
        body.extend(_complex_block(cr, result.starred_complexes))

    if not body:
        return head + "\n\n새 경매 변동 없음."

    auctions_url = dashboard_url.rstrip("/") + "/auctions"
    footer = (
        f'📊 <a href="{escape(auctions_url, quote=True)}">법원경매 대시보드 열기</a>\n'
        f"<i>※ 상세·사진·권리분석은 법원경매정보(courtauction)에서 확인하세요.</i>"
    )
    return head + "\n\n" + "\n".join(body).rstrip() + "\n\n" + footer
