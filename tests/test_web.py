"""대시보드 스모크 — TestClient 로 주요 라우트/큐레이션 점검."""

from __future__ import annotations

from datetime import timedelta

import yaml
from fastapi.testclient import TestClient
from sqlmodel import select
from tests.conftest import make_dto

from myhouse.constants import TradeType, now_kst, to_iso
from myhouse.core.collector import run_collection
from myhouse.db import repo
from myhouse.db.engine import get_session, init_db, make_engine
from myhouse.db.models import Deal, Listing
from myhouse.naver.client import FetchResult
from myhouse.settings import Settings, load_config
from myhouse.web.app import create_app


class FakeClient:
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
    db = tmp_path / "web.db"
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
            make_dto("1", price_deal=158000),
            make_dto("2", price_deal=159000),  # 같은 유닛 다른 중개사
            make_dto("3", floor_num=5, price_deal=210000),
        ],
        complete=True,
        raw_count=3,
    )
    run_collection(cfg, Settings(), engine, client=FakeClient([fr]))
    return db, cfg_path, engine


def test_dashboard_smoke(tmp_path):
    db, cfg_path, engine = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))

    # 모든 페이지가 SPA 셸(/)을 공유한다 — 데이터는 JSON API 로 검증한다.
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="root"' in r.text  # React 마운트 포인트
    assert "테스트단지" in {c["name"] for c in client.get("/api/listings").json()["complexes"]}

    # SPA 라우트는 셸(200)을 그대로 반환한다(클라이언트 라우팅).
    assert client.get("/shortlist").status_code == 200
    assert client.get("/runs").status_code == 200
    assert client.get("/complex/111").status_code == 200

    with get_session(engine) as s:
        ck = s.exec(select(Listing)).first().cluster_key

    # 관심(별표)은 단지 단위 — 단지 토글 시 관심 단지 목록(/api/shortlist)에 반영된다.
    r = client.post("/complexes/111/star")
    assert r.status_code == 200 and r.json()["starred"] is True
    assert "테스트단지" in {row["name"] for row in client.get("/api/shortlist").json()["rows"]}
    assert client.get("/api/listings?starred_only=on").status_code == 200

    # 메모/제외는 여전히 매물(cluster) 단위.
    r = client.post(f"/curation/{ck}/memo", data={"memo": "남향 좋음"})
    assert r.status_code == 200 and r.json()["memo"] == "남향 좋음"
    assert client.get(f"/api/listing/{ck}/history").status_code == 200

    # 관심 해제 시 관심 단지 목록에서 빠진다.
    r = client.post("/complexes/111/star")
    assert r.status_code == 200 and r.json()["starred"] is False
    assert "테스트단지" not in {row["name"] for row in client.get("/api/shortlist").json()["rows"]}


