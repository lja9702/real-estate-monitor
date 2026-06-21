"""JSON API 엔드포인트 스모크 — /api/listings, /api/filter-domains, /api/listing/.../history"""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient
from sqlmodel import select
from tests.conftest import make_dto

from myhouse.constants import TradeType
from myhouse.core.collector import run_collection
from myhouse.db import repo
from myhouse.db.engine import get_session, init_db, make_engine
from myhouse.db.models import Complex, Listing
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


def _seed(tmp_path):
    db = tmp_path / "api_test.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "app": {"db_path": str(db), "request_delay_seconds": [0, 0]},
                "defaults": {"trade_types": ["SALE"]},
                "targets": [
                    {
                        "kind": "complex",
                        "complex_no": "111",
                        "label": "테스트단지",
                        "lat": 37.0,
                        "lon": 127.0,
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    engine = make_engine(db)
    init_db(engine)
    fr = FetchResult(
        "111",
        [
            make_dto("1", price_deal=158000, floor_num=12),
            make_dto("2", price_deal=159000, floor_num=12),  # 같은 cluster
            make_dto("3", floor_num=5, price_deal=210000),
        ],
        complete=True,
        raw_count=3,
    )
    run_collection(cfg, Settings(), engine, client=_FakeClient([fr]))
    return db, cfg_path, engine


def test_api_listings_structure(tmp_path):
    """/api/listings → 200, 필수 키 존재, rows 비어있지 않음."""
    _, cfg_path, _ = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))

    r = client.get("/api/listings")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"rows", "total", "new_count", "complexes", "gu_dong_map"}
    assert data["total"] == len(data["rows"])
    assert data["total"] > 0


def test_api_listings_extreme_filter_returns_empty(tmp_path):
    """/api/listings?price_min=극단값 → rows 빈 배열."""
    _, cfg_path, _ = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))

    r = client.get("/api/listings?price_min=99999999")
    assert r.status_code == 200
    data = r.json()
    assert data["rows"] == []
    assert data["total"] == 0


def test_api_filter_domains_shape(tmp_path):
    """/api/filter-domains → 200, min<=max 불변식."""
    _, cfg_path, _ = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))

    r = client.get("/api/filter-domains")
    assert r.status_code == 200
    d = r.json()
    assert d["price_min"] <= d["price_max"]
    assert d["area_min"] <= d["area_max"]
    assert d["households_min"] <= d["households_max"]
    assert d["year_min"] <= d["year_max"]
    assert d["floor_max"] >= 1


def test_api_filter_domains_empty_db(tmp_path):
    """/api/filter-domains → 빈 DB에서도 기본값으로 200 반환."""
    db = tmp_path / "empty.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "app": {"db_path": str(db), "request_delay_seconds": [0, 0]},
                "defaults": {"trade_types": ["SALE"]},
                "targets": [],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(str(cfg_path)))
    r = client.get("/api/filter-domains")
    assert r.status_code == 200
    d = r.json()
    assert d["price_min"] <= d["price_max"]


def test_api_listing_history(tmp_path):
    """/api/listing/{cluster_key}/history → 200, points/spark 키 존재."""
    _, cfg_path, engine = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))

    with get_session(engine) as s:
        ck = s.exec(select(Listing)).first().cluster_key

    r = client.get(f"/api/listing/{ck}/history")
    assert r.status_code == 200
    data = r.json()
    assert "points" in data
    assert "spark" in data


def test_api_listing_history_unknown_key(tmp_path):
    """/api/listing/{없는key}/history → 200, points 빈 배열."""
    _, cfg_path, _ = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))

    r = client.get("/api/listing/nonexistent_key/history")
    assert r.status_code == 200
    assert r.json()["points"] == []
