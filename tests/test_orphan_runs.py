"""좀비 run 정리 — fail_orphan_runs 가 살아있는 락만 보존하고 나머지 RUNNING 을 FAILED 처리."""

from __future__ import annotations

import os
import signal

import pytest
from sqlmodel import select

from myhouse.constants import RunStatus
from myhouse.core.collector import (
    CollectionInterrupted,
    fail_orphan_runs,
    install_term_handler,
)
from myhouse.db.engine import get_session
from myhouse.db.models import Run


def test_sigterm_handler_raises_interrupted():
    """install_term_handler 설치 후 SIGTERM 은 CollectionInterrupted 로 변환된다."""
    old = signal.getsignal(signal.SIGTERM)
    try:
        install_term_handler()
        with pytest.raises(CollectionInterrupted):
            signal.raise_signal(signal.SIGTERM)
            for _ in range(10000):  # 시그널 전달 보장(바이트코드 경계 통과)
                pass
    finally:
        signal.signal(signal.SIGTERM, old)


def _add_run(session, kind: str, status: RunStatus = RunStatus.RUNNING) -> int:
    run = Run(started_at="2026-06-22T00:00:00+09:00", kind=kind, status=status)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run.id


def test_orphan_running_without_lock_is_failed(engine, tmp_path):
    with get_session(engine) as s:
        rid = _add_run(s, "listings")  # 락 파일 없음 → 좀비
        assert fail_orphan_runs(s, tmp_path) == 1
        assert s.get(Run, rid).status == RunStatus.FAILED
        assert s.get(Run, rid).finished_at  # 종료 시각 기록됨


def test_live_lock_preserves_running(engine, tmp_path):
    (tmp_path / ".collector.lock").write_text(str(os.getpid()))  # 살아있는 PID
    with get_session(engine) as s:
        rid = _add_run(s, "listings")
        assert fail_orphan_runs(s, tmp_path) == 0
        assert s.get(Run, rid).status == RunStatus.RUNNING


def test_dead_lock_is_failed(engine, tmp_path):
    (tmp_path / ".deal_collector.lock").write_text("999999")  # 죽은 PID
    with get_session(engine) as s:
        rid = _add_run(s, "deals")
        assert fail_orphan_runs(s, tmp_path) == 1
        assert s.get(Run, rid).status == RunStatus.FAILED


def test_finished_runs_untouched(engine, tmp_path):
    with get_session(engine) as s:
        ok = _add_run(s, "listings", RunStatus.SUCCESS)
        bad = _add_run(s, "listings", RunStatus.FAILED)
        assert fail_orphan_runs(s, tmp_path) == 0
        assert s.get(Run, ok).status == RunStatus.SUCCESS
        assert s.get(Run, bad).status == RunStatus.FAILED


def test_unknown_kind_preserved(engine, tmp_path):
    """락 매핑이 없는 kind 는 라이브 run 오판 방지를 위해 보존."""
    with get_session(engine) as s:
        rid = _add_run(s, "mystery")
        assert fail_orphan_runs(s, tmp_path) == 0
        assert s.get(Run, rid).status == RunStatus.RUNNING


def test_multiple_mixed(engine, tmp_path):
    (tmp_path / ".collector.lock").write_text(str(os.getpid()))  # listings 진짜 실행 중
    with get_session(engine) as s:
        live = _add_run(s, "listings")
        zombie1 = _add_run(s, "deals")  # 락 없음
        zombie2 = _add_run(s, "permits")  # 락 없음
        assert fail_orphan_runs(s, tmp_path) == 2
        assert s.get(Run, live).status == RunStatus.RUNNING
        assert s.get(Run, zombie1).status == RunStatus.FAILED
        assert s.get(Run, zombie2).status == RunStatus.FAILED
