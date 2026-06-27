"""봇 명령 파싱/디스패치 + 롱폴링 chat 허가 필터."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from myhouse.bot import runner
from myhouse.bot.commands import LOCKED_MSG, BotContext, handle_text, parse_command
from myhouse.constants import SOURCE_TELEGRAM, RunStatus, now_kst
from myhouse.core import on_demand
from myhouse.core.collector import CollectorLocked, ComplexResult, RunResult
from myhouse.core.diff import ComplexDiff
from myhouse.db import repo
from myhouse.db.engine import get_session
from myhouse.settings import AppConfig, Config, Settings, TargetSpec


class _DummyCM:
    def __enter__(self):
        return object()

    def __exit__(self, *a):
        return False


def _ctx(engine, tmp_path) -> BotContext:
    cfg = Config(
        app=AppConfig(db_path=str(tmp_path / "myhouse.db")),
        targets=[TargetSpec(kind="complex", complex_no="111", label="가나단지")],
    )
    return BotContext(
        config=cfg,
        settings=Settings(),
        engine=engine,
        open_client=lambda: _DummyCM(),
    )


def _canned_run():
    cdiff = ComplexDiff("947", True, [])
    fetch = SimpleNamespace(complete=True, raw_count=0)
    cr = ComplexResult("947", "삼호1차", "삼호1차", address=None, diff=cdiff, fetch=fetch)
    return RunResult(run_id=1, started_at=now_kst(), status=RunStatus.SUCCESS, complexes=[cr])


# ── parse_command ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("/add 947 삼호1차", ("add", "947 삼호1차")),
        ("/check 947", ("check", "947")),
        ("/check@MyHouseBot 947", ("check", "947")),
        ("/deals 947", ("deals", "947")),
        ("/list", ("list", "")),
        ("/HELP", ("help", "")),
        ("도곡렉슬", ("check", "도곡렉슬")),  # 평문 → check
        ("947", ("check", "947")),
        ("", ("help", "")),
        ("   ", ("help", "")),
    ],
)
def test_parse_command(text, expected):
    assert parse_command(text) == expected


# ── 비수집 명령 ──────────────────────────────────────────────────────────────
def test_help(engine, tmp_path):
    assert "명령" in handle_text("/help", _ctx(engine, tmp_path))


def test_unknown(engine, tmp_path):
    assert "모르는 명령" in handle_text("/wat", _ctx(engine, tmp_path))


def test_list_empty(engine, tmp_path):
    assert "없습니다" in handle_text("/list", _ctx(engine, tmp_path))


def test_list_only_subscribed(engine, tmp_path):
    """일반 유저는 본인이 구독한(=/add 한) 단지만 본다(다른 유저 추가분은 안 보임)."""
    with get_session(engine) as s:
        repo.upsert_complex(s, "947", name="삼호1차", source=SOURCE_TELEGRAM, is_active=True)
        repo.add_subscription(s, "555", "947")
    assert "삼호1차" in handle_text("/list", _ctx_chat(engine, tmp_path, "555"))
    assert "없습니다" in handle_text("/list", _ctx_chat(engine, tmp_path, "999"))


# ── /untrack — 본인 구독만 제거(번호·이름) ───────────────────────────────────
def test_untrack_empty_arg_shows_usage(engine, tmp_path):
    assert "번호 또는 이름" in handle_text("/untrack", _ctx_chat(engine, tmp_path))


def test_untrack_by_number(engine, tmp_path):
    with get_session(engine) as s:
        repo.upsert_complex(s, "947", name="삼호1차", source=SOURCE_TELEGRAM, is_active=True)
        repo.add_subscription(s, "555", "947")
    msg = handle_text("/untrack 947", _ctx_chat(engine, tmp_path, "555"))
    assert "추적 중단" in msg and "삼호1차" in msg
    assert "없습니다" in handle_text("/list", _ctx_chat(engine, tmp_path, "555"))  # 구독 제거됨


def test_untrack_by_name(engine, tmp_path):
    with get_session(engine) as s:
        repo.upsert_complex(s, "947", name="방배 삼호1차", source=SOURCE_TELEGRAM, is_active=True)
        repo.add_subscription(s, "555", "947")
    assert "추적 중단" in handle_text("/untrack 삼호", _ctx_chat(engine, tmp_path, "555"))


def test_untrack_not_subscribed(engine, tmp_path):
    assert "추적 중인 단지가 아니" in handle_text("/untrack 999", _ctx_chat(engine, tmp_path, "555"))


def test_untrack_ambiguous_name_asks_number(engine, tmp_path):
    with get_session(engine) as s:
        repo.upsert_complex(s, "1", name="래미안 A", source=SOURCE_TELEGRAM, is_active=True)
        repo.upsert_complex(s, "2", name="래미안 B", source=SOURCE_TELEGRAM, is_active=True)
        repo.add_subscription(s, "555", "1")
        repo.add_subscription(s, "555", "2")
    assert "번호로 지정" in handle_text("/untrack 래미안", _ctx_chat(engine, tmp_path, "555"))


def test_untrack_only_removes_caller(engine, tmp_path):
    """A 가 untrack 해도 B 의 구독·전역 추적(Complex.is_active)엔 영향 없음."""
    from myhouse.db.models import Complex

    with get_session(engine) as s:
        repo.upsert_complex(s, "947", name="삼호1차", source=SOURCE_TELEGRAM, is_active=True)
        repo.add_subscription(s, "A", "947")
        repo.add_subscription(s, "B", "947")
    handle_text("/untrack 947", _ctx_chat(engine, tmp_path, "A"))
    assert "없습니다" in handle_text("/list", _ctx_chat(engine, tmp_path, "A"))  # A 빠짐
    assert "삼호1차" in handle_text("/list", _ctx_chat(engine, tmp_path, "B"))  # B 유지
    with get_session(engine) as s:
        assert s.get(Complex, "947").is_active is True  # 전역 추적 유지


def test_add_empty_arg_shows_usage(engine, tmp_path):
    # 비숫자 인자는 이제 주소/단지명 검색으로 처리되므로(test_search.py), 빈 인자만 사용법 안내
    assert "단지번호" in handle_text("/add", _ctx(engine, tmp_path))


def test_check_empty_arg(engine, tmp_path):
    assert "단지번호" in handle_text("/check", _ctx(engine, tmp_path))


# ── 수집 명령 디스패치(코어 스텁) ────────────────────────────────────────────
def test_check_success(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(
        on_demand, "resolve_query", lambda c, e, q: on_demand.Resolution(complex_no="947")
    )
    monkeypatch.setattr(on_demand, "check_complex", lambda *a, **k: _canned_run())
    monkeypatch.setattr(on_demand, "is_tracked", lambda *a, **k: False)
    monkeypatch.setattr("myhouse.bot.commands.build_cluster_rows", lambda *a, **k: [])
    msg = handle_text("/check 947", _ctx(engine, tmp_path))
    assert "삼호1차" in msg
    assert "/complex/947" in msg
    assert "미추적" in msg


def test_check_locked_returns_friendly_message(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(
        on_demand, "resolve_query", lambda c, e, q: on_demand.Resolution(complex_no="947")
    )

    def _locked(*a, **k):
        raise CollectorLocked("정기 수집 중")

    monkeypatch.setattr(on_demand, "check_complex", _locked)
    assert handle_text("/check 947", _ctx(engine, tmp_path)) == LOCKED_MSG


def test_check_ambiguous_lists_candidates(engine, tmp_path, monkeypatch):
    cands = [on_demand.Candidate("1", "우성1차"), on_demand.Candidate("2", "우성2차")]
    monkeypatch.setattr(
        on_demand, "resolve_query", lambda c, e, q: on_demand.Resolution(candidates=cands)
    )
    msg = handle_text("/check 우성", _ctx(engine, tmp_path))
    assert "우성1차" in msg and "우성2차" in msg


def test_handler_catches_unexpected_error(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(
        on_demand, "resolve_query", lambda c, e, q: on_demand.Resolution(complex_no="947")
    )

    def _boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(on_demand, "check_complex", _boom)
    msg = handle_text("/check 947", _ctx(engine, tmp_path))
    assert "오류" in msg  # 봇은 죽지 않고 사용자에게 알림


# ── 롱폴링 구독 자동 등록 ────────────────────────────────────────────────────
class _FakeNotifier:
    def __init__(self):
        self.sent: list[tuple] = []

    def send(self, text, chat_id=None, **_):
        self.sent.append((str(chat_id), text))


def test_process_update_any_chat_allowed(monkeypatch, engine):
    """누구든 메시지를 보내면 응답한다."""
    monkeypatch.setattr(runner, "handle_text", lambda text, ctx: f"RE:{text}")
    notifier = _FakeNotifier()

    runner._process_update(
        {"message": {"text": "hi", "chat": {"id": 123}}}, notifier, engine, lambda c: None
    )
    assert notifier.sent == [("123", "RE:hi")]

    notifier.sent.clear()
    runner._process_update(
        {"message": {"text": "hi", "chat": {"id": 999}}}, notifier, engine, lambda c: None
    )
    assert notifier.sent == [("999", "RE:hi")]  # 모든 chat 허용


def test_process_update_auto_subscribe(monkeypatch, engine):
    """첫 메시지를 보내면 구독자로 자동 등록된다."""
    from myhouse.db.engine import get_session
    from myhouse.db.repo import get_active_subscriber_ids

    monkeypatch.setattr(runner, "handle_text", lambda text, ctx: "OK")
    notifier = _FakeNotifier()

    runner._process_update(
        {"message": {"text": "hi", "chat": {"id": 42}}}, notifier, engine, lambda c: None
    )
    with get_session(engine) as session:
        ids = get_active_subscriber_ids(session)
    assert "42" in ids


def test_process_update_stop_does_not_subscribe(monkeypatch, engine):
    """/stop 은 새 유저를 구독 등록하지 않는다."""
    from myhouse.db.engine import get_session
    from myhouse.db.repo import get_active_subscriber_ids

    monkeypatch.setattr(runner, "handle_text", lambda text, ctx: "bye")
    notifier = _FakeNotifier()

    runner._process_update(
        {"message": {"text": "/stop", "chat": {"id": 77}}}, notifier, engine, lambda c: None
    )
    with get_session(engine) as session:
        ids = get_active_subscriber_ids(session)
    assert "77" not in ids


def test_process_update_ignores_non_text(monkeypatch, engine):
    monkeypatch.setattr(runner, "handle_text", lambda text, ctx: "RE")
    notifier = _FakeNotifier()
    runner._process_update({"message": {"chat": {"id": 123}}}, notifier, engine, lambda c: None)
    runner._process_update({"edited_message": {"text": "x"}}, notifier, engine, lambda c: None)
    assert notifier.sent == []


# ── 접근 게이트(정적 허용목록 + 초대코드) ─────────────────────────────────────
def test_process_update_static_allow_gates_others(monkeypatch, engine):
    """정적 허용목록의 chat 은 처리, 그 밖은 가입 안내만(구독 안 함)."""
    from myhouse.db.engine import get_session
    from myhouse.db.repo import get_active_subscriber_ids

    monkeypatch.setattr(runner, "handle_text", lambda text, ctx: "RE")
    notifier = _FakeNotifier()
    allowed = {"100"}

    runner._process_update(
        {"message": {"text": "hi", "chat": {"id": 100}}}, notifier, engine, lambda c: None, allowed
    )
    runner._process_update(
        {"message": {"text": "hi", "chat": {"id": 999}}}, notifier, engine, lambda c: None, allowed
    )
    assert notifier.sent[0] == ("100", "RE")
    assert notifier.sent[1][0] == "999" and "초대" in notifier.sent[1][1]  # 가입 안내
    with get_session(engine) as session:
        ids = get_active_subscriber_ids(session)
    assert "100" in ids and "999" not in ids


def test_process_update_join_code_approves(monkeypatch, engine):
    """초대코드가 맞으면 자동 승인·구독되고, 이후 메시지는 정상 처리된다."""
    from myhouse.db.engine import get_session
    from myhouse.db.repo import get_active_subscriber_ids, is_approved

    monkeypatch.setattr(runner, "handle_text", lambda text, ctx: "RE")
    notifier = _FakeNotifier()

    runner._process_update(
        {"message": {"text": "/join secret", "chat": {"id": 7}}},
        notifier, engine, lambda c: None, None, "secret",
    )
    with get_session(engine) as session:
        assert is_approved(session, "7")
        assert "7" in get_active_subscriber_ids(session)
    assert "참여 완료" in notifier.sent[-1][1]

    notifier.sent.clear()
    runner._process_update(
        {"message": {"text": "hi", "chat": {"id": 7}}},
        notifier, engine, lambda c: None, None, "secret",
    )
    assert notifier.sent == [("7", "RE")]  # 승인 후 정상 처리


def test_process_update_join_wrong_code_rejected(engine):
    from myhouse.db.engine import get_session
    from myhouse.db.repo import is_approved

    notifier = _FakeNotifier()
    runner._process_update(
        {"message": {"text": "/join 땡", "chat": {"id": 8}}},
        notifier, engine, lambda c: None, None, "secret",
    )
    with get_session(engine) as session:
        assert not is_approved(session, "8")
    assert "올바르지 않" in notifier.sent[-1][1]


def test_process_update_unauth_nonjoin_gets_hint(engine):
    from myhouse.db.engine import get_session
    from myhouse.db.repo import get_active_subscriber_ids

    notifier = _FakeNotifier()
    runner._process_update(
        {"message": {"text": "안녕", "chat": {"id": 9}}},
        notifier, engine, lambda c: None, None, "secret",
    )
    assert "초대" in notifier.sent[-1][1]
    with get_session(engine) as session:
        assert "9" not in get_active_subscriber_ids(session)  # 안내만, 구독 안 함


# ── /band ────────────────────────────────────────────────────────────────────
def _ctx_chat(engine, tmp_path, chat_id="555") -> BotContext:
    ctx = _ctx(engine, tmp_path)
    ctx.chat_id = chat_id
    return ctx


def test_band_set_then_show(engine, tmp_path):
    ctx = _ctx_chat(engine, tmp_path)
    set_msg = handle_text("/band 7 12", ctx)
    assert "7억~12억" in set_msg

    with get_session(engine) as session:
        sub = repo.get_subscriber(session, "555")
    assert sub.price_min_manwon == 70000 and sub.price_max_manwon == 120000

    show_msg = handle_text("/band", ctx)
    assert "현재 가격밴드" in show_msg and "7억~12억" in show_msg


def test_band_off_clears(engine, tmp_path):
    ctx = _ctx_chat(engine, tmp_path)
    handle_text("/band 7 12", ctx)
    off_msg = handle_text("/band off", ctx)
    assert "해제" in off_msg
    with get_session(engine) as session:
        sub = repo.get_subscriber(session, "555")
    assert sub.price_min_manwon is None and sub.price_max_manwon is None


def test_band_invalid_shows_usage(engine, tmp_path):
    assert "억 단위" in handle_text("/band 시오재", _ctx_chat(engine, tmp_path))


# ── 유저별 단지 구독(/list·/add·/as) ─────────────────────────────────────────
def _ctx_op(engine, tmp_path, chat_id="555") -> BotContext:
    """운영자 컨텍스트 — TELEGRAM_CHAT_ID 로 판정, .env 격리."""
    ctx = _ctx(engine, tmp_path)
    ctx.settings = Settings(_env_file=None, telegram_chat_id=chat_id)
    ctx.chat_id = chat_id
    return ctx


def test_list_operator_sees_all(engine, tmp_path):
    """운영자는 구독하지 않아도 전체 텔레그램 단지를 본다."""
    with get_session(engine) as s:
        repo.upsert_complex(s, "947", name="삼호1차", source=SOURCE_TELEGRAM, is_active=True)
    assert "삼호1차" in handle_text("/list", _ctx_op(engine, tmp_path, "555"))


def test_add_records_subscription(engine, tmp_path, monkeypatch):
    """/add 는 추가한 사람의 구독으로 매핑을 남긴다."""
    with get_session(engine) as s:
        repo.upsert_complex(s, "947", name="삼호1차", source=SOURCE_TELEGRAM, is_active=True)
    monkeypatch.setattr(
        on_demand,
        "add_complex",
        lambda *a, **k: on_demand.AddResult(
            complex_no="947", name="삼호1차", name_resolved=True, run=_canned_run()
        ),
    )
    monkeypatch.setattr("myhouse.bot.commands.build_cluster_rows", lambda *a, **k: [])
    handle_text("/add 947", _ctx_chat(engine, tmp_path, "555"))
    with get_session(engine) as s:
        assert repo.subscribed_complex_nos(s, "555") == {"947"}


def test_as_operator_views_other(engine, tmp_path):
    """운영자 /as <지인> list → 그 지인이 보는 구독 목록을 그대로 확인."""
    with get_session(engine) as s:
        repo.upsert_complex(s, "947", name="삼호1차", source=SOURCE_TELEGRAM, is_active=True)
        repo.add_subscription(s, "777", "947")
    msg = handle_text("/as 777 list", _ctx_op(engine, tmp_path, "555"))
    assert "777" in msg and "삼호1차" in msg


def test_as_rejects_non_operator(engine, tmp_path):
    assert "운영자만" in handle_text("/as 777 list", _ctx_chat(engine, tmp_path, "555"))


def test_as_rejects_nesting(engine, tmp_path):
    assert "중첩" in handle_text("/as 777 as 888 list", _ctx_op(engine, tmp_path, "555"))


def test_build_personalized_operator_vs_user(engine, tmp_path):
    """발송 fan-out — 운영자=전체(None), 일반=공통(pinned)∪본인 구독(telegram)."""
    from myhouse.notify import telegram

    with get_session(engine) as s:
        repo.upsert_complex(s, "pin1", name="핀", source="pinned", is_active=True)
        repo.upsert_complex(s, "tel1", name="텔", source=SOURCE_TELEGRAM, is_active=True)
        repo.subscribe(s, "555")  # 운영자
        repo.subscribe(s, "777")  # 일반
        repo.add_subscription(s, "777", "tel1")
    settings = Settings(_env_file=None, telegram_chat_id="555")
    plans = dict(
        telegram.build_personalized(
            engine,
            settings,
            lambda lo, hi, only: ("ALL" if only is None else ",".join(sorted(only))),
        )
    )
    assert plans["555"] == "ALL"  # 운영자 — 단지 제한 없음
    assert plans["777"] == "pin1,tel1"  # 공통 ∪ 본인 구독


def test_v11_backfill_subscriptions(engine):
    """기존 telegram 단지를 활성 구독자 전원에 백필 + 마커로 재실행 시 되살아나지 않음."""
    from myhouse.db.engine import _backfill_subscriptions_v11
    from myhouse.db.models import Meta

    with get_session(engine) as s:
        marker = s.get(Meta, "subs_backfilled_v11")  # fixture init_db 가 1회 실행 → 제거 후 재현
        if marker:
            s.delete(marker)
            s.commit()
        repo.upsert_complex(s, "tel1", name="텔", source=SOURCE_TELEGRAM, is_active=True)
        repo.subscribe(s, "555")
        repo.subscribe(s, "777")
    with get_session(engine) as s:
        _backfill_subscriptions_v11(s)
        s.commit()
    with get_session(engine) as s:
        assert repo.subscribed_complex_nos(s, "555") == {"tel1"}
        assert repo.subscribed_complex_nos(s, "777") == {"tel1"}
    # 재실행은 no-op(마커 존재) — 사용자가 지운 구독이 되살아나지 않는다
    with get_session(engine) as s:
        repo.remove_subscription(s, "555", "tel1")
    with get_session(engine) as s:
        _backfill_subscriptions_v11(s)
        s.commit()
    with get_session(engine) as s:
        assert repo.subscribed_complex_nos(s, "555") == set()
