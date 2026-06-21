"""텔레그램 봇 명령 응답 메시지(HTML) 구성.

다이제스트(digest.py)는 정기 수집 푸시용, 여기는 사용자 질의에 대한 즉답용이다.
순수 포매팅 — 입력(결과 객체 + 스냅샷 행)만 받아 문자열을 만든다(네트워크/DB 무의존).
"""

from __future__ import annotations

from html import escape

from ..constants import TRADE_TYPE_KO, TradeType
from ..core.collector import ComplexResult, RunResult
from ..core.deal_collector import DealRunResult
from ..core.diff import DiffOp
from ..core.on_demand import AddResult, Candidate
from ..naver.parser import ArticleDTO
from ..naver.search_parser import SearchHit
from ..util import format_manwon, format_price

HELP = (
    "🏠 <b>myhouse 부동산 봇</b>\n"
    "관심 단지의 매물·실거래를 즉시 확인합니다.\n\n"
    "<b>명령</b>\n"
    "• <code>/add 1234 [별칭]</code> 또는 <code>/add 방배 삼호1차</code> — 단지를 추적 목록에 추가(정기 수집 포함) + 즉시 수집(번호·이름·주소)\n"
    "• <code>/check 1234</code> · <code>/check 도곡렉슬</code> · <code>/check 방배 삼호1차</code> — 매물 갱신 + 변동(번호·이름·주소)\n"
    "• <code>/deals 1234</code> 또는 <code>/deals 방배 삼호1차</code> — 최근 실거래(번호·이름·주소)\n"
    "• <code>/permits [1234]</code> 또는 <code>/permits 방배 삼호1차</code> — 최근 토지거래허가 내역(번호·이름·주소, 생략 시 전체 단지)\n"
    "• <code>/discover</code> — 관심 지역에서 조건(매매 15~26억 등)에 새로 든 단지 탐색\n"
    "• <code>/band 7 12</code> — 정기 알림을 받을 관심 가격대(억) 설정(<code>/band</code>=보기, <code>/band off</code>=전체)\n"
    "• <code>/list</code> — 내가 추가한 단지 목록\n"
    "• <code>/help</code> — 이 도움말\n\n"
    "단지번호 또는 단지명만 보내도 매물을 조회합니다. "
    "추적 목록에 없는 번호는 1회만 보여주고 추적하지 않습니다(추적하려면 <code>/add</code>)."
)


def format_help(is_operator: bool = False) -> str:
    if is_operator:
        return HELP + (
            "\n\n<b>운영자</b>\n"
            "• <code>/as &lt;chat_id&gt; &lt;명령&gt;</code> — 그 유저 시점으로 실행(개인화 검증). "
            "예: <code>/as 7745991913 list</code>"
        )
    return HELP


def format_unknown(cmd: str) -> str:
    return f"❓ 모르는 명령입니다: <code>/{escape(cmd)}</code>\n\n" + HELP


def format_not_found(query: str) -> str:
    return (
        f"🔍 '<b>{escape(query)}</b>' 에 해당하는 단지를 찾지 못했습니다.\n"
        "단지번호(예: <code>/check 1234</code>) 또는 정확한 단지명으로 다시 시도하세요."
    )


def format_candidates(query: str, candidates: list[Candidate]) -> str:
    lines = [f"🔎 '<b>{escape(query)}</b>' — 여러 단지가 검색됐습니다. 번호로 선택하세요:"]
    for c in candidates[:20]:
        lines.append(f"• <code>{escape(c.complex_no)}</code> {escape(c.name)}")
    if len(candidates) > 20:
        lines.append(f"… 외 {len(candidates) - 20}개")
    return "\n".join(lines)


def _hit_line(h: SearchHit) -> str:
    bits = [f"<code>{escape(h.complex_no)}</code> {escape(h.name)}"]
    if h.address:
        bits.append(escape(h.address))
    extra = " · ".join(
        filter(None, [h.type_name and escape(h.type_name), h.households and f"{h.households}세대"])
    )
    line = " · ".join(bits)
    return f"• {line}" + (f" ({extra})" if extra else "")


