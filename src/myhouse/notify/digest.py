"""RunResult → 텔레그램 다이제스트 메시지(HTML) 구성.

단지별로 그룹핑하고 🆕신규/📉가격변동/✅거래완료 섹션으로 나눈다. 신규는 cluster_key 로 묶어
중개사 churn(같은 유닛 다른 중개사) 을 한 줄로 접는다. 별표(★) 단지는 강조한다.
"""

from __future__ import annotations

from html import escape

from ..constants import TRADE_TYPE_KO
from ..core.collector import ComplexResult, RunResult
from ..core.dedup import group_by_cluster, price_range
from ..core.diff import DiffOp
from ..core.flash import FlashSignal
from ..naver.parser import ArticleDTO
from ..util import format_manwon, format_price
from .bands import format_band, in_band


def _floor(dto: ArticleDTO) -> str:
    if dto.floor_num is not None:
        return f"{dto.floor_num}층"
    return (dto.floor_info or "").split("/", 1)[0]


def _confirm(dto: ArticleDTO) -> str:
    if not dto.confirm_date:
        return ""
    # 'YYYY-MM-DD' → 'MM-DD'
    return dto.confirm_date[5:] if len(dto.confirm_date) >= 10 else dto.confirm_date


def _link(dto: ArticleDTO, text: str = "보기") -> str:
    if not dto.article_url:
        return ""
    return f'<a href="{escape(dto.article_url, quote=True)}">{escape(text)}</a>'


def _spec(dto: ArticleDTO) -> str:
    """면적·층·향 등 매물 스펙 한 줄."""
    bits: list[str] = []
    if dto.area_excl:
        bits.append(f"{dto.area_excl:g}㎡")
    fl = _floor(dto)
    if fl:
        bits.append(fl)
    if dto.direction:
        bits.append(escape(dto.direction))
    cfm = _confirm(dto)
    if cfm:
        bits.append(f"확인 {cfm}")
    return " · ".join(bits)


def _new_line(cluster_dtos: list[ArticleDTO], starred: bool) -> str:
    rep = cluster_dtos[0]
    trade_ko = TRADE_TYPE_KO[rep.trade_type]
    star = "★ " if starred else ""
    line = f"• {star}{trade_ko} {format_price(trade_ko, rep.price_deal, rep.price_rent)} · {_spec(rep)}"
    extra = ""
    if len(cluster_dtos) > 1:
        lo, hi = price_range([d.price_deal for d in cluster_dtos])
        rng = format_manwon(lo) if lo == hi else f"{format_manwon(lo)}~{format_manwon(hi)}"
        extra = f" · 중개 {len(cluster_dtos)}곳({rng})"
    return f"{line}  {_link(rep)}{extra}"


def _price_line(op: DiffOp, starred: bool) -> str:
    dto = op.dto
    assert dto is not None
    trade_ko = TRADE_TYPE_KO[dto.trade_type]
    star = "★ " if starred else ""
    old = format_price(trade_ko, op.old_price_deal, op.old_price_rent)
    new = format_price(trade_ko, dto.price_deal, dto.price_rent)
    delta = ""
    if op.old_price_deal is not None and dto.price_deal is not None:
        diff = dto.price_deal - op.old_price_deal
        if diff:
            arrow = "▼" if diff < 0 else "▲"
            delta = f" ({arrow}{format_manwon(abs(diff))})"
    return f"• {star}{old} → {new}{delta} · {_spec(dto)}  {_link(dto)}"


def _removed_line(op: DiffOp, starred: bool) -> str:
    star = "★ " if starred else ""
    price = format_manwon(op.old_price_deal)
    return f"• {star}{price} 매물 미노출 → 거래완료(추정)"


def _flash_line(sig: FlashSignal, dto: ArticleDTO | None, starred: bool) -> str:
    """🔥급매 한 줄 — 발생가 + 직전하한 + 하락폭. dto 가 있으면 면적/층/향·링크를 곁들인다."""
    trade_ko = TRADE_TYPE_KO[sig.trade_type]
    star = "★ " if starred else ""
    tag = "신규" if sig.trigger == "new" else "인하"
    drop = f"하한 {format_manwon(sig.prior_floor)} ▼{format_manwon(sig.drop_amount)}(-{sig.drop_pct:g}%)"
    line = f"• {star}🔥 {trade_ko} {format_manwon(sig.price_deal)}"
    spec = _spec(dto) if dto is not None else (f"{sig.area_excl:g}㎡" if sig.area_excl else "")
    if spec:
        line += f" · {spec}"
    line += f" · {drop} [{tag}]"
    link = _link(dto) if dto is not None else ""
    return f"{line}  {link}".rstrip()


