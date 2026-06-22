"""telegram.TelegramNotifier.send — 429 재시도·청크 상한·토큰 마스킹.

run #22 회귀 방지: 신규 15000여 건 다이제스트가 수백 청크로 불어나 텔레그램 rate limit(429)에
막히고, 그 예외가 collector 에서 삼켜져 운영자 알림이 통째로 유실되던 문제.
"""

from __future__ import annotations

import pytest

from myhouse.notify import telegram
from myhouse.notify.telegram import MAX_CHUNKS, TelegramNotifier, TelegramSendError


class _Resp:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = "ok"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _FakeHttp:
    """post() 가 미리 짜둔 응답 큐를 순서대로 반환(소진 후엔 200). 호출을 기록한다."""

    def __init__(self, responses: list[_Resp] | None = None):
        self._queue = list(responses or [])
        self.posts: list[tuple[str, dict]] = []

    def post(self, url: str, json: dict) -> _Resp:  # noqa: A002 - httpx 시그니처 맞춤
        self.posts.append((url, json))
        return self._queue.pop(0) if self._queue else _Resp(200)

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """페이싱/429 대기를 테스트에서 무력화(빠르게)."""
    monkeypatch.setattr(telegram.time, "sleep", lambda *_: None)


def test_send_retries_on_429_then_succeeds():
    http = _FakeHttp([
        _Resp(429, {"parameters": {"retry_after": 1}}, "Too Many Requests"),
        _Resp(200),
    ])
    TelegramNotifier("TOKEN", "123", http=http).send("hello")  # 단일 청크
    assert len(http.posts) == 2  # 429 한 번 후 재시도 성공


def test_send_gives_up_after_max_retries():
    http = _FakeHttp([_Resp(429, {"parameters": {"retry_after": 1}})] * 10)
    with pytest.raises(TelegramSendError):
        TelegramNotifier("TOKEN", "123", http=http).send("hello")


def test_oversized_message_is_capped_and_keeps_footer():
    http = _FakeHttp()
    footer = "📊 대시보드 열기"
    body = "\n".join("• " + "x" * 120 for _ in range(2000))  # 수십 청크 분량
    TelegramNotifier("TOKEN", "123", http=http).send(body + "\n" + footer)

    sent = [p[1]["text"] for p in http.posts]
    assert len(sent) == MAX_CHUNKS  # 수백 청크가 상한으로 접힘
    assert any("일부만 표시" in t for t in sent)  # 생략 안내 포함
    assert footer in sent[-1]  # 마지막(대시보드 푸터) 보존


def test_normal_message_is_not_capped_or_delayed():
    http = _FakeHttp()
    TelegramNotifier("TOKEN", "123", http=http).send("🏠 변동 없음.")
    assert len(http.posts) == 1  # 평상시 알림은 그대로 1통


def test_error_does_not_leak_token():
    http = _FakeHttp([_Resp(400, {"ok": False}, "Bad Request: chat not found")])
    with pytest.raises(TelegramSendError) as ei:
        TelegramNotifier("SECRET-TOKEN-XYZ", "123", http=http).send("hi")
    assert "SECRET-TOKEN-XYZ" not in str(ei.value)  # 토큰 비노출