_CMD_VERB = {"add": "추가", "deals": "실거래 조회", "check": "조회"}


def format_search_candidates(query: str, hits: list[SearchHit], command: str = "add") -> str:
    """주소/이름 검색이 여러 단지로 매칭될 때 — 번호로 골라 다시 보내도록 안내."""
    verb = _CMD_VERB.get(command, "선택")
    lines = [
        f"🔎 '<b>{escape(query)}</b>' — 여러 단지가 검색됐습니다. "
        f"번호로 {verb}하세요(예: <code>/{escape(command)} 1234</code>):"
    ]
    for h in hits[:15]:
        lines.append(_hit_line(h))
    if len(hits) > 15:
        lines.append(f"… 외 {len(hits) - 15}개 — 검색어를 더 좁혀보세요")
    return "\n".join(lines)


def format_add_candidates(query: str, hits: list[SearchHit]) -> str:
    return format_search_candidates(query, hits, "add")


def format_add_not_found(query: str) -> str:
    return (
        f"🔍 '<b>{escape(query)}</b>' 로 단지를 찾지 못했습니다.\n"
        "단지명을 더 정확히 적거나(예: '방배삼호1차'), 단지번호로 추가하세요: <code>/add 1234</code>"
    )


def format_list(rows: list[tuple[str, str]]) -> str:
    """rows: [(complex_no, name)] — 텔레그램으로 추가한 추적 단지."""
    if not rows:
        return (
            "📭 텔레그램으로 추가한 단지가 없습니다.\n"
            "<code>/add 1234</code> 로 추가하세요(정기 수집에도 포함됩니다)."
        )
    lines = [f"📋 <b>추적 단지</b> ({len(rows)}개) — 텔레그램 추가분"]
    for no, name in rows:
        lines.append(f"• <code>{escape(no)}</code> {escape(name or no)}")
    return "\n".join(lines)


# ── 매물 변동/스냅샷 ──────────────────────────────────────────────────────────
def _floor(dto: ArticleDTO) -> str:
    if dto.floor_num is not None:
        return f"{dto.floor_num}층"
    return (dto.floor_info or "").split("/", 1)[0]


def _dto_spec(dto: ArticleDTO) -> str:
    bits: list[str] = []
    if dto.area_excl:
        bits.append(f"{dto.area_excl:g}㎡")
    fl = _floor(dto)
    if fl:
        bits.append(fl)
    if dto.direction:
        bits.append(escape(dto.direction))
    return " · ".join(bits)


def _link(url: str | None, text: str = "보기") -> str:
    return f' <a href="{escape(url, quote=True)}">{escape(text)}</a>' if url else ""


def _new_line(op: DiffOp) -> str:
    dto = op.dto
    assert dto is not None
    trade_ko = TRADE_TYPE_KO[dto.trade_type]
    price = format_price(trade_ko, dto.price_deal, dto.price_rent)
    return f"• {trade_ko} {price} · {_dto_spec(dto)}{_link(dto.article_url)}"


def _price_line(op: DiffOp) -> str:
    dto = op.dto
    assert dto is not None
    trade_ko = TRADE_TYPE_KO[dto.trade_type]
    old = format_price(trade_ko, op.old_price_deal, op.old_price_rent)
    new = format_price(trade_ko, dto.price_deal, dto.price_rent)
    delta = ""
    if op.old_price_deal is not None and dto.price_deal is not None:
        d = dto.price_deal - op.old_price_deal
        if d:
            delta = f" ({'▼' if d < 0 else '▲'}{format_manwon(abs(d))})"
    return f"• {old} → {new}{delta} · {_dto_spec(dto)}{_link(dto.article_url)}"


