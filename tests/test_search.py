"""주소/단지명 역추적(검색) — 응답 파싱, seed 선택, 봇 /add 검색 분기, 응답 포매팅."""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

from myhouse.bot.commands import BotContext, handle_text
from myhouse.constants import SOURCE_TELEGRAM, RunStatus, now_kst
from myhouse.core import on_demand
from myhouse.core.collector import ComplexResult, RunResult
from myhouse.core.diff import ComplexDiff
from myhouse.core.on_demand import AddResult, search_address
from myhouse.db import repo
from myhouse.db.engine import get_session
from myhouse.naver.search_parser import SearchHit, parse_search
from myhouse.notify import reply
from myhouse.settings import AppConfig, Config, Settings, TargetSpec

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _config(tmp_path, targets=None) -> Config:
    return Config(
        app=AppConfig(db_path=str(tmp_path / "myhouse.db")),
        targets=targets if targets is not None else [TargetSpec(kind="complex", complex_no="111")],
    )


class _FakeClient:
    def __init__(self, hits):
        self.hits = hits
        self.seed = None
        self.kw = None

    def search_complexes(self, keyword, *, seed_complex_no):
        self.kw = keyword
        self.seed = seed_complex_no
        return self.hits


class _DummyCM:
    def __init__(self, client):
        self.client = client

    def __enter__(self):
        return self.client

    def __exit__(self, *a):
        return False


# ── parse_search ─────────────────────────────────────────────────────────────
def test_parse_search_real_shape():
    payload = json.loads((FIXTURES / "search_results.json").read_text(encoding="utf-8"))
    hits = parse_search(payload)
    # 번호 없는 항목은 스킵 → 2건
    assert [h.complex_no for h in hits] == ["947", "12345"]
    h = hits[0]
    assert h.name == "삼호1차"
    assert h.address == "서울시 서초구 방배동"
    assert h.cortar_no == "1165010100"
    assert h.type_name == "재건축"
    assert h.households == 419
    assert abs(h.lat - 37.495335) < 1e-6 and abs(h.lon - 126.987687) < 1e-6


def test_parse_search_missing_or_bad():
    assert parse_search({}) == []
    assert parse_search({"complexes": None}) == []
    assert parse_search([]) == []  # dict 아님
    assert parse_search({"complexes": [{"complexName": "이름만"}]}) == []  # 번호 없음 스킵


# ── seed 선택 + search_address ────────────────────────────────────────────────
def test_seed_prefers_config_target(tmp_path, engine):
    cfg = _config(tmp_path)  # config target 111
    assert on_demand._seed_complex_no(cfg, engine) == "111"


def test_seed_falls_back_to_db_then_constant(tmp_path, engine):
    cfg = _config(tmp_path, targets=[])
    assert on_demand._seed_complex_no(cfg, engine) == "947"  # 비어있으면 기준 단지
    with get_session(engine) as s:
        repo.upsert_complex(s, "555", name="활성", source=SOURCE_TELEGRAM, is_active=True)
    assert on_demand._seed_complex_no(cfg, engine) == "555"  # 활성 DB 단지


def test_search_address_passes_seed_and_returns_hits(tmp_path, engine):
    cfg = _config(tmp_path)
    hits = [SearchHit(complex_no="947", name="삼호1차")]
    client = _FakeClient(hits)
    out = search_address(cfg, engine, client, "방배삼호")
    assert out == hits
    assert client.kw == "방배삼호"
    assert client.seed == "111"  # config target seed


def test_search_address_empty_keyword(tmp_path, engine):
    cfg = _config(tmp_path)
    client = _FakeClient([SearchHit(complex_no="1", name="x")])
    assert search_address(cfg, engine, client, "   ") == []


# ── 응답 포매팅 ───────────────────────────────────────────────────────────────
def test_format_add_candidates():
    hits = [
        SearchHit(
            complex_no="947",
            name="삼호1차",
            address="서울시 서초구 방배동",
            type_name="재건축",
            households=419,
        ),
        SearchHit(complex_no="12345", name="방배삼호2차", address="서울시 서초구 방배동"),
    ]
    msg = reply.format_add_candidates("방배삼호", hits)
    assert "삼호1차" in msg and "<code>947</code>" in msg
    assert "방배동" in msg and "419세대" in msg
    assert "/add" in msg


def test_format_add_not_found():
    assert "찾지 못" in reply.format_add_not_found("없는주소")


# ── 봇 /add 검색 분기 ─────────────────────────────────────────────────────────
def _ctx(engine, tmp_path, client):
    return BotContext(
        config=_config(tmp_path),
        settings=Settings(),
        engine=engine,
        open_client=lambda: _DummyCM(client),
    )


def _canned_add(no="947", name="삼호1차"):
    cdiff = ComplexDiff(no, True, [])
    fetch = SimpleNamespace(complete=True, raw_count=0)
    cr = ComplexResult(no, name, name, address=None, diff=cdiff, fetch=fetch)
    run = RunResult(run_id=1, started_at=now_kst(), status=RunStatus.SUCCESS, complexes=[cr])
    return AddResult(no, name, name_resolved=True, run=run)


