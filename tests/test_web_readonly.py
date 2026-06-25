"""읽기 전용 클라우드 모드(CLOUD_READONLY=1) — ro DB 읽기 OK, 모든 쓰기/수집 트리거 403."""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlmodel import select
from tests.conftest import make_dto

from myhouse.core.collector import run_collection
from myhouse.db.engine import get_session, init_db, make_engine
from myhouse.db.models import Listing
from myhouse.naver.client import FetchResult
from myhouse.settings import Settings, load_config
from myhouse.web.app import create_app


class _FakeClient:
    def __init__(self, results):
        self._q = list(results)

    def fetch_articles(self, complex_row, filt):
        return self._q.pop(0)

    def fetch_complex_meta(self, complex_no):
        return None

    def fetch_complex_address(self, complex_no, article_no):
        return None

    def fetch_complex_coords(self, complex_no):
        return None

    def close(self):
        pass


def _seed_db(tmp_path):
    """쓰기 엔진으로 단지 1개를 수집·적재하고 WAL 을 본 파일로 체크포인트한 뒤 닫는다."""
    db = tmp_path / "ro.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "app": {"db_path": str(db), "request_delay_seconds": [0, 0]},
                "defaults": {"trade_types": ["SALE"]},
                "targets": [{"kind": "complex", "complex_no": "111", "label": "테스트단지"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    engine = make_engine(db)
    init_db(engine)
    fr = FetchResult("111", [make_dto("1", price_deal=158000)], complete=True, raw_count=1)
    run_collection(cfg, Settings(_env_file=None), engine, client=_FakeClient([fr]))
    with engine.begin() as c:
        c.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")  # ro 가 모든 데이터를 보게
    with get_session(engine) as s:
        ck = s.exec(select(Listing)).first().cluster_key
    engine.dispose()
    return cfg_path, ck


def test_readonly_reads_ok_writes_blocked(tmp_path, monkeypatch):
    cfg_path, ck = _seed_db(tmp_path)
    monkeypatch.setenv("CLOUD_READONLY", "1")
    client = TestClient(create_app(str(cfg_path)))

    # 읽기는 ro 엔진으로 정상 (init_db 를 건너뛰어도 시드된 스키마/데이터를 그대로 읽음)
    assert client.get("/api/listings").status_code == 200
    assert "테스트단지" in {c["name"] for c in client.get("/api/listings").json()["complexes"]}
    assert client.get("/api/me").json()["readonly"] is True
    assert client.get("/healthz").status_code == 200  # 헬스체크는 차단 안 됨

    # 모든 쓰기/수집 트리거는 403 (라우트 진입 전 미들웨어에서)
    assert client.post("/run").status_code == 403
    assert client.post("/run-deals").status_code == 403
    assert client.post("/run-auctions").status_code == 403
    assert client.post("/complexes/111/star").status_code == 403
    assert client.post("/complexes/add", data={"complex_no": "222"}).status_code == 403
    assert client.post(f"/curation/{ck}/memo", data={"memo": "x"}).status_code == 403


def test_readonly_engine_rejects_direct_write(tmp_path, monkeypatch):
    """방어선 — 미들웨어를 우회해도 ro 엔진 자체가 쓰기를 거부한다."""
    cfg_path, _ = _seed_db(tmp_path)
    monkeypatch.setenv("CLOUD_READONLY", "1")
    app = create_app(str(cfg_path))
    with app.state.engine.connect() as c, pytest.raises(OperationalError):
        c.exec_driver_sql("CREATE TABLE _should_fail(x)")


def test_not_readonly_by_default(tmp_path):
    """CLOUD_READONLY 미설정이면 쓰기 가능(기존 동작)."""
    cfg_path, _ = _seed_db(tmp_path)
    client = TestClient(create_app(str(cfg_path)))
    assert client.get("/api/me").json()["readonly"] is False
    assert client.post("/complexes/111/star").status_code == 200