def _removed_line(op: DiffOp) -> str:
    return f"• {format_manwon(op.old_price_deal)} 매물 미노출 → 거래완료(추정)"


def _change_lines(cr: ComplexResult) -> list[str]:
    cdiff = cr.diff
    if cdiff is None:
        return []
    out: list[str] = []
    if cdiff.new:
        out.append("🆕 신규")
        out += [_new_line(op) for op in cdiff.new if op.dto]
    if cdiff.price_changed:
        out.append("📉 가격변동")
        out += [_price_line(op) for op in cdiff.price_changed if op.dto]
    if cdiff.removed:
        out.append("✅ 거래완료(추정)")
        out += [_removed_line(op) for op in cdiff.removed]
    return out


def _snapshot_line(row) -> str:  # noqa: ANN001 — web.queries.ClusterRow 덕타이핑
    trade_ko = row.trade_ko
    bits: list[str] = [trade_ko]
    if row.area_excl:
        bits.append(f"{row.area_excl:g}㎡")
    if row.floor_num is not None:
        bits.append(f"{row.floor_num}층")
    elif row.floor_info:
        bits.append(row.floor_info.split("/", 1)[0])
    if row.direction:
        bits.append(escape(row.direction))
    if row.trade_type == TradeType.WOLSE or row.rent_min:
        lo = format_manwon(row.price_min)
        rent = f"/{format_manwon(row.rent_min)}" if row.rent_min else ""
        price = f"{lo}{rent}"
    else:
        lo, hi = row.price_min, row.price_max
        price = format_manwon(lo) if lo == hi else f"{format_manwon(lo)}~{format_manwon(hi)}"
    spec = " · ".join(bits)
    realtor = f" · 중개 {row.realtor_count}곳" if row.realtor_count > 1 else ""
    star = "★ " if getattr(row, "starred", False) else ""
    return f"• {star}{spec} · <b>{price}</b>{realtor}{_link(row.article_url)}"


def _complex_link(dashboard_url: str, complex_no: str) -> str:
    base = dashboard_url.rstrip("/")
    return f'📊 <a href="{escape(base + "/complex/" + complex_no, quote=True)}">대시보드</a>'


def format_check_reply(
    result: RunResult,
    snapshot,  # list[web.queries.ClusterRow]
    *,
    complex_no: str,
    tracked: bool,
    dashboard_url: str,
    max_rows: int = 15,
) -> str:
    cr: ComplexResult | None = result.complexes[0] if result.complexes else None
    if cr is None:
        return f"⚠ 단지 {escape(complex_no)} 수집 결과가 없습니다."

    title = escape(cr.name or cr.label or complex_no)
    head = f"🏠 <b>{title}</b>"
    if cr.address:
        head += f"  <i>{escape(cr.address)}</i>"
    tag = "추적 중" if tracked else "1회 조회(미추적 · /add 로 추적)"
    head += f"\n<code>{escape(complex_no)}</code> · {tag}"

    if cr.error:
        return head + f"\n\n⚠ 수집 실패: {escape(cr.error)}"

    lines = [head, ""]
    changes = _change_lines(cr)
    if changes:
        lines.append(
            f"<b>이번 갱신</b> — 신규 {result.new_count} · 가격변동 "
            f"{result.price_changed_count} · 거래완료 {result.removed_count}"
        )
        lines += changes
        lines.append("")
    else:
        lines.append("<b>이번 갱신</b> — 변동 없음")
        lines.append("")

    active = [r for r in snapshot if r.status != "REMOVED"]
    active.sort(key=lambda r: (r.price_min is None, r.price_min or 0))
    if active:
        lines.append(f"<b>현재 매물</b> {len(active)}건")
        lines += [_snapshot_line(r) for r in active[:max_rows]]
        if len(active) > max_rows:
            lines.append(f"… 외 {len(active) - max_rows}건 (대시보드에서 전체 보기)")
    else:
        lines.append("<b>현재 매물</b> 없음")

    if not cr.fetch or not cr.fetch.complete:
        lines.append("⚠ 일부 수집 실패 — 거래완료 판정 생략됨")

    lines.append("")
    lines.append(_complex_link(dashboard_url, complex_no))
    return "\n".join(lines)