def _complex_block(
    cr: ComplexResult,
    starred_complexes: set[str],
    price_min: int | None,
    price_max: int | None,
    *,
    include_errors: bool,
    show_flash: bool = True,
) -> tuple[list[str], int, int, int, int]:
    """(라인, 신규수, 가격변동수, 거래완료수, 급매수) — 가격밴드 밖 매물은 제외.

    카운트는 (헤더 표기를 위해) 매물(article) 단위다. 신규는 표시할 때만 cluster 로 접는다.
    급매(🔥)는 신규/가격변동의 부분집합이라 별도 섹션으로 한 번 더 강조한다(하한가·하락폭 표기).
    """
    if cr.error:
        if include_errors:
            return ([f"━━ {escape(cr.label)} ━━", f"⚠ 수집 실패: {escape(cr.error)}", ""], 0, 0, 0, 0)
        return ([], 0, 0, 0, 0)
    cdiff = cr.diff
    if cdiff is None:
        return ([], 0, 0, 0, 0)

    new_dtos = [op.dto for op in cdiff.new if op.dto and in_band(op.dto.price_deal, price_min, price_max)]
    # 가격변동은 신·구 어느 쪽이든 밴드에 걸치면 표시(밴드 진입/이탈도 의미 있음).
    price_ops = [
        op
        for op in cdiff.price_changed
        if op.dto
        and (
            in_band(op.dto.price_deal, price_min, price_max)
            or in_band(op.old_price_deal, price_min, price_max)
        )
    ]
    removed_ops = [op for op in cdiff.removed if in_band(op.old_price_deal, price_min, price_max)]
    flash_sigs = (
        [s for s in cr.flash if in_band(s.price_deal, price_min, price_max)]
        if show_flash else []
    )

    if not (new_dtos or price_ops or removed_ops or flash_sigs):
        return ([], 0, 0, 0, 0)

    starred = cr.complex_no in starred_complexes  # 관심 단지면 모든 변동에 ★
    header = ("★ " if starred else "") + escape(cr.name or cr.label)
    if cr.address:
        header += f"  <i>{escape(cr.address)}</i>"
    lines = [f"━━ {header} ━━"]

    if flash_sigs:
        lines.append("🔥 급매")
        flash_dtos = {op.article_no: op.dto for op in (cdiff.new + cdiff.price_changed) if op.dto}
        for sig in flash_sigs:
            lines.append(_flash_line(sig, flash_dtos.get(sig.article_no), starred))

    if new_dtos:
        lines.append("🆕 신규")
        clusters = group_by_cluster(new_dtos, key=lambda d: d.cluster_key)
        for dtos in clusters.values():
            lines.append(_new_line(dtos, starred))

    if price_ops:
        lines.append("📉 가격변동")
        for op in price_ops:
            lines.append(_price_line(op, starred))

    if removed_ops:
        lines.append("✅ 거래완료(추정)")
        for op in removed_ops:
            lines.append(_removed_line(op, starred))

    if not cr.fetch or not cr.fetch.complete:
        lines.append("⚠ 일부 수집 실패 — 거래완료 판정 생략됨")

    lines.append("")
    return (lines, len(new_dtos), len(price_ops), len(removed_ops), len(flash_sigs))


def build_digest(
    result: RunResult,
    dashboard_url: str,
    *,
    price_min: int | None = None,
    price_max: int | None = None,
    only_complexes: set[str] | None = None,
    drop_empty: bool = False,
    show_flash: bool = True,
) -> str | None:
    """RunResult → HTML 메시지 문자열.

    price_min/max: 구독자 가격밴드(만원, None=무제한). 밴드 밖 매물은 빼고 카운트도 다시 센다.
    only_complexes: 이 구독자가 받을 단지번호 집합(None=전체=운영자). 밖의 단지는 통째로 제외.
    drop_empty=True: 밴드 안에 보여줄 게 없으면 None 반환(개인화 발송 시 그 구독자 건너뛰기).
    show_flash: 🔥급매 섹션 표기 여부(config.flash.notify). False 면 텔레그램에서만 숨김(대시보드엔 남음).
    밴드가 걸린(둘 중 하나라도 not None) 경우 수집오류 블록은 생략한다(가격무관 운영잡음 차단).
    """
    include_errors = price_min is None and price_max is None
    body: list[str] = []
    n_new = n_price = n_removed = n_flash = 0
    for cr in result.complexes:
        if only_complexes is not None and cr.complex_no not in only_complexes:
            continue
        lines, a, b, c, e = _complex_block(
            cr, result.starred_complexes, price_min, price_max,
            include_errors=include_errors, show_flash=show_flash,
        )
        body.extend(lines)
        n_new += a
        n_price += b
        n_removed += c
        n_flash += e

    ts = result.started_at.strftime("%Y-%m-%d %H:%M")
    head = (
        f"🏠 <b>부동산 모니터</b> — {ts} KST\n"
        f"신규 {n_new} · 가격변동 {n_price} · 거래완료 {n_removed}"
    )
    if n_flash:
        head += f" · 🔥급매 {n_flash}"
    band_label = format_band(price_min, price_max)
    if band_label:
        head += f" · 🎯 {band_label}"
    if include_errors and result.http_errors:
        head += f"  ⚠수집오류 {result.http_errors}"

    if not body:
        if drop_empty:
            return None
        return head + "\n\n변동 없음."

    footer = f'📊 <a href="{escape(dashboard_url, quote=True)}">대시보드 열기</a>'
    return head + "\n\n" + "\n".join(body).rstrip() + "\n\n" + footer