def test_complex_detail_shows_meta(tmp_path):
    """단지 메타가 채워지면 단지상세 API(stat.meta_line)에 한 줄 요약으로 실린다."""
    db, cfg_path, engine = _seed(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(
            s,
            "111",
            total_households=419,
            total_dong_count=3,
            use_approve_ymd="19751128",
            floor_area_ratio=238,
            building_coverage_ratio=23,
        )
    client = TestClient(create_app(str(cfg_path)))
    assert client.get("/complex/111").status_code == 200  # SPA 셸 로드
    meta = client.get("/api/complex/111").json()["stat"]["meta_line"]
    assert "419세대(3개동)" in meta
    assert "1975.11 준공" in meta
    assert "용적률 238%" in meta
    assert "건폐율 23%" in meta


def test_complex_detail_omits_meta_when_absent(tmp_path):
    """메타가 없으면(신규/미백필 단지) stat.meta_line 이 None 이다."""
    db, cfg_path, engine = _seed(tmp_path)  # _seed 는 메타를 채우지 않는다
    stat = TestClient(create_app(str(cfg_path))).get("/api/complex/111").json()["stat"]
    assert stat["meta_line"] is None


def _days_ago(n: int) -> str:
    """현재(KST) 기준 n일 전 'YYYY-MM-DD' — 시간 의존 로직 테스트용."""
    return (now_kst() - timedelta(days=n)).date().isoformat()


def test_area_group_deal_price_recent_range(tmp_path):
    """최근 1개월 실거래가 있으면 가격 범위(min~max)로 노출 (취소·과거 거래 제외)."""
    db, cfg_path, engine = _seed(tmp_path)
    now = to_iso(now_kst())
    with get_session(engine) as s:
        # 매물 면적(81.0)과 같은 평형(round 81)·같은 거래유형(SALE)
        s.add(Deal(  # 최근 — 범위 하한
            deal_key="r1", complex_no="111", trade_type=TradeType.SALE,
            deal_date=_days_ago(5), price_deal=200000, floor=8,
            area_excl=81.39, first_seen_at=now, last_seen_at=now,
        ))
        s.add(Deal(  # 최근 — 범위 상한
            deal_key="r2", complex_no="111", trade_type=TradeType.SALE,
            deal_date=_days_ago(15), price_deal=230000, floor=12,
            area_excl=81.39, first_seen_at=now, last_seen_at=now,
        ))
        s.add(Deal(  # 1개월 이전 — 범위에서 제외
            deal_key="old", complex_no="111", trade_type=TradeType.SALE,
            deal_date=_days_ago(120), price_deal=130000, floor=3,
            area_excl=81.39, first_seen_at=now, last_seen_at=now,
        ))
        s.add(Deal(  # 최근이지만 취소 — 제외
            deal_key="cancel", complex_no="111", trade_type=TradeType.SALE,
            deal_date=_days_ago(3), price_deal=999000, floor=9,
            area_excl=81.39, cancelled=True, first_seen_at=now, last_seen_at=now,
        ))
        s.commit()

    client = TestClient(create_app(str(cfg_path)))
    rows = client.get("/api/listings").json()["rows"]
    row = next(r for r in rows if r["complex_no"] == "111")
    # 최근 1개월 범위(200000~230000) — 1개월 이전(130000)·취소(999000)는 제외
    assert (row["deal_price_min"], row["deal_price_max"]) == (200000, 230000)
    assert row["deal_is_recent"] is True


def test_area_group_deal_price_fallback_when_no_recent(tmp_path):
    """최근 1개월 실거래가 없으면 과거 최근 1건으로 폴백 (거래월 함께 표시)."""
    db, cfg_path, engine = _seed(tmp_path)
    now = to_iso(now_kst())
    fallback_date = _days_ago(100)
    with get_session(engine) as s:
        s.add(Deal(  # 가장 최근(폴백 대상)
            deal_key="f1", complex_no="111", trade_type=TradeType.SALE,
            deal_date=fallback_date, price_deal=201000, floor=8,
            area_excl=81.39, first_seen_at=now, last_seen_at=now,
        ))
        s.add(Deal(  # 더 오래된 거래 — 가려짐
            deal_key="f2", complex_no="111", trade_type=TradeType.SALE,
            deal_date=_days_ago(300), price_deal=130000, floor=3,
            area_excl=81.39, first_seen_at=now, last_seen_at=now,
        ))
        s.commit()

    client = TestClient(create_app(str(cfg_path)))
    rows = client.get("/api/listings").json()["rows"]
    row = next(r for r in rows if r["complex_no"] == "111")
    # 최근 1개월 거래 없음 → 과거 최근 1건(201000)으로 폴백, 더 오래된 130000 은 가려짐
    assert (row["deal_price_min"], row["deal_price_max"]) == (201000, 201000)
    assert row["deal_is_recent"] is False
    assert row["deal_date"] == fallback_date


def test_area_group_deal_price_floor_match(tmp_path):
    """네이버 매물 면적(버림 정수 81)과 실거래 정밀소수(81.97)가 같은 평형으로 매칭.

    81.97 은 round 면 82 로 어긋나지만 floor(버림)면 81 로 매물과 맞물린다.
    """
    db, cfg_path, engine = _seed(tmp_path)  # 매물 전용면적 81.0 (단지 111)
    now = to_iso(now_kst())
    with get_session(engine) as s:
        s.add(Deal(
            deal_key="floor1", complex_no="111", trade_type=TradeType.SALE,
            deal_date=_days_ago(7), price_deal=205000, floor=8,
            area_excl=81.97, first_seen_at=now, last_seen_at=now,
        ))
        s.commit()

    client = TestClient(create_app(str(cfg_path)))
    rows = client.get("/api/listings").json()["rows"]
    row = next(r for r in rows if r["complex_no"] == "111")
    assert row["deal_price_min"] == 205000  # 81.97 실거래가 81평형 매물 행에 매핑됨
    assert row["deal_is_recent"] is True


def test_floor_min_filter_uses_band_estimate(tmp_path):
    """'저/중/고' 밴드 매물은 총층 3등분 추정층으로 '최소 층' 필터에 노출된다."""
    from myhouse.web.queries import Filters, build_cluster_rows

    db = tmp_path / "band.db"
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
    # 15층 단지: 고=11~15(추정13) · 저=1~5(추정3) · 숫자 12층
    fr = FetchResult(
        "111",
        [
            make_dto("hi", area_name="82A", floor_num=None, floor_info="고/15"),
            make_dto("lo", area_name="84B", floor_num=None, floor_info="저/15"),
            make_dto("num", area_name="59C", floor_num=12, price_deal=200000),
        ],
        complete=True,
        raw_count=3,
    )
    run_collection(cfg, Settings(), engine, client=FakeClient([fr]))

    with get_session(engine) as session:
        # floor_min=10: 고(13)·숫자(12) 통과, 저(3) 탈락
        rows = build_cluster_rows(session, Filters(floor_min=10), None)
        urls = {r.article_url.rsplit("/", 1)[-1] for r in rows}
        assert "hi" in urls and "num" in urls and "lo" not in urls
        # floor_min=14: 추정 13인 고도 탈락(추정의 한계), 숫자 12도 탈락
        rows = build_cluster_rows(session, Filters(floor_min=14), None)
        assert rows == []
        # 필터 없으면 셋 다 노출
        rows = build_cluster_rows(session, Filters(), None)
        assert len(rows) == 3


def test_filters_smoke(tmp_path):
    db, cfg_path, engine = _seed(tmp_path)
    client = TestClient(create_app(str(cfg_path)))
    # 다양한 필터 조합이 500 없이 동작 (SPA 가 소비하는 /api/listings)
    for qs in [
        "?trade_type=SALE",
        "?status=new",
        "?status=removed",
        "?price_min=100000&price_max=200000",
        "?area_min=50&area_max=70",
        "?floor_min=10",
        "?sort=price_asc",
        "?q=테스트",
        "?complex_no=111",
    ]:
        assert client.get("/api/listings" + qs).status_code == 200