# ── 실거래 ────────────────────────────────────────────────────────────────────
def _deal_date(iso: str) -> str:
    return f"{iso[2:4]}.{iso[5:7]}.{iso[8:10]}" if len(iso) >= 10 and iso[4] == "-" else iso


def _deal_row_line(row) -> str:  # noqa: ANN001 — web.queries.DealRow 덕타이핑
    trade_ko = row.trade_ko
    price = format_manwon(row.price_deal)
    if row.price_rent:
        price += f"/{format_manwon(row.price_rent)}"
    bits = [f"{trade_ko} {price}"]
    if row.pyeong_name or row.area_excl:
        py = escape(row.pyeong_name) if row.pyeong_name else ""
        area = f"{row.area_excl:g}㎡" if row.area_excl else ""
        bits.append(f"{py}({area})" if py and area else (py or area))
    if row.floor is not None:
        bits.append(f"{row.floor}층")
    bits.append(_deal_date(row.deal_date))
    flag = " ❌취소" if row.cancelled else (" 🆕" if getattr(row, "is_new", False) else "")
    return "• " + " · ".join(bits) + flag


def format_deals_reply(
    result: DealRunResult,
    recent,  # list[web.queries.DealRow]
    *,
    complex_no: str,
    name: str,
    dashboard_url: str,
    max_rows: int = 15,
) -> str:
    head = f"🏛 <b>{escape(name or complex_no)}</b> 실거래\n<code>{escape(complex_no)}</code>"

    cr = result.complexes[0] if result.complexes else None
    if cr and cr.error and not (cr.new_deals or cr.cancelled_deals):
        # 수집 자체가 실패했고 신규도 없으면 캐시된 최근 거래라도 보여준다
        head += "\n⚠ 이번 갱신 일부 실패 — 저장된 최근 실거래를 표시합니다"

    lines = [head, ""]
    lines.append(f"<b>이번 갱신</b> — 신규 {result.new_count} · 취소 {result.cancelled_count}")

    valid = [r for r in recent if not r.cancelled]
    if valid:
        lines.append("")
        lines.append("<b>최근 실거래</b>")
        lines += [_deal_row_line(r) for r in valid[:max_rows]]
        if len(valid) > max_rows:
            lines.append(f"… 외 {len(valid) - max_rows}건")
    else:
        lines.append("")
        lines.append("최근 실거래 내역이 없습니다(면적 필터에 맞는 거래 없음일 수 있음).")

    base = dashboard_url.rstrip("/")
    url = f"{base}/deals?complex_no={complex_no}"
    lines.append("")
    lines.append(f'📊 <a href="{escape(url, quote=True)}">실거래 대시보드</a>')
    return "\n".join(lines)


def format_add_reply(
    add: AddResult,
    snapshot,  # list[web.queries.ClusterRow]
    *,
    dashboard_url: str,
    max_rows: int = 12,
) -> str:
    cr: ComplexResult | None = add.run.complexes[0] if add.run.complexes else None
    head = f"✅ 추적 시작 — 🏠 <b>{escape(add.name)}</b>  <code>{escape(add.complex_no)}</code>"
    if cr and cr.address:
        head += f"\n<i>{escape(cr.address)}</i>"
    head += "\n정기 수집(하루 2회)에 포함됩니다."
    if not add.name_resolved:
        head += (
            f"\n⚠ 단지명을 자동으로 찾지 못해 임시로 '{escape(add.name)}' 로 저장했습니다. "
            f"<code>/add {escape(add.complex_no)} 원하는이름</code> 으로 다시 보내면 이름을 바꿉니다."
        )

    if cr and cr.error:
        return head + f"\n\n⚠ 첫 수집 실패: {escape(cr.error)} (다음 정기 수집에서 재시도)"

    lines = [head, ""]
    active = [r for r in snapshot if r.status != "REMOVED"]
    active.sort(key=lambda r: (r.price_min is None, r.price_min or 0))
    if active:
        lines.append(f"<b>현재 매물</b> {len(active)}건")
        lines += [_snapshot_line(r) for r in active[:max_rows]]
        if len(active) > max_rows:
            lines.append(f"… 외 {len(active) - max_rows}건")
    else:
        lines.append("<b>현재 매물</b> 없음 (필터 조건에 맞는 매물이 없을 수 있음)")
    lines.append("")
    lines.append(_complex_link(dashboard_url, add.complex_no))
    return "\n".join(lines)


