"""급매 대시보드 스모크 — /api/flash JSON·필터·/flash 리다이렉트."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from myhouse.constants import ListingStatus, TradeType, now_kst, to_iso
from myhouse.db.engine import get_session, init_db, make_engine, set_meta
from myhouse.db.models import Complex, FlashDeal, Listing
from myhouse.web.app import create_app


def _seed(tmp_path):
    db = tmp_path / "flash_web.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "app": {"db_path": str(db), "request_delay_seconds": [0, 0]},
                "defaults": {"trade_types": ["SALE"]},
                "targets": [{"kind": "complex", "complex_no": "947", "label": "삼호1차"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    engine = make_engine(db)
    init_db(engine)
    now = to_iso(now_kst())
    with get_session(engine) as s:
        s.add(Complex(complex_no="947", name="삼호1차", address="서울시 서초구 방배동",
                      first_seen_at=now, updated_at=now))
        # 살아있는 급매(신규) 매물 + 빠진 급매(거래완료) 매물
        s.add(Listing(article_no="A1", complex_no="947", trade_type=TradeType.SALE,
                      price_deal=110000, area_excl=81.39, floor_info="10/15",
                      status=ListingStatus.ACTIVE,
                      article_url="https://m.land.naver.com/article/info/A1"))
        s.add(Listing(article_no="A2", complex_no="947", trade_type=TradeType.SALE,
                      price_deal=105000, area_excl=81.39, status=ListingStatus.REMOVED))
        s.commit()  # 부모(단지·매물) 먼저 커밋 — flash_deal.article_no FK 보장
        s.add(FlashDeal(article_no="A1", complex_no="947", trade_type=TradeType.SALE,
                        area_excl=81.39, area_key=81, price_deal=110000, prior_floor=120000,
                        drop_amount=10000, drop_pct=8.33, trigger="new",
                        detected_at=now, detected_run_id=42))
        s.add(FlashDeal(article_no="A2", complex_no="947", trade_type=TradeType.SALE,
                        area_excl=81.39, area_key=81, price_deal=105000, prior_floor=120000,
                        drop_amount=15000, drop_pct=12.5, trigger="price_drop",
                        detected_at=now, detected_run_id=42))
        set_meta(s, "last_successful_run_id", "42")
        s.commit()
    return cfg_path


def test_api_flash_basic(tmp_path):
    client = TestClient(create_app(str(_seed(tmp_path))))
    data = client.get("/api/flash").json()
    # 기본은 ACTIVE 급매만 → A1 한 건
    assert data["total"] == 1
    row = data["rows"][0]
    assert row["article_no"] == "A1"
    assert row["complex_name"] == "삼호1차"
    assert row["prior_floor"] == 120000
    assert row["drop_amount"] == 10000
    assert row["drop_pct"] == 8.33
    assert row["trigger_ko"] == "신규"
    assert row["is_new"] is True  # detected_run_id == last_successful_run_id
    assert data["new_count"] == 1
    assert {c["complex_no"] for c in data["complexes"]} == {"947"}
    assert "서초구" in data["gu_dong_map"]


def test_api_flash_include_inactive(tmp_path):
    client = TestClient(create_app(str(_seed(tmp_path))))
    assert client.get("/api/flash").json()["total"] == 1
    # 빠진 매물 포함 → A1 + A2
    both = client.get("/api/flash?include_inactive=true").json()
    assert both["total"] == 2


def test_api_flash_filters(tmp_path):
    client = TestClient(create_app(str(_seed(tmp_path))))
    # trigger 필터: 살아있는 것 중 price_drop 은 없음(A2 는 빠짐)
    assert client.get("/api/flash?trigger=price_drop").json()["total"] == 0
    assert client.get("/api/flash?trigger=new").json()["total"] == 1
    # include_inactive 와 결합하면 price_drop(A2) 노출
    assert client.get("/api/flash?trigger=price_drop&include_inactive=true").json()["total"] == 1
    for qs in [
        "?days=7", "?days=90", "?trade_type=SALE", "?complex_no=947",
        "?gu=서초구", "?q=삼호", "?sort=drop_amount_desc", "?sort=detected_desc",
        "?sort=price_asc",
    ]:
        assert client.get("/api/flash" + qs).status_code == 200


def test_flash_route_redirects_to_spa(tmp_path):
    client = TestClient(create_app(str(_seed(tmp_path))))
    r = client.get("/flash", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/app/flash"
