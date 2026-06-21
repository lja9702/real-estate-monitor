"""온디맨드 해석/추적 로직 — 이름·번호 해석, 추적 단지의 정기 수집 병합."""

from __future__ import annotations

import json

from sqlmodel import select

from myhouse.constants import SOURCE_ADHOC, SOURCE_PINNED, SOURCE_TELEGRAM, SOURCE_WEB
from myhouse.core import on_demand
from myhouse.core.targets import resolve_one, resolve_targets
from myhouse.db import repo
from myhouse.db.engine import get_session
from myhouse.db.models import Complex
from myhouse.settings import AppConfig, Config, TargetSpec


def _config(tmp_path, targets=None) -> Config:
    return Config(
        app=AppConfig(db_path=str(tmp_path / "myhouse.db")),
        targets=targets or [TargetSpec(kind="complex", complex_no="111", label="가나단지")],
    )


# ── resolve_one: 추적 의미론 ──────────────────────────────────────────────────
def test_resolve_one_track_new_complex_is_telegram(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        rt = resolve_one(cfg, s, "947", track=True, name="삼호1차")
        assert rt.complex.complex_no == "947"
    cx = _get(engine, "947")
    assert cx.source == SOURCE_TELEGRAM
    assert cx.is_active is True
    assert cx.name == "삼호1차"


def test_resolve_one_track_config_complex_stays_pinned(tmp_path, engine):
    cfg = _config(tmp_path)  # 111 은 config 타겟
    with get_session(engine) as s:
        resolve_one(cfg, s, "111", track=True)
    cx = _get(engine, "111")
    assert cx.source == SOURCE_PINNED
    assert cx.is_active is True


def test_resolve_one_untracked_is_adhoc_inactive(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        resolve_one(cfg, s, "555", track=False)
    cx = _get(engine, "555")
    assert cx.source == SOURCE_ADHOC
    assert cx.is_active is False  # 정기 수집 제외


def test_resolve_one_untracked_keeps_existing_tracking(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(s, "777", name="이미추적", source=SOURCE_TELEGRAM, is_active=True)
    with get_session(engine) as s:
        resolve_one(cfg, s, "777", track=False)  # /check 가 추적 상태를 끄면 안 됨
    cx = _get(engine, "777")
    assert cx.source == SOURCE_TELEGRAM
    assert cx.is_active is True


# ── resolve_targets: 텔레그램 추적 단지 병합 ─────────────────────────────────
def test_resolve_targets_merges_active_telegram_complexes(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(s, "947", name="삼호1차", source=SOURCE_TELEGRAM, is_active=True)
        repo.upsert_complex(s, "555", name="미리보기", source=SOURCE_ADHOC, is_active=False)
        repo.upsert_complex(s, "888", name="비활성", source=SOURCE_TELEGRAM, is_active=False)
    with get_session(engine) as s:
        nos = {rt.complex.complex_no for rt in resolve_targets(cfg, s, client=None)}
    assert "111" in nos  # config 고정
    assert "947" in nos  # 텔레그램 추적 → 병합
    assert "555" not in nos  # adhoc 미추적 제외
    assert "888" not in nos  # 비활성 제외


def test_resolve_targets_no_duplicate_when_in_config(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(s, "111", name="가나단지", source=SOURCE_TELEGRAM, is_active=True)
    with get_session(engine) as s:
        nos = [rt.complex.complex_no for rt in resolve_targets(cfg, s, client=None)]
    assert nos.count("111") == 1


def test_resolve_targets_skips_untracked_config_complex(tmp_path, engine):
    cfg = _config(tmp_path)  # 111 = config 고정 타겟
    with get_session(engine) as s:
        repo.upsert_complex(s, "111", name="가나단지", source=SOURCE_PINNED, is_active=False)
    with get_session(engine) as s:
        nos = {rt.complex.complex_no for rt in resolve_targets(cfg, s, client=None)}
    assert "111" not in nos  # config 고정이라도 추적 해제(is_active=False)면 정기 수집 제외


def test_resolve_targets_merges_active_web_complexes(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(s, "947", name="삼호1차", source=SOURCE_WEB, is_active=True)
    with get_session(engine) as s:
        nos = {rt.complex.complex_no for rt in resolve_targets(cfg, s, client=None)}
    assert "947" in nos  # 대시보드에서 추가(web)한 추적 단지도 병합


# ── track_complex / untrack_complex: 대시보드 추적 토글 ───────────────────────
def test_track_complex_new_is_web_active(tmp_path, engine):
    cfg = _config(tmp_path)
    cx = on_demand.track_complex(cfg, engine, "947", alias="삼호1차")
    assert cx.is_active is True
    assert cx.source == SOURCE_WEB
    assert cx.name == "삼호1차"


def test_track_complex_config_stays_pinned(tmp_path, engine):
    cfg = _config(tmp_path)  # 111 = config
    cx = on_demand.track_complex(cfg, engine, "111")
    assert cx.source == SOURCE_PINNED and cx.is_active is True


def test_untrack_then_retrack_preserves_source(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(s, "777", name="텔레단지", source=SOURCE_TELEGRAM, is_active=True)
    assert on_demand.untrack_complex(engine, "777") is True
    assert _get(engine, "777").is_active is False
    cx = on_demand.track_complex(cfg, engine, "777")  # 다시 추적
    assert cx.is_active is True
    assert cx.source == SOURCE_TELEGRAM  # 출처 보존(web 으로 덮어쓰지 않음)


def test_untrack_missing_complex_returns_false(tmp_path, engine):
    assert on_demand.untrack_complex(engine, "404404") is False


# ── resolve_query: 번호/이름 해석 ────────────────────────────────────────────
def test_resolve_query_number(tmp_path, engine):
    cfg = _config(tmp_path)
    res = on_demand.resolve_query(cfg, engine, "947")
    assert res.found and res.complex_no == "947" and res.is_number


def test_resolve_query_unique_name(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(s, "200", name="도곡렉슬")
    res = on_demand.resolve_query(cfg, engine, "렉슬")
    assert res.found and res.complex_no == "200"


def test_resolve_query_ambiguous_lists_candidates(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(s, "1", name="우성1차")
        repo.upsert_complex(s, "2", name="우성2차")
    res = on_demand.resolve_query(cfg, engine, "우성")
    assert not res.found
    assert {c.complex_no for c in res.candidates} == {"1", "2"}


def test_resolve_query_not_found(tmp_path, engine):
    cfg = _config(tmp_path)
    res = on_demand.resolve_query(cfg, engine, "없는단지명")
    assert not res.found and not res.candidates


def test_resolve_query_config_label(tmp_path, engine):
    cfg = _config(tmp_path)  # 111=가나단지 (DB 에 아직 없음)
    res = on_demand.resolve_query(cfg, engine, "가나")
    assert res.found and res.complex_no == "111"


# ── resolve_name: 우선순위 ───────────────────────────────────────────────────
def test_resolve_name_alias_wins(tmp_path, engine):
    cfg = _config(tmp_path)
    assert on_demand.resolve_name(cfg, engine, "947", "내별칭", None) == "내별칭"


def test_resolve_name_config_label(tmp_path, engine):
    cfg = _config(tmp_path)
    assert on_demand.resolve_name(cfg, engine, "111", None, None) == "가나단지"


def test_resolve_name_from_discovered(tmp_path, engine):
    cfg = _config(tmp_path)
    (tmp_path / "discovered.json").write_text(
        json.dumps([{"complex_no": "947", "name": "삼호1차"}]), encoding="utf-8"
    )
    on_demand._DISCOVERED_CACHE.clear()
    assert on_demand.resolve_name(cfg, engine, "947", None, None) == "삼호1차"


def test_resolve_name_fallback_none(tmp_path, engine):
    cfg = _config(tmp_path)
    on_demand._DISCOVERED_CACHE.clear()
    assert on_demand.resolve_name(cfg, engine, "999999", None, None) is None


# ── is_tracked ───────────────────────────────────────────────────────────────
def test_is_tracked(tmp_path, engine):
    cfg = _config(tmp_path)
    with get_session(engine) as s:
        repo.upsert_complex(s, "947", source=SOURCE_TELEGRAM, is_active=True)
        repo.upsert_complex(s, "555", source=SOURCE_ADHOC, is_active=False)
    assert on_demand.is_tracked(cfg, engine, "111")  # config
    assert on_demand.is_tracked(cfg, engine, "947")  # telegram active
    assert not on_demand.is_tracked(cfg, engine, "555")  # adhoc
    assert not on_demand.is_tracked(cfg, engine, "123")  # unknown


def _get(engine, no) -> Complex:
    with get_session(engine) as s:
        return s.exec(select(Complex).where(Complex.complex_no == no)).one()