def test_add_by_address_no_match(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(on_demand, "search_address", lambda *a, **k: [])
    msg = handle_text("/add 없는주소", _ctx(engine, tmp_path, _FakeClient([])))
    assert "찾지 못" in msg


def test_add_by_address_multiple_candidates(engine, tmp_path, monkeypatch):
    hits = [
        SearchHit(complex_no="947", name="삼호1차"),
        SearchHit(complex_no="12345", name="삼호2차"),
    ]
    monkeypatch.setattr(on_demand, "search_address", lambda *a, **k: hits)
    msg = handle_text("/add 방배 삼호", _ctx(engine, tmp_path, _FakeClient(hits)))
    assert "여러 단지" in msg and "<code>947</code>" in msg and "<code>12345</code>" in msg


def test_add_by_address_unique_adds(engine, tmp_path, monkeypatch):
    hit = SearchHit(complex_no="947", name="삼호1차")
    monkeypatch.setattr(on_demand, "search_address", lambda *a, **k: [hit])
    monkeypatch.setattr(on_demand, "add_complex", lambda *a, **k: _canned_add())
    monkeypatch.setattr("myhouse.bot.commands.build_cluster_rows", lambda *a, **k: [])
    msg = handle_text("/add 방배삼호1차", _ctx(engine, tmp_path, _FakeClient([hit])))
    assert "추적 시작" in msg and "삼호1차" in msg


def test_add_numeric_still_works(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(on_demand, "add_complex", lambda *a, **k: _canned_add("1234", "수동단지"))
    monkeypatch.setattr("myhouse.bot.commands.build_cluster_rows", lambda *a, **k: [])
    msg = handle_text("/add 1234 수동단지", _ctx(engine, tmp_path, _FakeClient([])))
    assert "추적 시작" in msg and "수동단지" in msg


# ── /deals · /check 가 로컬 실패 시 라이브 검색으로 역추적 ─────────────────────
def _canned_deal_run(no="947", name="삼호1차"):
    from myhouse.core.deal_collector import ComplexDealResult, DealRunResult

    cr = ComplexDealResult(no, name, name, new_deals=[], cancelled_deals=[])
    return DealRunResult(run_id=1, started_at=now_kst(), status=RunStatus.SUCCESS, complexes=[cr])


def test_deals_by_address_searches_when_local_miss(engine, tmp_path, monkeypatch):
    hit = SearchHit(complex_no="947", name="삼호1차")
    monkeypatch.setattr(on_demand, "search_address", lambda *a, **k: [hit])
    monkeypatch.setattr(on_demand, "check_deals", lambda *a, **k: _canned_deal_run())
    monkeypatch.setattr("myhouse.bot.commands.recent_deals_for_complex", lambda *a, **k: [])
    msg = handle_text("/deals 방배삼호1차", _ctx(engine, tmp_path, _FakeClient([hit])))
    assert "실거래" in msg and "삼호1차" in msg


def test_deals_by_address_multiple_candidates(engine, tmp_path, monkeypatch):
    hits = [
        SearchHit(complex_no="947", name="삼호1차"),
        SearchHit(complex_no="468", name="삼호2차"),
    ]
    monkeypatch.setattr(on_demand, "search_address", lambda *a, **k: hits)
    msg = handle_text("/deals 방배삼호", _ctx(engine, tmp_path, _FakeClient(hits)))
    assert "여러 단지" in msg and "/deals" in msg
    assert "<code>947</code>" in msg and "<code>468</code>" in msg


def test_deals_local_hit_skips_live_search(engine, tmp_path, monkeypatch):
    with get_session(engine) as s:
        repo.upsert_complex(s, "200", name="도곡렉슬", source=SOURCE_TELEGRAM, is_active=True)
    called = {"search": False}

    def _search(*a, **k):
        called["search"] = True
        return []

    monkeypatch.setattr(on_demand, "search_address", _search)
    monkeypatch.setattr(
        on_demand, "check_deals", lambda *a, **k: _canned_deal_run("200", "도곡렉슬")
    )
    monkeypatch.setattr("myhouse.bot.commands.recent_deals_for_complex", lambda *a, **k: [])
    msg = handle_text("/deals 도곡렉슬", _ctx(engine, tmp_path, _FakeClient([])))
    assert "도곡렉슬" in msg
    assert called["search"] is False  # 로컬에서 찾으면 라이브 검색 생략


def test_check_by_address_searches_when_local_miss(engine, tmp_path, monkeypatch):
    hit = SearchHit(complex_no="947", name="삼호1차")
    monkeypatch.setattr(on_demand, "search_address", lambda *a, **k: [hit])
    monkeypatch.setattr(on_demand, "check_complex", lambda *a, **k: _canned_add().run)
    monkeypatch.setattr(on_demand, "is_tracked", lambda *a, **k: False)
    monkeypatch.setattr("myhouse.bot.commands.build_cluster_rows", lambda *a, **k: [])
    msg = handle_text("/check 방배삼호1차", _ctx(engine, tmp_path, _FakeClient([hit])))
    assert "삼호1차" in msg and "/complex/947" in msg
