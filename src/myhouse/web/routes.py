"""대시보드 라우트."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session

from ..constants import SOURCE_WEB
from ..core import on_demand
from ..core.auction_detail import get_case_events
from ..db import repo
from ..db.engine import get_meta
from ..db.models import Auction
from .auth import (
    COOKIE_NAME,
    MAX_AGE_SECONDS,
    cookie_is_secure,
    gate_page,
    safe_next,
    sign_token,
)
from .queries import (
    AuctionFilters,
    DealFilters,
    Filters,
    FlashFilters,
    PermitFilters,
    address_option_map,
    auction_address_option_map,
    auction_complexes,
    build_area_group_rows,
    build_auction_detail,
    build_auction_rows,
    build_cluster_rows,
    build_deal_rows,
    build_flash_rows,
    build_permit_rows,
    complex_stats,
    deal_address_option_map,
    deal_complexes,
    filter_domains,
    flash_address_option_map,
    flash_complexes,
    get_map_complexes,
    list_complexes_filtered,
    list_starred_complex_rows,
    list_tracking_rows,
    permit_address_option_map,
    permit_complexes,
    price_history,
    recent_deals_for_complex,
    recent_runs,
    sparkline,
)

router = APIRouter()


# ── 초대코드 게이트 ─────────────────────────────────────────────────────────
@router.get("/healthz")
def healthz():
    """헬스체크(클라우드 상시 호스트용) — 게이트 없이 통과."""
    return {"ok": True}


@router.get("/gate", response_class=HTMLResponse)
def gate_get(request: Request):
    return gate_page(next_path=request.query_params.get("next", "/"))


@router.post("/gate")
def gate_post(request: Request, code: str = Form(...), next: str = Form("/")):
    settings = request.app.state.settings
    dest = safe_next(next)
    if code.strip() in settings.web_invite_code_set:
        resp = RedirectResponse(url=dest, status_code=303)
        resp.set_cookie(
            COOKIE_NAME,
            sign_token(settings.gate_signing_secret),
            max_age=MAX_AGE_SECONDS,
            httponly=True,
            samesite="lax",
            secure=cookie_is_secure(request),
        )
        return resp
    return HTMLResponse(gate_page(next_path=dest, error=True), status_code=401)


@router.get("/api/me")
def api_me(request: Request):
    """현재 세션 역할 + 읽기전용 여부(프론트가 쓰기 컨트롤을 숨기는 데 사용)."""
    return {
        "authenticated": True,
        "role": getattr(request.state, "role", "member"),
        "readonly": bool(request.app.state.settings.cloud_readonly),
    }


# ── 의존성 ─────────────────────────────────────────────────────────────────
def get_session_dep(request: Request):
    with Session(request.app.state.engine) as session:
        yield session


def _i(v: str | None) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


def _f(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def get_filters(request: Request) -> Filters:
    qp = request.query_params

    def g(k: str) -> str | None:
        v = qp.get(k)
        return v if v not in (None, "") else None

    return Filters(
        complex_no=g("complex_no"),
        trade_type=g("trade_type"),
        status=g("status") or "active",
        q=g("q"),
        price_min=_i(g("price_min")),
        price_max=_i(g("price_max")),
        area_min=_f(g("area_min")),
        area_max=_f(g("area_max")),
        floor_min=_i(g("floor_min")),
        direction=g("direction"),
        gu=g("gu"),
        dong=g("dong"),
        starred_only=qp.get("starred_only") in ("on", "true", "1"),
        show_excluded=qp.get("show_excluded") in ("on", "true", "1"),
        sort=g("sort") or "new",
        households_min=_i(g("households_min")),
        households_max=_i(g("households_max")),
        year_min=_i(g("year_min")),
        year_max=_i(g("year_max")),
    )


def _last_run_id(session: Session) -> int | None:
    return _i(get_meta(session, "last_successful_run_id"))


def _last_deal_run_id(session: Session) -> int | None:
    return _i(get_meta(session, "last_deal_run_id"))


def _last_permit_run_id(session: Session) -> int | None:
    return _i(get_meta(session, "last_permit_run_id"))


def _last_auction_run_id(session: Session) -> int | None:
    return _i(get_meta(session, "last_auction_run_id"))


def get_deal_filters(request: Request) -> DealFilters:
    qp = request.query_params

    def g(k: str) -> str | None:
        v = qp.get(k)
        return v if v not in (None, "") else None

    return DealFilters(
        complex_no=g("complex_no"),
        gu=g("gu"),
        dong=g("dong"),
        trade_type=g("trade_type"),
        months=_i(g("months")) or 12,
        area_min=_f(g("area_min")),
        area_max=_f(g("area_max")),
        include_cancelled=qp.get("include_cancelled") in ("on", "true", "1"),
        q=g("q"),
        sort=g("sort") or "date_desc",
        households_min=_i(g("households_min")),
        households_max=_i(g("households_max")),
        year_min=_i(g("year_min")),
        year_max=_i(g("year_max")),
    )


def get_permit_filters(request: Request) -> PermitFilters:
    qp = request.query_params

    def g(k: str) -> str | None:
        v = qp.get(k)
        return v if v not in (None, "") else None

    return PermitFilters(
        complex_no=g("complex_no"),
        gu=g("gu"),
        months=_i(g("months")) or 3,
        job_gbn=g("job_gbn"),
        q=g("q"),
        sort=g("sort") or "date_desc",
        households_min=_i(g("households_min")),
        households_max=_i(g("households_max")),
        year_min=_i(g("year_min")),
        year_max=_i(g("year_max")),
    )


def get_auction_filters(request: Request) -> AuctionFilters:
    qp = request.query_params

    def g(k: str) -> str | None:
        v = qp.get(k)
        return v if v not in (None, "") else None

    return AuctionFilters(
        complex_no=g("complex_no"),
        gu=g("gu"),
        q=g("q"),
        sort=g("sort") or "date_asc",
    )


def get_flash_filters(request: Request) -> FlashFilters:
    qp = request.query_params

    def g(k: str) -> str | None:
        v = qp.get(k)
        return v if v not in (None, "") else None

    return FlashFilters(
        complex_no=g("complex_no"),
        gu=g("gu"),
        dong=g("dong"),
        trade_type=g("trade_type"),
        days=_i(g("days")) or 30,
        trigger=g("trigger"),
        include_inactive=qp.get("include_inactive") in ("on", "true", "1"),
        q=g("q"),
        sort=g("sort") or "drop_pct_desc",
        households_min=_i(g("households_min")),
        households_max=_i(g("households_max")),
        year_min=_i(g("year_min")),
        year_max=_i(g("year_max")),
    )


# ── 큐레이션 (JSON 응답, JS 로 즉시 반영) ─────────────────────────────────
@router.post("/curation/{cluster_key}/exclude")
def toggle_exclude(
    cluster_key: str,
    session: Session = Depends(get_session_dep),
    complex_no: str | None = Form(None),
):
    cur = repo.get_curation_map(session, [cluster_key]).get(cluster_key)
    excluded = not (cur.excluded if cur else False)
    repo.upsert_curation(session, cluster_key, excluded=excluded, complex_no=complex_no)
    return {"cluster_key": cluster_key, "excluded": excluded}


@router.post("/curation/{cluster_key}/memo")
def set_memo(
    cluster_key: str,
    session: Session = Depends(get_session_dep),
    memo: str = Form(""),
    complex_no: str | None = Form(None),
):
    repo.upsert_curation(session, cluster_key, memo=memo.strip() or None, complex_no=complex_no)
    return {"cluster_key": cluster_key, "memo": memo.strip()}


# ── 지도 ───────────────────────────────────────────────────────────────────
@router.get("/api/map-data")
def map_data(
    request: Request,
    session: Session = Depends(get_session_dep),
):
    rows = get_map_complexes(session, _last_run_id(session))
    return [dataclasses.asdict(r) for r in rows]


@router.get("/api/config")
def api_config(request: Request):
    s = getattr(request.app.state, "settings", None)
    return {"naver_map_client_id": (s.naver_map_client_id or None) if s else None}


# ── JSON API ──────────────────────────────────────────────────────────────

@router.get("/api/listings")
def api_listings(
    filters: Filters = Depends(get_filters),
    session: Session = Depends(get_session_dep),
):
    rows = build_area_group_rows(session, filters, _last_run_id(session))
    return {
        "rows": [dataclasses.asdict(r) for r in rows],
        "total": len(rows),
        "new_count": sum(1 for r in rows if r.is_new),
        "complexes": [
            {"complex_no": c.complex_no, "name": c.name or c.complex_no}
            for c in list_complexes_filtered(session, filters.gu, filters.dong)
        ],
        "gu_dong_map": address_option_map(session),
    }


@router.get("/api/filter-domains")
def api_filter_domains(session: Session = Depends(get_session_dep)):
    return dataclasses.asdict(filter_domains(session))


@router.get("/api/listing/{cluster_key}/history")
def api_listing_history(cluster_key: str, session: Session = Depends(get_session_dep)):
    pts = price_history(session, cluster_key)
    return {"points": [dataclasses.asdict(p) for p in pts], "spark": sparkline(pts)}


@router.get("/api/complex/{complex_no}")
def api_complex_detail(complex_no: str, session: Session = Depends(get_session_dep)):
    stat = complex_stats(session, complex_no)
    f = Filters(complex_no=complex_no, status="all", sort="price_asc")
    rows = build_cluster_rows(session, f, _last_run_id(session))
    deals = recent_deals_for_complex(session, complex_no, _last_deal_run_id(session))
    auctions = build_auction_rows(
        session, AuctionFilters(complex_no=complex_no), _last_auction_run_id(session)
    )
    return {
        "stat": dataclasses.asdict(stat),
        "rows": [dataclasses.asdict(r) for r in rows],
        "deals": [dataclasses.asdict(d) for d in deals],
        "auctions": [dataclasses.asdict(a) for a in auctions],
    }


@router.get("/api/deals")
def api_deals(
    f: DealFilters = Depends(get_deal_filters),
    session: Session = Depends(get_session_dep),
):
    rows = build_deal_rows(session, f, _last_deal_run_id(session))
    return {
        "rows": [dataclasses.asdict(r) for r in rows],
        "total": len(rows),
        "new_count": sum(1 for r in rows if r.is_new),
        "complexes": [
            {"complex_no": c.complex_no, "name": c.name or c.complex_no}
            for c in deal_complexes(session)
        ],
        "gu_dong_map": deal_address_option_map(session),
    }


@router.get("/api/permits")
def api_permits(
    f: PermitFilters = Depends(get_permit_filters),
    session: Session = Depends(get_session_dep),
):
    rows = build_permit_rows(session, f, _last_permit_run_id(session))
    return {
        "rows": [dataclasses.asdict(r) for r in rows],
        "total": len(rows),
        "new_count": sum(1 for r in rows if r.is_new),
        "complexes": [
            {"complex_no": c.complex_no, "name": c.name or c.complex_no}
            for c in permit_complexes(session)
        ],
        "gu_list": sorted(permit_address_option_map(session).keys()),
    }


@router.get("/api/auctions")
def api_auctions(
    f: AuctionFilters = Depends(get_auction_filters),
    session: Session = Depends(get_session_dep),
):
    rows = build_auction_rows(session, f, _last_auction_run_id(session))
    return {
        "rows": [dataclasses.asdict(r) for r in rows],
        "total": len(rows),
        "new_count": sum(1 for r in rows if r.is_new),
        "complexes": [
            {"complex_no": c.complex_no, "name": c.name or c.complex_no}
            for c in auction_complexes(session)
        ],
        "gu_list": sorted(auction_address_option_map(session).keys()),
    }


@router.get("/api/auction/{auction_key}")
def api_auction_detail(
    auction_key: str,
    request: Request,
    session: Session = Depends(get_session_dep),
):
    """물건 1건 상세 — 저장행 + 기일내역(매각/유찰 이력). 기일내역은 온디맨드 fetch·TTL 캐시.

    cloud_readonly(쓰기·수집 금지) 환경에선 라이브 fetch 없이 캐시만 반환.
    """
    row = session.get(Auction, auction_key)
    if row is None:
        raise HTTPException(status_code=404, detail="경매 물건을 찾을 수 없습니다.")
    settings = request.app.state.settings
    config = request.app.state.config
    events = get_case_events(
        row,
        allow_fetch=not settings.cloud_readonly,
        delay=config.app.request_delay_seconds,
    )
    return build_auction_detail(session, auction_key, events)


@router.get("/api/flash")
def api_flash(
    f: FlashFilters = Depends(get_flash_filters),
    session: Session = Depends(get_session_dep),
):
    rows = build_flash_rows(session, f, _last_run_id(session))
    return {
        "rows": [dataclasses.asdict(r) for r in rows],
        "total": len(rows),
        "new_count": sum(1 for r in rows if r.is_new),
        "complexes": [
            {"complex_no": c.complex_no, "name": c.name or c.complex_no}
            for c in flash_complexes(session)
        ],
        "gu_dong_map": flash_address_option_map(session),
    }


@router.get("/api/runs")
def api_runs(session: Session = Depends(get_session_dep)):
    runs = recent_runs(session)
    return {"runs": [{**r.model_dump(), "status": r.status.value} for r in runs]}


@router.get("/api/shortlist")
def api_shortlist(session: Session = Depends(get_session_dep)):
    rows = list_starred_complex_rows(session, _last_run_id(session))
    return {"rows": [dataclasses.asdict(r) for r in rows]}


@router.get("/api/complexes")
def api_complexes(session: Session = Depends(get_session_dep)):
    rows = list_tracking_rows(session)
    return {"rows": [dataclasses.asdict(r) for r in rows]}


# ── 지금 수집 ──────────────────────────────────────────────────────────────
# 백그라운드로 띄운 수집 자식 프로세스 핸들. poll() 로 종료분을 회수해 좀비(defunct)를
# 막는다 — 미회수 좀비는 os.kill(pid,0) 에 살아있다고 응답해 fail_orphan_runs 의 생존
# 판정을 속이고, 취소(pkill)로 죽은 run 의 자동 정리를 막는다.
_children: list[subprocess.Popen] = []


def _reap_children() -> None:
    """종료된 자식 프로세스를 회수(poll 이 waitpid 호출)."""
    for p in _children[:]:
        if p.poll() is not None:
            _children.remove(p)


def _spawn(cmd: list[str]) -> None:
    """수집 자식 프로세스를 띄우고 핸들을 추적. 직전에 종료분을 회수."""
    _reap_children()
    _children.append(subprocess.Popen(cmd, cwd=os.getcwd()))


@router.post("/run")
def run_now():
    try:
        _spawn([sys.executable, "-m", "myhouse.cli", "collect", "--trigger", "manual"])
    except OSError as e:
        return JSONResponse({"started": False, "error": str(e)}, status_code=500)
    return {"started": True}


@router.post("/run-deals")
def run_deals_now():
    try:
        _spawn([sys.executable, "-m", "myhouse.cli", "collect-deals", "--trigger", "manual"])
    except OSError as e:
        return JSONResponse({"started": False, "error": str(e)}, status_code=500)
    return {"started": True}


@router.post("/run-permits")
def run_permits_now():
    try:
        _spawn([sys.executable, "-m", "myhouse.cli", "collect-permits", "--trigger", "manual"])
    except OSError as e:
        return JSONResponse({"started": False, "error": str(e)}, status_code=500)
    return {"started": True}


@router.post("/run-auctions")
def run_auctions_now():
    try:
        _spawn([sys.executable, "-m", "myhouse.cli", "collect-auctions", "--trigger", "manual"])
    except OSError as e:
        return JSONResponse({"started": False, "error": str(e)}, status_code=500)
    return {"started": True}


@router.post("/run-cancel")
def run_cancel():
    """실행 중인 수집 프로세스(collect·collect-deals·collect-permits)를 모두 종료."""
    try:
        result = subprocess.run(
            ["pkill", "-f", "myhouse.cli collect"],
            capture_output=True,
        )
        _reap_children()  # 종료분 회수(미종료분은 SIGTERM 핸들러가 run 을 FAILED 로 정리)
        # pkill: 0 = 프로세스 종료됨, 1 = 매칭 없음
        return {"cancelled": result.returncode == 0}
    except OSError as e:
        return JSONResponse({"cancelled": False, "error": str(e)}, status_code=500)


# ── 추적 단지 추가/제거 (JSON 응답) ──────────────────────────────────────────
def _spawn_add_collect(complex_no: str, alias: str | None) -> bool:
    """추가한 단지 1건을 즉시 수집(백그라운드 서브프로세스). 텔레그램 /add 와 동일한 경로."""
    cmd = [
        sys.executable, "-m", "myhouse.cli", "add-complex", complex_no,
        "--source", SOURCE_WEB,
        "--config", os.environ.get("MYHOUSE_CONFIG", "config.yaml"),
    ]
    if alias:
        cmd += ["--alias", alias]
    try:
        _spawn(cmd)
        return True
    except OSError:
        return False


@router.post("/complexes/add")
def add_tracking(
    request: Request,
    complex_no: str = Form(...),
    alias: str = Form(""),
):
    no = (complex_no or "").strip()
    if not no.isdigit():
        return JSONResponse(
            {"ok": False, "error": "단지번호(숫자)를 입력하세요."}, status_code=400
        )
    nick = alias.strip() or None
    cx = on_demand.track_complex(
        request.app.state.config, request.app.state.engine, no, alias=nick, source=SOURCE_WEB
    )
    collecting = _spawn_add_collect(no, nick)
    return {"ok": True, "complex_no": no, "name": cx.name, "collecting": collecting}


@router.post("/complexes/{complex_no}/untrack")
def untrack_tracking(complex_no: str, request: Request):
    if not on_demand.untrack_complex(request.app.state.engine, complex_no):
        return JSONResponse(
            {"ok": False, "error": "단지를 찾을 수 없습니다."}, status_code=404
        )
    return {"ok": True, "complex_no": complex_no, "is_active": False}


@router.post("/complexes/{complex_no}/track")
def track_tracking(complex_no: str, request: Request):
    cx = on_demand.track_complex(
        request.app.state.config, request.app.state.engine, complex_no, source=SOURCE_WEB
    )
    return {"ok": True, "complex_no": complex_no, "name": cx.name, "is_active": True}


# ── 관심 단지(별표) 토글 (JSON 응답) ─────────────────────────────────────────
@router.post("/complexes/{complex_no}/star")
def toggle_complex_star(
    complex_no: str,
    session: Session = Depends(get_session_dep),
):
    cx = repo.get_complex(session, complex_no)
    starred = not (cx.starred if cx else False)
    if repo.set_complex_starred(session, complex_no, starred) is None:
        return JSONResponse(
            {"ok": False, "error": "단지를 찾을 수 없습니다(첫 수집 후 가능)."}, status_code=404
        )
    return {"ok": True, "complex_no": complex_no, "starred": starred}
