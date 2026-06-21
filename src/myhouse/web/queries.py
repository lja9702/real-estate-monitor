"""대시보드 뷰 모델 — 매물(article)을 cluster 단위로 묶어 표시/큐레이션한다.

큐레이션(별표/제외/메모)은 cluster_key 기준이므로 표도 cluster 단위 행으로 보여준다.
한 cluster 행 = 같은 유닛(면적/층/향/거래유형), 여러 중개사의 호가를 min~max 로 묶음.
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, field

from sqlmodel import Session, func, select

from ..constants import SOURCE_KO, TRADE_TYPE_KO, ListingStatus, TradeType, now_kst
from ..core.dedup import price_range
from ..db.models import Complex, Curation, Deal, LandPermit, Listing, ListingHistory, Run
from ..util import format_complex_meta


@dataclass
class ClusterRow:
    cluster_key: str
    complex_no: str
    complex_name: str
    trade_type: TradeType
    trade_ko: str
    area_excl: float | None
    floor_info: str | None
    floor_num: int | None
    direction: str | None
    dong: str | None
    price_min: int | None
    price_max: int | None
    rent_min: int | None
    rent_max: int | None
    realtor_count: int
    status: str
    confirm_date: str | None
    feature_desc: str | None
    article_url: str | None
    address_short: str | None = None  # "서초구 방배동"
    meta_line: str | None = None      # "419세대(3개동) · 1975.11 준공 · ..."
    total_households: int | None = None
    use_approve_ymd: str | None = None  # 'YYYYMMDD' — 필터용
    is_new: bool = False
    starred: bool = False
    excluded: bool = False
    memo: str | None = None


# 클러스터 상태 우선순위 (낮을수록 '살아있음')
_STATUS_RANK = {"ACTIVE": 0, "PENDING_REMOVAL": 1, "REMOVED": 2}


def _cluster_status(items: list[Listing]) -> str:
    if any(i.status == ListingStatus.ACTIVE for i in items):
        return "ACTIVE"
    if any(i.status == ListingStatus.PENDING_REMOVAL for i in items):
        return "PENDING_REMOVAL"
    return "REMOVED"


def _avail(items: list[Listing]) -> list[Listing]:
    """거래완료(REMOVED) 제외한 살아있는 매물."""
    return [i for i in items if i.status != ListingStatus.REMOVED] or items


@dataclass
class Filters:
    complex_no: str | None = None
    trade_type: str | None = None
    status: str = "active"  # active | new | removed | all
    q: str | None = None
    price_min: int | None = None
    price_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    floor_min: int | None = None
    direction: str | None = None
    gu: str | None = None    # 예) "서초구"
    dong: str | None = None  # 예) "방배동"
    starred_only: bool = False
    show_excluded: bool = False
    sort: str = "new"  # new | price_asc | price_desc | area_desc | confirm_desc
    households_min: int | None = None  # 세대수 하한
    households_max: int | None = None  # 세대수 상한
    year_min: int | None = None        # 준공 연도 하한 (YYYY)
    year_max: int | None = None        # 준공 연도 상한 (YYYY)


def _text_match(row: ClusterRow, q: str) -> bool:
    hay = " ".join(
        filter(None, [row.complex_name, row.dong, row.direction, row.feature_desc])
    ).lower()
    return q.lower() in hay


def build_cluster_rows(
    session: Session, filters: Filters, last_run_id: int | None
) -> list[ClusterRow]:
    stmt = select(Listing)
    if filters.complex_no:
        stmt = stmt.where(Listing.complex_no == filters.complex_no)
    if filters.trade_type:
        stmt = stmt.where(Listing.trade_type == filters.trade_type)
    listings = list(session.exec(stmt))

    cx_map = {c.complex_no: c for c in session.exec(select(Complex))}

    groups: dict[str, list[Listing]] = {}
    for lst in listings:
        groups.setdefault(lst.cluster_key, []).append(lst)

    cur_map = {c.cluster_key: c for c in session.exec(select(Curation))}

    rows: list[ClusterRow] = []
    for ck, items in groups.items():
        cstatus = _cluster_status(items)
        avail = _avail(items)
        rep = avail[0]
        deposits = [i.price_deal for i in avail]
        rents = [i.price_rent for i in avail]
        pmin, pmax = price_range(deposits)
        rmin, rmax = price_range(rents)
        is_new = bool(last_run_id) and any(i.first_seen_run_id == last_run_id for i in items)
        cur = cur_map.get(ck)
        cx = cx_map.get(rep.complex_no)
        confirm = max((i.confirm_date for i in avail if i.confirm_date), default=None)

        rows.append(
            ClusterRow(
                cluster_key=ck,
                complex_no=rep.complex_no,
                complex_name=(cx.name if cx else rep.complex_no),
                trade_type=rep.trade_type,
                trade_ko=TRADE_TYPE_KO.get(rep.trade_type, rep.trade_type.value),
                area_excl=rep.area_excl,
                floor_info=rep.floor_info,
                floor_num=rep.floor_num,
                direction=rep.direction,
                dong=rep.dong,
                price_min=pmin,
                price_max=pmax,
                rent_min=rmin,
                rent_max=rmax,
                realtor_count=len(avail),
                status=cstatus,
                confirm_date=confirm,
                feature_desc=rep.feature_desc,
                article_url=rep.article_url,
                address_short=_short_address(cx.address if cx else None),
                meta_line=format_complex_meta(
                    households=cx.total_households,
                    dong_count=cx.total_dong_count,
                    use_approve_ymd=cx.use_approve_ymd,
                    floor_area_ratio=cx.floor_area_ratio,
                    building_coverage_ratio=cx.building_coverage_ratio,
                ) if cx else None,
                total_households=cx.total_households if cx else None,
                use_approve_ymd=cx.use_approve_ymd if cx else None,
                is_new=is_new,
                starred=bool(cx and cx.starred),  # 관심은 단지 단위
                excluded=bool(cur and cur.excluded),
                memo=cur.memo if cur else None,
            )
        )

    rows = [r for r in rows if _passes(r, filters)]
    _sort_rows(rows, filters.sort)
    return rows


def _passes(r: ClusterRow, f: Filters) -> bool:
    if f.status == "active" and r.status == "REMOVED":
        return False
    if f.status == "removed" and r.status != "REMOVED":
        return False
    if f.status == "new" and not r.is_new:
        return False
    if not f.show_excluded and r.excluded:
        return False
    if f.starred_only and not r.starred:
        return False
    if f.price_min is not None and (r.price_max is None or r.price_max < f.price_min):
        return False
    if f.price_max is not None and (r.price_min is None or r.price_min > f.price_max):
        return False
    if f.area_min is not None and (r.area_excl is None or r.area_excl < f.area_min):
        return False
    if f.area_max is not None and (r.area_excl is None or r.area_excl > f.area_max):
        return False
    if f.floor_min is not None and (r.floor_num is None or r.floor_num < f.floor_min):
        return False
    if f.direction and (not r.direction or f.direction not in r.direction):
        return False
    if f.gu and (not r.address_short or f.gu not in r.address_short):
        return False
    if f.dong and (not r.address_short or f.dong not in r.address_short):
        return False
    if f.q and not _text_match(r, f.q):
        return False
    if f.households_min is not None and (r.total_households is None or r.total_households < f.households_min):
        return False
    if f.households_max is not None and (r.total_households is None or r.total_households > f.households_max):
        return False
    yr = _approve_year(r.use_approve_ymd)
    if f.year_min is not None and (yr is None or yr < f.year_min):
        return False
    if f.year_max is not None and (yr is None or yr > f.year_max):
        return False
    return True


def _sort_rows(rows: list[ClusterRow], sort: str) -> None:
    if sort == "price_asc":
        rows.sort(key=lambda r: (r.price_min is None, r.price_min or 0))
    elif sort == "price_desc":
        rows.sort(key=lambda r: (r.price_min or 0), reverse=True)
    elif sort == "area_desc":
        rows.sort(key=lambda r: (r.area_excl or 0), reverse=True)
    elif sort == "confirm_desc":
        rows.sort(key=lambda r: (r.confirm_date or ""), reverse=True)
    else:  # new: 신규 먼저, 그 다음 확인일 최신
        rows.sort(
            key=lambda r: (
                _STATUS_RANK.get(r.status, 9),
                not r.is_new,
                _neg_date(r.confirm_date),
            )
        )


def _neg_date(d: str | None) -> str:
    # 확인일 내림차순 정렬용 — 최신이 앞으로 (간단히 역순 비교)
    return "" if d is None else "".join(chr(255 - ord(c)) if c.isdigit() else c for c in d)


def _approve_year(ymd: str | None) -> int | None:
    """'YYYYMMDD' → 연도 int. 없거나 형식 불일치 시 None."""
    if not ymd or len(ymd) < 4 or not ymd[:4].isdigit():
        return None
    return int(ymd[:4])


# ── 부가 뷰 ────────────────────────────────────────────────────────────────
@dataclass
class PricePoint:
    date: str
    price: int | None
    event: str


def price_history(session: Session, cluster_key: str) -> list[PricePoint]:
    stmt = (
        select(ListingHistory)
        .where(ListingHistory.cluster_key == cluster_key)
        .order_by(ListingHistory.recorded_at)
    )
    out: list[PricePoint] = []
    for h in session.exec(stmt):
        out.append(PricePoint(date=h.recorded_at[:10], price=h.price_deal, event=h.event_type.value))
    return out


def sparkline(points: list[PricePoint], width: int = 320, height: int = 70, pad: int = 10) -> dict | None:
    """가격 이력 → 인라인 SVG 좌표(차트 라이브러리 무의존)."""
    pts = [(p.date, p.price) for p in points if p.price is not None]
    if not pts:
        return None
    vals = [pr for _, pr in pts]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    n = len(pts)
    coords = []
    for i, (d, pr) in enumerate(pts):
        x = pad + (i * (width - 2 * pad) / max(n - 1, 1))
        y = pad + (height - 2 * pad) * (1 - (pr - lo) / span)
        coords.append({"x": round(x, 1), "y": round(y, 1), "price": pr, "date": d})
    return {
        "poly": " ".join(f"{c['x']},{c['y']}" for c in coords),
        "pts": coords,
        "lo": lo,
        "hi": hi,
        "w": width,
        "h": height,
    }


@dataclass
class ComplexStat:
    complex_no: str
    name: str
    active_count: int
    by_trade: dict[str, int] = field(default_factory=dict)
    price_min: int | None = None
    price_max: int | None = None
    new_30d: int = 0
    starred: bool = False  # 관심 단지 여부
    # '419세대(3개동) · 1975.11 준공 · 용적률 238% · 건폐율 23%' (값 있는 항목만, 없으면 None)
    meta_line: str | None = None


def complex_stats(session: Session, complex_no: str) -> ComplexStat:
    listings = list(
        session.exec(select(Listing).where(Listing.complex_no == complex_no))
    )
    cx = session.get(Complex, complex_no) or Complex(complex_no=complex_no)
    name = cx.name
    active = [lst for lst in listings if lst.status == ListingStatus.ACTIVE]
    by_trade: dict[str, int] = {}
    for lst in active:
        by_trade[TRADE_TYPE_KO.get(lst.trade_type, lst.trade_type.value)] = (
            by_trade.get(TRADE_TYPE_KO.get(lst.trade_type, lst.trade_type.value), 0) + 1
        )
    pmin, pmax = price_range([lst.price_deal for lst in active])
    return ComplexStat(
        complex_no=complex_no,
        name=name,
        active_count=len(active),
        by_trade=by_trade,
        price_min=pmin,
        price_max=pmax,
        starred=cx.starred,
        meta_line=format_complex_meta(
            households=cx.total_households,
            dong_count=cx.total_dong_count,
            use_approve_ymd=cx.use_approve_ymd,
            floor_area_ratio=cx.floor_area_ratio,
            building_coverage_ratio=cx.building_coverage_ratio,
        ),
    )


# ── 메인 페이지 면적 그룹 뷰 ───────────────────────────────────────────────

@dataclass
class AreaGroupRow:
    """단지 + 면적 + 거래유형 단위로 묶인 행 (메인 페이지용)."""
    rep_cluster_key: str       # 대표 cluster_key (가장 저렴한 cluster)
    complex_no: str
    complex_name: str
    address_short: str | None
    meta_line: str | None      # "419세대(3개동) · 1975.11 준공 · ..."
    trade_type: TradeType
    trade_ko: str
    area_excl: float | None    # 대표 전용면적
    price_min: int | None      # 그룹 내 최저가
    price_max: int | None      # 그룹 내 최고가
    rent_min: int | None
    rent_max: int | None
    is_new: bool               # 그룹 내 신규 여부
    rep_article_url: str | None
    starred: bool
    excluded: bool
    memo: str | None
    # 실거래가 — 같은 단지·평형·거래유형. 최근 1개월 범위 우선, 없으면 과거 최근 1건 폴백.
    deal_price_min: int | None = None  # 범위 하한 (폴백 시 단건 가격)
    deal_price_max: int | None = None  # 범위 상한 (폴백 시 min 과 동일)
    deal_date: str | None = None       # 폴백(과거 최근 1건)일 때의 거래일 (ISO)
    deal_is_recent: bool = False       # True=최근 1개월 범위, False=과거 최근 1건 폴백


def _area_key(area: float | None) -> int:
    """전용면적 → 평형 매칭 키 (정수). 매물과 실거래를 잇는 기준.

    네이버 매물은 전용면적을 '버림(floor)'으로 정수화해 저장하고(예: 84.97㎡→84),
    국토부 실거래는 정밀 소수로 들어온다(84.97). 따라서 실거래도 동일하게 버림해야
    같은 평형으로 매칭된다. round 를 쓰면 X.9x 평형이 +1 되어(84.97→85) 어긋난다.
    """
    return int(area) if area else -1


@dataclass
class DealSummary:
    """area-group 행에 붙는 실거래가 요약 (한 평형 묶음당 1개)."""
    price_min: int
    price_max: int
    is_recent: bool       # True=최근 1개월 범위, False=과거 최근 1건 폴백
    date: str | None      # 폴백일 때의 거래일(ISO), 범위일 때 None


def _deal_summaries_by_area(
    session: Session, complex_nos: set[str]
) -> dict[tuple, DealSummary]:
    """(complex_no, _area_key(area_excl), trade_type) → 실거래가 요약.

    매물 area-group 행에 '실거래가'를 붙이기 위한 조회. 취소 거래는 제외하고,
    면적 키는 area-group 묶음과 같은 _area_key(버림) 를 쓴다(면적 0/None 은 매칭 불가라 스킵).
    표시 기준: 최근 1개월 내 실거래가 있으면 그 가격 범위(min~max), 없으면 과거 최근 1건으로 폴백.
    """
    if not complex_nos:
        return {}
    deals = session.exec(
        select(Deal).where(
            Deal.complex_no.in_(list(complex_nos)),
            Deal.cancelled == False,  # noqa: E712
        )
    )
    grouped: dict[tuple, list[Deal]] = {}
    for d in deals:
        if not d.area_excl:
            continue
        key = (d.complex_no, _area_key(d.area_excl), d.trade_type)
        grouped.setdefault(key, []).append(d)

    cutoff = _months_ago_iso(1)  # 'YYYY-MM-DD' — 이 날짜 이후가 '최근 1개월'
    out: dict[tuple, DealSummary] = {}
    for key, items in grouped.items():
        recent = [d.price_deal for d in items if d.deal_date >= cutoff]
        if recent:
            out[key] = DealSummary(min(recent), max(recent), is_recent=True, date=None)
        else:
            latest = max(items, key=lambda d: d.deal_date)
            out[key] = DealSummary(
                latest.price_deal, latest.price_deal, is_recent=False, date=latest.deal_date
            )
    return out


def build_area_group_rows(
    session: Session, filters: Filters, last_run_id: int | None
) -> list[AreaGroupRow]:
    """ClusterRow를 (단지+면적+거래유형) 단위로 한 번 더 묶어 반환."""
    clusters = build_cluster_rows(session, filters, last_run_id)

    # (complex_no, area_key, trade_type) 로 묶기 — 실거래 매칭과 동일한 _area_key(버림) 사용
    bucket: dict[tuple, list[ClusterRow]] = {}
    for r in clusters:
        key = (r.complex_no, _area_key(r.area_excl), r.trade_type)
        bucket.setdefault(key, []).append(r)

    deal_lookup = _deal_summaries_by_area(session, {r.complex_no for r in clusters})

    result: list[AreaGroupRow] = []
    for key, rows in bucket.items():
        # 가격 오름차순으로 대표 선정
        rows.sort(key=lambda r: (r.price_min is None, r.price_min or 0))
        rep = rows[0]

        prices = [r.price_min for r in rows if r.price_min is not None]
        prices += [r.price_max for r in rows if r.price_max is not None]
        rents = [r.rent_min for r in rows if r.rent_min is not None]
        rents += [r.rent_max for r in rows if r.rent_max is not None]

        deal = deal_lookup.get(key)  # 묶음 키 == 실거래 조회 키 (동일 _area_key/버림)

        result.append(AreaGroupRow(
            rep_cluster_key=rep.cluster_key,
            complex_no=rep.complex_no,
            complex_name=rep.complex_name,
            address_short=rep.address_short,
            meta_line=rep.meta_line,
            trade_type=rep.trade_type,
            trade_ko=rep.trade_ko,
            area_excl=rep.area_excl,
            price_min=min(prices) if prices else None,
            price_max=max(prices) if prices else None,
            rent_min=min(rents) if rents else None,
            rent_max=max(rents) if rents else None,
            is_new=any(r.is_new for r in rows),
            rep_article_url=rep.article_url,
            starred=rep.starred,
            excluded=rep.excluded,
            memo=rep.memo,
            deal_price_min=deal.price_min if deal else None,
            deal_price_max=deal.price_max if deal else None,
            deal_date=deal.date if deal else None,
            deal_is_recent=deal.is_recent if deal else False,
        ))

    _sort_area_rows(result, filters.sort)
    return result


def _sort_area_rows(rows: list[AreaGroupRow], sort: str) -> None:
    if sort == "price_asc":
        rows.sort(key=lambda r: (r.price_min is None, r.price_min or 0))
    elif sort == "price_desc":
        rows.sort(key=lambda r: (r.price_min or 0), reverse=True)
    elif sort == "area_desc":
        rows.sort(key=lambda r: (r.area_excl or 0), reverse=True)
    else:  # new / confirm_desc → 신규 먼저, 그 다음 단지명
        rows.sort(key=lambda r: (not r.is_new, r.complex_name, r.area_excl or 0))


def _short_address(address: str | None) -> str | None:
    """서울특별시 서초구 방배동 123 → '서초구 방배동'"""
    if not address:
        return None
    gu = re.search(r"\w+구", address)
    dong = re.search(r"\w+동", address)
    if gu and dong:
        return f"{gu.group()} {dong.group()}"
    if gu:
        return gu.group()
    return None


def address_option_map(session: Session) -> dict[str, list[str]]:
    """gu → sorted [dong] 매핑. 필터 드롭다운용."""
    addrs = session.exec(select(Complex.address).where(Complex.address != None)).all()  # noqa: E711
    gu_dong: dict[str, set[str]] = {}
    for addr in addrs:
        if not addr:
            continue
        gu_m = re.search(r"\w+구", addr)
        dong_m = re.search(r"\w+동", addr)
        if gu_m:
            gu = gu_m.group()
            gu_dong.setdefault(gu, set())
            if dong_m:
                gu_dong[gu].add(dong_m.group())
    return {gu: sorted(dongs) for gu, dongs in sorted(gu_dong.items())}


def list_complexes(session: Session) -> list[Complex]:
    return list(session.exec(select(Complex).order_by(Complex.name)))


def list_complexes_filtered(
    session: Session, gu: str | None = None, dong: str | None = None
) -> list[Complex]:
    """gu/dong 조건에 맞는 단지만 반환 (단지 드롭다운 필터링용)."""
    complexes = list(session.exec(select(Complex).order_by(Complex.name)))
    if not gu and not dong:
        return complexes
    result = []
    for cx in complexes:
        short = _short_address(cx.address)
        if not short:
            continue
        if gu and gu not in short:
            continue
        if dong and dong not in short:
            continue
        result.append(cx)
    return result


def recent_runs(session: Session, limit: int = 30) -> list[Run]:
    return list(session.exec(select(Run).order_by(Run.id.desc()).limit(limit)))


# ── 추적 단지 관리 ───────────────────────────────────────────────────────────
@dataclass
class TrackingRow:
    complex_no: str
    name: str
    source: str
    source_ko: str
    is_active: bool
    address_short: str | None
    meta_line: str | None
    active_count: int  # 현재 활성 매물 수


def list_tracking_rows(session: Session) -> list[TrackingRow]:
    """추적 단지 관리 페이지용 — 모든 단지 + 활성 매물 수. 추적중 먼저, 그 다음 이름순."""
    active_nos = session.exec(
        select(Listing.complex_no).where(Listing.status == ListingStatus.ACTIVE)
    ).all()
    counts: dict[str, int] = {}
    for no in active_nos:
        counts[no] = counts.get(no, 0) + 1

    rows = [
        TrackingRow(
            complex_no=cx.complex_no,
            name=cx.name or cx.complex_no,
            source=cx.source,
            source_ko=SOURCE_KO.get(cx.source, cx.source),
            is_active=cx.is_active,
            address_short=_short_address(cx.address),
            meta_line=format_complex_meta(
                households=cx.total_households,
                dong_count=cx.total_dong_count,
                use_approve_ymd=cx.use_approve_ymd,
                floor_area_ratio=cx.floor_area_ratio,
                building_coverage_ratio=cx.building_coverage_ratio,
            ),
            active_count=counts.get(cx.complex_no, 0),
        )
        for cx in session.exec(select(Complex))
    ]
    rows.sort(key=lambda r: (not r.is_active, r.name))
    return rows


# ── 관심 단지(관심목록) ───────────────────────────────────────────────────────
@dataclass
class StarredComplexRow:
    complex_no: str
    name: str
    address_short: str | None
    meta_line: str | None
    is_active: bool          # 추적 중 여부(관심이라도 추적 해제 상태일 수 있음)
    active_count: int        # 현재 활성 매물 수
    sale_min: int | None     # 매매 호가 최저(만원)
    sale_max: int | None     # 매매 호가 최고(만원)
    new_count: int           # 마지막 수집 회차 신규 매물 수


def list_starred_complex_rows(
    session: Session, last_run_id: int | None
) -> list[StarredComplexRow]:
    """관심(별표) 단지 목록 — 활성 매물 수·매매 호가대·신규 수 요약. 이름순."""
    starred = session.exec(
        select(Complex).where(Complex.starred == True)  # noqa: E712
    ).all()
    if not starred:
        return []

    nos = [c.complex_no for c in starred]
    active = session.exec(
        select(Listing).where(
            Listing.complex_no.in_(nos),
            Listing.status == ListingStatus.ACTIVE,
        )
    ).all()

    by_cx: dict[str, list[Listing]] = {}
    for lst in active:
        by_cx.setdefault(lst.complex_no, []).append(lst)

    rows: list[StarredComplexRow] = []
    for cx in starred:
        listings = by_cx.get(cx.complex_no, [])
        sale_prices = [
            lst.price_deal
            for lst in listings
            if lst.trade_type == TradeType.SALE and lst.price_deal is not None
        ]
        smin, smax = price_range(sale_prices)
        rows.append(
            StarredComplexRow(
                complex_no=cx.complex_no,
                name=cx.name or cx.complex_no,
                address_short=_short_address(cx.address),
                meta_line=format_complex_meta(
                    households=cx.total_households,
                    dong_count=cx.total_dong_count,
                    use_approve_ymd=cx.use_approve_ymd,
                    floor_area_ratio=cx.floor_area_ratio,
                    building_coverage_ratio=cx.building_coverage_ratio,
                ),
                is_active=cx.is_active,
                active_count=len(listings),
                sale_min=smin,
                sale_max=smax,
                new_count=sum(
                    1
                    for lst in listings
                    if last_run_id and lst.first_seen_run_id == last_run_id
                ),
            )
        )
    rows.sort(key=lambda r: r.name)
    return rows  # starred list


# ── 실거래(deal) ─────────────────────────────────────────────────────────────
@dataclass
class DealRow:
    deal_key: str
    complex_no: str
    complex_name: str
    trade_type: TradeType
    trade_ko: str
    deal_date: str
    price_deal: int
    price_rent: int | None
    floor: int | None
    pyeong_name: str | None
    area_excl: float | None
    cancelled: bool
    address_short: str | None = None
    meta_line: str | None = None
    total_households: int | None = None
    use_approve_ymd: str | None = None
    is_new: bool = False


@dataclass
class DealFilters:
    complex_no: str | None = None
    gu: str | None = None
    dong: str | None = None
    trade_type: str | None = None
    months: int = 12  # 최근 N개월
    area_min: float | None = None
    area_max: float | None = None
    include_cancelled: bool = False
    q: str | None = None
    sort: str = "date_desc"  # date_desc | price_desc | price_asc
    households_min: int | None = None
    households_max: int | None = None
    year_min: int | None = None
    year_max: int | None = None


def _months_ago_iso(months: int) -> str:
    today = now_kst().date()
    y, m = today.year, today.month - months
    while m <= 0:
        m += 12
        y -= 1
    day = min(today.day, monthrange(y, m)[1])
    return f"{y:04d}-{m:02d}-{day:02d}"


def build_deal_rows(
    session: Session, f: DealFilters, last_deal_run_id: int | None, limit: int = 600
) -> list[DealRow]:
    stmt = select(Deal)
    if f.complex_no:
        stmt = stmt.where(Deal.complex_no == f.complex_no)
    if f.trade_type:
        stmt = stmt.where(Deal.trade_type == f.trade_type)
    if f.months:
        stmt = stmt.where(Deal.deal_date >= _months_ago_iso(f.months))
    if not f.include_cancelled:
        stmt = stmt.where(Deal.cancelled == False)  # noqa: E712
    deals = list(session.exec(stmt))

    cx_map = {c.complex_no: c for c in session.exec(select(Complex))}

    rows: list[DealRow] = []
    for d in deals:
        cx = cx_map.get(d.complex_no)
        addr_short = _short_address(cx.address if cx else None)
        rows.append(
            DealRow(
                deal_key=d.deal_key,
                complex_no=d.complex_no,
                complex_name=(cx.name if cx and cx.name else d.complex_no),
                trade_type=d.trade_type,
                trade_ko=TRADE_TYPE_KO.get(d.trade_type, d.trade_type.value),
                deal_date=d.deal_date,
                price_deal=d.price_deal,
                price_rent=d.price_rent,
                floor=d.floor,
                pyeong_name=d.pyeong_name,
                area_excl=d.area_excl,
                cancelled=d.cancelled,
                address_short=addr_short,
                meta_line=format_complex_meta(
                    households=cx.total_households if cx else None,
                    dong_count=cx.total_dong_count if cx else None,
                    use_approve_ymd=cx.use_approve_ymd if cx else None,
                    floor_area_ratio=cx.floor_area_ratio if cx else None,
                    building_coverage_ratio=cx.building_coverage_ratio if cx else None,
                ) if cx else None,
                total_households=cx.total_households if cx else None,
                use_approve_ymd=cx.use_approve_ymd if cx else None,
                is_new=bool(last_deal_run_id) and d.first_seen_run_id == last_deal_run_id,
            )
        )

    rows = [r for r in rows if _deal_passes(r, f)]
    _sort_deals(rows, f.sort)
    return rows[:limit]


def _deal_passes(r: DealRow, f: DealFilters) -> bool:
    if f.area_min is not None and (r.area_excl is None or r.area_excl < f.area_min):
        return False
    if f.area_max is not None and (r.area_excl is None or r.area_excl > f.area_max):
        return False
    if f.gu and (not r.address_short or f.gu not in r.address_short):
        return False
    if f.dong and (not r.address_short or f.dong not in r.address_short):
        return False
    if f.q:
        hay = " ".join(filter(None, [r.complex_name, r.pyeong_name])).lower()
        if f.q.lower() not in hay:
            return False
    if f.households_min is not None and (r.total_households is None or r.total_households < f.households_min):
        return False
    if f.households_max is not None and (r.total_households is None or r.total_households > f.households_max):
        return False
    yr = _approve_year(r.use_approve_ymd)
    if f.year_min is not None and (yr is None or yr < f.year_min):
        return False
    if f.year_max is not None and (yr is None or yr > f.year_max):
        return False
    return True


def _sort_deals(rows: list[DealRow], sort: str) -> None:
    if sort == "price_desc":
        rows.sort(key=lambda r: r.price_deal, reverse=True)
    elif sort == "price_asc":
        rows.sort(key=lambda r: r.price_deal)
    else:  # date_desc: 거래일 최신순, 동일일은 가격↓
        rows.sort(key=lambda r: (r.deal_date, r.price_deal), reverse=True)


def recent_deals_for_complex(
    session: Session, complex_no: str, last_deal_run_id: int | None, months: int = 24
) -> list[DealRow]:
    """단지 상세용 — 한 단지의 최근 실거래(취소 포함, 최신순)."""
    f = DealFilters(complex_no=complex_no, months=months, include_cancelled=True, sort="date_desc")
    return build_deal_rows(session, f, last_deal_run_id, limit=300)


def deal_complexes(session: Session) -> list[Complex]:
    """실거래가 1건 이상 있는 단지(필터 드롭다운용)."""
    nos = set(session.exec(select(Deal.complex_no)).all())
    if not nos:
        return []
    rows = session.exec(select(Complex).where(Complex.complex_no.in_(nos))).all()
    return sorted(rows, key=lambda c: c.name or c.complex_no)


def deal_address_option_map(session: Session) -> dict[str, list[str]]:
    """실거래 보유 단지의 gu→[dong] 매핑."""
    nos = set(session.exec(select(Deal.complex_no)).all())
    if not nos:
        return {}
    addrs = session.exec(
        select(Complex.address).where(
            Complex.complex_no.in_(nos), Complex.address != None  # noqa: E711
        )
    ).all()
    gu_dong: dict[str, set[str]] = {}
    for addr in addrs:
        if not addr:
            continue
        gu_m = re.search(r"\w+구", addr)
        dong_m = re.search(r"\w+동", addr)
        if gu_m:
            gu_dong.setdefault(gu_m.group(), set())
            if dong_m:
                gu_dong[gu_m.group()].add(dong_m.group())
    return {gu: sorted(d) for gu, d in sorted(gu_dong.items())}


# ── 지도 ────────────────────────────────────────────────────────────────────

@dataclass
class MapComplexRow:
    complex_no: str
    name: str
    lat: float
    lon: float
    active_count: int
    new_count: int
    min_price: int | None
    max_price: int | None
    trade_types: list[str] = field(default_factory=list)
    meta_line: str | None = None


def get_map_complexes(session: Session, last_run_id: int | None = None) -> list[MapComplexRow]:
    """좌표 있는 단지 + 활성 매물 집계 (지도 마커용)."""
    complexes = session.exec(
        select(Complex).where(Complex.lat != None)  # noqa: E711
    ).all()
    if not complexes:
        return []

    cx_map = {cx.complex_no: cx for cx in complexes}
    active_listings = session.exec(
        select(Listing).where(
            Listing.complex_no.in_(list(cx_map.keys())),
            Listing.status == ListingStatus.ACTIVE,
        )
    ).all()

    # complex_no별로 집계
    from collections import defaultdict
    grouped: dict[str, list[Listing]] = defaultdict(list)
    for lst in active_listings:
        grouped[lst.complex_no].append(lst)

    # 마지막 run에서 신규인 article_no 집합
    new_articles: set[str] = set()
    if last_run_id is not None:
        new_rows = session.exec(
            select(Listing.article_no).where(
                Listing.first_seen_run_id == last_run_id,
                Listing.complex_no.in_(list(cx_map.keys())),
            )
        ).all()
        new_articles = set(new_rows)

    rows: list[MapComplexRow] = []
    for cx_no, cx in cx_map.items():
        listings = grouped.get(cx_no, [])
        prices = [lst.price_deal for lst in listings if lst.price_deal is not None]
        trade_types = sorted(
            {TRADE_TYPE_KO.get(lst.trade_type, str(lst.trade_type)) for lst in listings}
        )
        rows.append(MapComplexRow(
            complex_no=cx_no,
            name=cx.name,
            lat=cx.lat,  # type: ignore[arg-type]
            lon=cx.lon,  # type: ignore[arg-type]
            active_count=len(listings),
            new_count=sum(1 for lst in listings if lst.article_no in new_articles),
            min_price=min(prices) if prices else None,
            max_price=max(prices) if prices else None,
            trade_types=trade_types,
            meta_line=format_complex_meta(
                households=cx.total_households,
                dong_count=cx.total_dong_count,
                use_approve_ymd=cx.use_approve_ymd,
                floor_area_ratio=cx.floor_area_ratio,
                building_coverage_ratio=cx.building_coverage_ratio,
            ),
        ))

    rows.sort(key=lambda r: r.name)
    return rows


# ── 토지거래허가 ─────────────────────────────────────────────────────────────

@dataclass
class PermitRow:
    permit_key: str
    complex_no: str
    complex_name: str
    address_short: str | None
    meta_line: str | None
    address: str
    permit_date: str | None
    job_gbn: str | None
    use_purp: str | None
    is_new: bool = False
    starred: bool = False


@dataclass
class PermitFilters:
    complex_no: str | None = None
    gu: str | None = None
    months: int = 3
    job_gbn: str | None = None
    q: str | None = None
    sort: str = "date_desc"
    households_min: int | None = None
    households_max: int | None = None
    year_min: int | None = None
    year_max: int | None = None


def build_permit_rows(
    session: Session, f: PermitFilters, last_permit_run_id: int | None, limit: int = 500
) -> list[PermitRow]:
    stmt = select(LandPermit)
    if f.complex_no:
        stmt = stmt.where(LandPermit.complex_no == f.complex_no)
    if f.months:
        stmt = stmt.where(LandPermit.permit_date >= _months_ago_iso(f.months))
    if f.job_gbn:
        stmt = stmt.where(LandPermit.job_gbn == f.job_gbn)
    permits = list(session.exec(stmt))

    cx_map = {c.complex_no: c for c in session.exec(select(Complex))}

    rows: list[PermitRow] = []
    for p in permits:
        cx = cx_map.get(p.complex_no)
        addr_short = _short_address(cx.address if cx else None)
        if f.gu and (not addr_short or f.gu not in addr_short):
            continue
        name = (cx.name if cx and cx.name else p.complex_no)
        if f.q:
            hay = " ".join(filter(None, [name, p.address])).lower()
            if f.q.lower() not in hay:
                continue
        if cx:
            if f.households_min is not None and (cx.total_households is None or cx.total_households < f.households_min):
                continue
            if f.households_max is not None and (cx.total_households is None or cx.total_households > f.households_max):
                continue
            yr = _approve_year(cx.use_approve_ymd)
            if f.year_min is not None and (yr is None or yr < f.year_min):
                continue
            if f.year_max is not None and (yr is None or yr > f.year_max):
                continue
        rows.append(PermitRow(
            permit_key=p.permit_key,
            complex_no=p.complex_no,
            complex_name=name,
            address_short=addr_short,
            meta_line=format_complex_meta(
                households=cx.total_households if cx else None,
                dong_count=cx.total_dong_count if cx else None,
                use_approve_ymd=cx.use_approve_ymd if cx else None,
                floor_area_ratio=cx.floor_area_ratio if cx else None,
                building_coverage_ratio=cx.building_coverage_ratio if cx else None,
            ) if cx else None,
            address=p.address or "",
            permit_date=p.permit_date,
            job_gbn=p.job_gbn,
            use_purp=p.use_purp,
            is_new=bool(last_permit_run_id) and p.first_seen_run_id == last_permit_run_id,
            starred=bool(cx and cx.starred),
        ))

    if f.sort == "date_asc":
        rows.sort(key=lambda r: (r.permit_date or ""))
    else:
        rows.sort(key=lambda r: (r.permit_date or ""), reverse=True)
    return rows[:limit]


def permit_complexes(session: Session) -> list[Complex]:
    """토지거래허가가 1건 이상 있는 단지(필터 드롭다운용)."""
    nos = set(session.exec(select(LandPermit.complex_no)).all())
    if not nos:
        return []
    rows = session.exec(select(Complex).where(Complex.complex_no.in_(nos))).all()
    return sorted(rows, key=lambda c: c.name or c.complex_no)


@dataclass
class FilterDomains:
    price_min: int
    price_max: int
    area_min: float
    area_max: float
    households_min: int
    households_max: int
    year_min: int
    year_max: int
    floor_max: int


def filter_domains(session: Session) -> FilterDomains:
    r = session.exec(
        select(
            func.min(Listing.price_deal), func.max(Listing.price_deal),
            func.min(Listing.area_excl), func.max(Listing.area_excl),
            func.min(Listing.floor_num), func.max(Listing.floor_num),
        ).where(Listing.status != ListingStatus.REMOVED)
    ).first()
    cx = session.exec(
        select(
            func.min(Complex.total_households), func.max(Complex.total_households),
            func.min(Complex.use_approve_ymd), func.max(Complex.use_approve_ymd),
        )
    ).first()

    def _year(ymd: str | None) -> int | None:
        return int(ymd[:4]) if ymd else None

    return FilterDomains(
        price_min=r[0] or 0,
        price_max=r[1] or 300000,
        area_min=r[2] or 0.0,
        area_max=r[3] or 200.0,
        households_min=cx[0] or 0,
        households_max=cx[1] or 5000,
        year_min=_year(cx[2]) or 1970,
        year_max=_year(cx[3]) or 2025,
        floor_max=r[5] or 30,
    )


def permit_address_option_map(session: Session) -> dict[str, list[str]]:
    """허가 보유 단지의 gu→[dong] 매핑 (필터용)."""
    nos = set(session.exec(select(LandPermit.complex_no)).all())
    if not nos:
        return {}
    addrs = session.exec(
        select(Complex.address).where(
            Complex.complex_no.in_(nos), Complex.address != None  # noqa: E711
        )
    ).all()
    gu_dong: dict[str, set[str]] = {}
    for addr in addrs:
        if not addr:
            continue
        gu_m = re.search(r"\w+구", addr)
        dong_m = re.search(r"\w+동", addr)
        if gu_m:
            gu_dong.setdefault(gu_m.group(), set())
            if dong_m:
                gu_dong[gu_m.group()].add(dong_m.group())
    return {gu: sorted(d) for gu, d in sorted(gu_dong.items())}
