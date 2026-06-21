"""PermitRunResult → 텔레그램 토지거래허가 다이제스트(HTML).

단지별로 🏛 신규 허가를 허가일 최신순으로 나열한다. 가격·면적이 없는 데이터원이라
허가일·지번·이용목적만 보여준다(가격은 실거래 다이제스트에서). 별표(★) 단지는 강조.
"""

from __future__ import annotations

from html import escape

from ..core.permit_collector import ComplexPermitResult, PermitRunResult
from ..seoul.permit_parser import PermitDTO


def _d(iso: str | None) -> str:
    """'2026-06-19' → '26.06.19'."""
    if iso and len(iso) >= 10 and iso[4] == "-":
        return f"{iso[2:4]}.{iso[5:7]}.{iso[8:10]}"
    return iso or "-"


def _permit_line(dto: PermitDTO) -> str:
    jibun = dto.address.split()[-1] if dto.address else ""  # "강남구 청담동 127-31" → "127-31"
    bits = [_d(dto.permit_date)]
    if jibun:
        bits.append(escape(jibun))
    if dto.use_purp:
        bits.append(escape(dto.use_purp))
    return "• 허가 " + " · ".join(bits)


def _complex_block(cr: ComplexPermitResult, starred: set[str]) -> list[str]:
    if not cr.new_permits:
        return []
    star = "★ " if cr.complex_no in starred else ""
    header = star + escape(cr.name or cr.label)
    if cr.address:
        header += f"  <i>{escape(cr.address)}</i>"
    lines = [f"━━ {header} ━━", f"🏛 신규 허가 {len(cr.new_permits)}건"]
    for dto in sorted(cr.new_permits, key=lambda d: d.permit_date or "", reverse=True):
        lines.append(_permit_line(dto))
    lines.append("")
    return lines


def build_permit_digest(result: PermitRunResult, dashboard_url: str) -> str:
    """PermitRunResult → HTML 메시지 문자열."""
    ts = result.started_at.strftime("%Y-%m-%d %H:%M")
    matched = sum(1 for cr in result.complexes if cr.new_permits)
    head = (
        f"🏛 <b>토지거래허가</b> — {ts} KST\n"
        f"신규 허가 {result.new_count}건 · 단지 {matched}곳"
    )
    if result.missing_jibun:
        head += f"  ⚠지번미보유 {result.missing_jibun}"
    if result.errors:
        head += f"  ⚠수집오류 {result.errors}"

    body: list[str] = []
    for cr in result.complexes:
        body.extend(_complex_block(cr, result.starred_complexes))

    if not body:
        return head + "\n\n새 허가 없음."

    permits_url = dashboard_url.rstrip("/") + "/permits"
    footer = (
        f'📊 <a href="{escape(permits_url, quote=True)}">토지거래허가 대시보드 열기</a>\n'
        f"<i>※ 허가는 거래 성사 전 단계 신호 — 가격은 실거래로 확인하세요.</i>"
    )
    return head + "\n\n" + "\n".join(body).rstrip() + "\n\n" + footer
