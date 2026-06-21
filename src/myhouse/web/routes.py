"""대시보드 라우트."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import Session

from ..constants import SOURCE_WEB
from ..core import on_demand
from ..db import repo
from ..db.engine import get_meta
from .queries import (
    DealFilters,
    FilterDomains,
    Filters,
    PermitFilters,
    address_option_map,
    build_area_group_rows,
    build_cluster_rows,
    build_deal_rows,
    build_permit_rows,
    complex_stats,
    deal_address_option_map,
    deal_complexes,
    filter_domains,
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


def _tpl(request: Request):
    return request.app.state.templates


# ── 페이지 ─────────────────────────────────────────────────────────────────
@router.get("/")
def index(
    request: Request,
    filters: Filters = Depends(get_filters),
    session: Session = Depends(get_session_dep),
):
    last_run_id = _last_run_id(session)
    rows = build_area_group_rows(session, filters, last_run_id)
    gu_dong_map = address_option_map(session)
    ctx = {
        "request": request,
        "rows": rows,
        "complexes": list_complexes_filtered(session, filters.gu, filters.dong),
        "f": filters,
        "gu_dong_map": gu_dong_map,
        "new_count": sum(1 for r in rows if r.is_new),
        "total": len(rows),
        "title": "매물 목록",
    }
    return _tpl(request).TemplateResponse(request, "index.html", ctx)


@router.get("/shortlist")
def shortlist():
    return RedirectResponse("/app/shortlist", status_code=302)


@router.get("/deals")
def deals():
    return RedirectResponse("/app/deals", status_code=302)


@router.get("/permits")
def permits():
    return RedirectResponse("/app/permits", status_code=302)


@router.get("/complex/{complex_no}")
def complex_detail(complex_no: str):
    return RedirectResponse(f"/app/complex/{complex_no}", status_code=302)


@router.get("/listing/{cluster_key}/history")
def listing_history(
    cluster_key: str,
    request: Request,
    session: Session = Depends(get_session_dep),
):
    points = price_history(session, cluster_key)
    ctx = {
        "request": request,
        "points": points,
        "spark": sparkline(points),
        "cluster_key": cluster_key,
    }
    return _tpl(request).TemplateResponse(request, "_price_history.html", ctx)


@router.get("/runs")
def runs():
    return RedirectResponse("/app/runs", status_code=302)


@router.get("/complexes")
def complexes_page():
    return RedirectResponse("/app/complexes", status_code=302)


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
@router.get("/map")
def map_view(request: Request):
    s = getattr(request.app.state, "settings", None)
    naver_key = (s.naver_map_client_id or "") if s else ""
    ctx = {"request": request, "title": "지도", "naver_map_key": naver_key}
    return _tpl(request).TemplateResponse(request, "map.html", ctx)


@router.get("/api/map-data")
def map_data(
    request: Request,
    session: Session = Depends(get_session_dep),
):
    rows = get_map_complexes(session, _last_run_id(session))
    return [dataclasses.asdict(r) for r in rows]


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
    return {
        "stat": dataclasses.asdict(stat),
        "rows": [dataclasses.asdict(r) for r in rows],
        "deals": [dataclasses.asdict(d) for d in deals],
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
@router.post("/run")
def run_now():
    try:
        subprocess.Popen(
            [sys.executable, "-m", "myhouse.cli", "collect", "--trigger", "manual"],
            cwd=os.getcwd(),
        )
    except OSError as e:
        return JSONResponse({"started": False, "error": str(e)}, status_code=500)
    return {"started": True}


@router.post("/run-deals")
def run_deals_now():
    try:
        subprocess.Popen(
            [sys.executable, "-m", "myhouse.cli", "collect-deals", "--trigger", "manual"],
            cwd=os.getcwd(),
        )
    except OSError as e:
        return JSONResponse({"started": False, "error": str(e)}, status_code=500)
    return {"started": True}


@router.post("/run-permits")
def run_permits_now():
    try:
        subprocess.Popen(
            [sys.executable, "-m", "myhouse.cli", "collect-permits", "--trigger", "manual"],
            cwd=os.getcwd(),
        )
    except OSError as e:
        return JSONResponse({"started": False, "error": str(e)}, status_code=500)
    return {"started": True}


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
        subprocess.Popen(cmd, cwd=os.getcwd())
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
