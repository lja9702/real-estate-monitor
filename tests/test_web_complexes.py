"""추적 단지 관리 — 대시보드 페이지 + 추가/해제/재추적 엔드포인트."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from myhouse.constants import SOURCE_PINNED, SOURCE_WEB
from myhouse.core.targets import resolve_targets
from myhouse.db import repo
from myhouse.db.engine import get_session, init_db, make_engine
from myhouse.db.models import Complex
from myhouse.settings import load_config
from myhouse.web.app import create_app


def _app(tmp_path, monkeypatch):
    db = tmp_path / "web.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "app": {"db_path": str(db), "request_delay_seconds": [0, 0]},
                "defaults": {"trade_types": ["SALE"]},
                "targets": [{"kind": "complex", "complex_no": "111", "label": "고정단지"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    engine = make_engine(db)
    init_db(engine)
    # config 고정 단지가 DB 행을 갖는 상태(첫 수집 이후)를 모사
    with get_session(engine) as s:
        repo.upsert_complex(s, "111", name="고정단지", source=SOURCE_PINNED, is_active=True)
    # '추적 추가' 의 백그라운드 수집 서브프로세스는 테스트에서 띄우지 않는다
    import myhouse.web.routes as routes

    monkeypatch.setattr(routes, "_spawn_add_collect", lambda no, alias: True)
    return create_app(str(cfg_path)), engine, cfg_path


def test_complexes_page_lists_tracked(tmp_path, monkeypatch):
    app, _engine, _ = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    # /complexes 는 SPA 셸로 리다이렉트(200) — 추적 목록은 /api/complexes 가 공급한다.
    assert client.get("/complexes").status_code == 200
    rows = client.get("/api/complexes").json()["rows"]
    assert "고정단지" in {r["name"] for r in rows}


def test_add_untrack_retrack_flow(tmp_path, monkeypatch):
    app, engine, _ = _app(tmp_path, monkeypatch)
    client = TestClient(app)

    # 추가 → web 출처로 추적 등록
    r = client.post("/complexes/add", data={"complex_no": "947", "alias": "삼호1차"})
    assert r.status_code == 200 and r.json()["ok"] is True
    with get_session(engine) as s:
        cx = s.get(Complex, "947")
    assert cx and cx.is_active and cx.source == SOURCE_WEB and cx.name == "삼호1차"

    # 숫자 아닌 번호 → 400
    bad = client.post("/complexes/add", data={"complex_no": "abc"})
    assert bad.status_code == 400 and bad.json()["ok"] is False

    # 추적 해제
    r = client.post("/complexes/947/untrack")
    assert r.status_code == 200 and r.json()["is_active"] is False
    with get_session(engine) as s:
        assert s.get(Complex, "947").is_active is False

    # 다시 추적
    r = client.post("/complexes/947/track")
    assert r.status_code == 200 and r.json()["is_active"] is True
    with get_session(engine) as s:
        assert s.get(Complex, "947").is_active is True

    # 없는 단지 해제 → 404
    assert client.post("/complexes/000000/untrack").status_code == 404


def test_untrack_config_complex_drops_from_collection(tmp_path, monkeypatch):
    app, engine, cfg_path = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    # config 고정 단지 111 을 UI 에서 추적 해제
    assert client.post("/complexes/111/untrack").json()["is_active"] is False
    # 정기 수집 타겟 해석에서 빠져야 한다
    cfg = load_config(str(cfg_path))
    with get_session(engine) as s:
        nos = {rt.complex.complex_no for rt in resolve_targets(cfg, s, client=None)}
    assert "111" not in nos