# ── 토지거래허가 ───────────────────────────────────────────────────────────────

def _permit_row_line(row) -> str:  # noqa: ANN001 — web.queries.PermitRow 덕타이핑
    date = row.permit_date or "-"
    gbn = escape(row.job_gbn or "-")
    jibun = escape(row.address.split()[-1]) if row.address else "-"
    purp = escape(row.use_purp or "")
    bits = [date, gbn, jibun]
    if purp:
        bits.append(purp)
    flag = " 🆕" if getattr(row, "is_new", False) else ""
    return "• " + " · ".join(bits) + flag


def format_permits_reply(
    rows,  # list[web.queries.PermitRow]
    *,
    complex_no: str | None,
    name: str | None,
    dashboard_url: str,
    months: int = 3,
    max_rows: int = 20,
) -> str:
    if not rows:
        scope = f"<b>{escape(name or complex_no or '전체')}</b>" if (name or complex_no) else "전체 단지"
        return (
            f"🏛 <b>토지거래허가</b> {scope}\n"
            f"최근 {months}개월 내 허가 내역이 없습니다.\n"
            "<i>※ 서울 토지거래허가구역(강남3구·용산 등) 단지만 집계됩니다.</i>"
        )

    scope = f"<b>{escape(name or complex_no or '전체')}</b>" if (name or complex_no) else "전체 단지"
    # 허가 건만 분리해서 맨 위에 안내
    granted = [r for r in rows if r.job_gbn == "허가"]
    head = (
        f"🏛 <b>토지거래허가</b> {scope}\n"
        f"최근 {months}개월 · 총 {len(rows)}건(허가 {len(granted)}건)"
    )

    lines = [head, ""]

    # 단지별 그룹 (전체 조회 시)
    if not complex_no:
        from collections import defaultdict
        by_cx: dict[str, list] = defaultdict(list)
        for r in rows[:max_rows * 3]:
            by_cx[r.complex_no].append(r)
        shown = 0
        for _cx_no, cx_rows in list(by_cx.items())[:10]:
            cx_name = escape(cx_rows[0].complex_name)
            star = "★ " if cx_rows[0].starred else ""
            lines.append(f"<b>{star}{cx_name}</b>")
            for r in cx_rows[:5]:
                lines.append(_permit_row_line(r))
                shown += 1
            lines.append("")
        if len(by_cx) > 10:
            lines.append(f"… 외 {len(by_cx) - 10}개 단지")
    else:
        lines.append(f"<b>허가 내역</b> {len(rows)}건")
        for r in rows[:max_rows]:
            lines.append(_permit_row_line(r))
        if len(rows) > max_rows:
            lines.append(f"… 외 {len(rows) - max_rows}건")

    permits_url = dashboard_url.rstrip("/") + "/permits"
    if complex_no:
        permits_url += f"?complex_no={complex_no}"
    lines.append("")
    lines.append(f'📊 <a href="{escape(permits_url, quote=True)}">토지거래허가 대시보드</a>')
    lines.append("<i>※ 허가는 거래 성사 전 단계 신호 — 가격은 실거래로 확인하세요.</i>")
    return "\n".join(lines)
