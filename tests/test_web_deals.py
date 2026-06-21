"""실거래 대시보드 스모크 — /deals 라우트·필터·단지상세 섹션."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from myhouse.constants import TradeType, now_kst, to_iso
from myhouse.db.engine import get_session, init_db, make_engine, set_meta
from myhouse.db.models import Complex, Deal
from myhouse.web.app import create_app


def _seed(tmp_path):
    db = tmp_path / "deals_web.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "app": {"db_path": str(db), "request_delay_seconds": [0, 0]},
                "defaults": {"trade_types": ["SALE"]},
                "deals": {"enabled": True},
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
        s.add(
            Complex(
                complex_no="947",
                name="삼호1차",
                address="서울시 서초구 방배동",
                first_seen_at=now,
                updated_at=now,
            )
        )
        s.add(
            Deal(
                deal_key="d1",
                complex_no="947",
                trade_type=TradeType.SALE,
                deal_date="2026-05-23",
                price_deal=225000,
                floor=10,
                pyeong_no="1",
                pyeong_name="82A",
                area_excl=81.39,
                first_seen_at=now,
                first_seen_run_id=42,
                last_seen_at=now,
            )
        )
        s.add(
            Deal(
                deal_key="d2",
                complex_no="947",
                trade_type=TradeType.SALE,
                deal_date="2024-12-04",
                price_deal=170000,
                floor=10,
                pyeong_no="1",
                pyeong_name="82A",
                area_excl=81.39,
                cancelled=True,
                first_seen_at=now,
                first_seen_run_id=42,
                last_seen_at=now,
                cancel_seen_at=now,
            )
        )
        set_meta(s, "last_deal_run_id", "42")
        s.commit()
    return cfg_path


def test_deals_page_smoke(tmp_path):
    cfg_path = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))

    r = client.get("/deals?months=36")
    assert r.status_code == 200
    assert "삼호1차" in r.text
    assert "82A" in r.text
    assert "신규" in r.text  # first_seen_run_id == last_deal_run_id

    # 기본은 취소 제외 → 취소 거래(2024-12-04)는 안 보임
    assert "2024-12-04" not in r.text
    # 취소포함 시 등장
    r_cancel = client.get("/deals?months=36&include_cancelled=on")
    assert "2024-12-04" in r_cancel.text


def test_deals_filters_smoke(tmp_path):
    cfg_path = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))
    for qs in [
        "?months=3",
        "?months=36&sort=price_desc",
        "?sort=price_asc",
        "?trade_type=SALE",
        "?complex_no=947",
        "?gu=서초구",
        "?area_min=80&area_max=82",
        "?q=삼호",
        "?include_cancelled=on",
    ]:
        assert client.get("/deals" + qs).status_code == 200


def test_complex_detail_has_deal_section(tmp_path):
    cfg_path = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))
    r = client.get("/complex/947")
    assert r.status_code == 200
    assert "실거래가" in r.text
    assert "82A" in r.text
