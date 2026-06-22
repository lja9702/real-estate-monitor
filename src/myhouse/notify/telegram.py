"""텔레그램 봇 전송 + 롱폴링 수신(getUpdates)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable

import httpx

from ..settings import Settings

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
SOFT_LIMIT = 3900  # 텔레그램 4096 제한 여유
SEND_DELAY_SECONDS = 0.05  # 청크·대상 간 최소 간격(연타 플러드 방지)
MAX_CHUNKS = 10  # 한 통지의 최대 청크 수 — 초과분은 요약 한 줄로 접는다(대량수집 플러드 차단)
RATE_LIMIT_MAX_WAIT = 60  # 429 retry_after 가 이보다 크면 이만큼만 대기(무한 블로킹 방지)
RATE_LIMIT_RETRIES = 3  # 429 시 같은 청크 재시도 횟수


class TelegramSendError(RuntimeError):
    """sendMessage 실패 — 토큰이 URL 에 노출되는 httpx 예외 대신 사용(로그 비밀 누출 방지)."""


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str | list[str],
        http: httpx.Client | None = None,
        timeout: float = 15.0,
    ):
        self.token = token
        self.chat_ids: list[str] = [chat_id] if isinstance(chat_id, str) else list(chat_id)
        self.chat_id = self.chat_ids[0] if self.chat_ids else ""  # 하위 호환용
        self._http = http or httpx.Client(timeout=timeout)
        self._owns_http = http is None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    @staticmethod
    def _chunks(text: str, limit: int = SOFT_LIMIT) -> list[str]:
        """줄 단위로 limit 이하 청크로 분할(링크 태그 중간 절단 방지)."""
        chunks: list[str] = []
        cur: list[str] = []
        size = 0
        for line in text.split("\n"):
            add = len(line) + 1
            if size + add > limit and cur:
                chunks.append("\n".join(cur))
                cur, size = [], 0
            if len(line) > limit:
                # 한 줄이 너무 길면 강제 분할
                for i in range(0, len(line), limit):
                    chunks.append(line[i : i + limit])
                continue
            cur.append(line)
            size += add
        if cur:
            chunks.append("\n".join(cur))
        return chunks or [""]

    @staticmethod
    def _cap_chunks(chunks: list[str], limit: int = MAX_CHUNKS) -> list[str]:
        """청크가 limit 을 넘으면 앞부분 + 생략 안내 + 마지막(보통 대시보드 푸터)만 남긴다.

        신규 15000여 건 같은 첫 대량 수집에서 다이제스트가 수백 청크로 불어나 텔레그램 rate
        limit(HTTP 429)에 막히고 알림이 통째로 유실되던 문제를 막는다. 헤더(요약 카운트)와
        푸터(대시보드 링크)는 보존하고, 가운데를 안내 한 줄로 접는다.
        """
        if len(chunks) <= limit:
            return chunks
        head = chunks[: limit - 2]
        notice = (
            f"⚠️ 알림이 너무 길어 일부만 표시합니다 — 전체 {len(chunks)}조각 중 {limit - 1}조각. "
            "나머지는 대시보드에서 확인하세요."
        )
        return [*head, notice, chunks[-1]]

    @staticmethod
    def _retry_after(resp: httpx.Response, default: int = 5) -> int:
        """429 응답의 parameters.retry_after(초)를 읽는다(파싱 실패 시 default)."""
        try:
            return int(resp.json()["parameters"]["retry_after"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return default

    def _post_chunk(self, target: str, chunk: str, parse_mode: str | None) -> None:
        """청크 1개 전송 — 429 면 retry_after(상한 내)만큼 대기 후 재시도. 최종 실패 시 TelegramSendError."""
        payload: dict[str, object] = {
            "chat_id": target,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        url = f"{API_BASE}/bot{self.token}/sendMessage"
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            resp = self._http.post(url, json=payload)
            if resp.status_code == 200:
                return
            if resp.status_code == 429 and attempt < RATE_LIMIT_RETRIES:
                wait = min(self._retry_after(resp), RATE_LIMIT_MAX_WAIT)
                log.warning(
                    "텔레그램 429(Too Many Requests) — %d초 대기 후 재시도 (%d/%d)",
                    wait, attempt + 1, RATE_LIMIT_RETRIES,
                )
                time.sleep(wait)
                continue
            # 토큰이 URL 에 박힌 httpx 예외 대신 마스킹된 예외를 던진다.
            log.error("텔레그램 전송 실패 HTTP %s: %s", resp.status_code, resp.text[:300])
            raise TelegramSendError(f"sendMessage 실패 HTTP {resp.status_code}")
        raise TelegramSendError(f"sendMessage 429 — {RATE_LIMIT_RETRIES}회 재시도 후 실패")

    def send(
        self, text: str, parse_mode: str | None = "HTML", chat_id: str | int | None = None
    ) -> None:
        targets = [str(chat_id)] if chat_id is not None else self.chat_ids
        chunks = self._cap_chunks(self._chunks(text))
        first = True
        for target in targets:
            for chunk in chunks:
                if not first:
                    time.sleep(SEND_DELAY_SECONDS)  # 청크·대상 간 페이싱(연타 방지)
                first = False
                self._post_chunk(target, chunk, parse_mode)

    def set_commands(self, commands: list[dict]) -> None:
        """BotFather 없이 봇 명령 목록을 등록한다 (자동완성 메뉴)."""
        resp = self._http.post(
            f"{API_BASE}/bot{self.token}/setMyCommands",
            json={"commands": commands},
        )
        if resp.status_code != 200:
            log.error("setMyCommands 실패 HTTP %s: %s", resp.status_code, resp.text[:300])
            resp.raise_for_status()

    def get_updates(self, offset: int | None = None, timeout: int = 50) -> list[dict]:
        """롱폴링으로 미수신 업데이트(메시지만) 조회. offset 이상 update_id 만 받는다.

        HTTP read 타임아웃을 롱폴링 timeout 보다 길게 줘 정상 빈 응답을 끊지 않는다.
        """
        params: dict[str, object] = {
            "timeout": timeout,
            "allowed_updates": json.dumps(["message"]),
        }
        if offset is not None:
            params["offset"] = offset
        resp = self._http.get(
            f"{API_BASE}/bot{self.token}/getUpdates",
            params=params,
            timeout=timeout + 15,
        )
        if resp.status_code != 200:
            log.error("getUpdates 실패 HTTP %s: %s", resp.status_code, resp.text[:300])
            resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"getUpdates ok=false: {str(data)[:300]}")
        return data.get("result", []) or []


def from_settings(settings: Settings) -> TelegramNotifier | None:
    """토큰이 있으면 Notifier, 없으면 None. chat_id 는 선택(구독자 DB 기반)."""
    if not settings.telegram_configured:
        return None
    return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_ids)  # type: ignore[arg-type]


def broadcast(notifier: TelegramNotifier, engine, text: str) -> None:
    """DB의 활성 구독자 전체에게 같은 텍스트를 전송한다(가격무관 알림·하트비트용)."""
    from ..db.engine import get_session
    from ..db.repo import get_active_subscriber_ids

    with get_session(engine) as session:
        ids = get_active_subscriber_ids(session)
    for cid in ids:
        notifier.send(text, chat_id=cid)


def build_personalized(
    engine,
    settings: Settings,
    build_for: Callable[[int | None, int | None, set[str] | None], str | None],
) -> list[tuple[str, str]]:
    """구독자별 (chat_id, 메시지) 목록 — **발송하지 않는다**. None(빈 내용)은 제외.

    build_for(price_min, price_max, only_complexes) -> 메시지 | None.
    only_complexes: 운영자(allowlist)면 None(전체), 일반 구독자면 공통(pinned/web) ∪ 본인 구독 단지.
    수집·diff 는 전역 1회로 끝났고, 여기서 발송 직전에만 구독자별 가격대·단지로 잘라낸다.
    발송(broadcast_personalized)과 dry-run 미리보기(cli)가 이 한 함수를 공유한다.
    """
    from ..db.engine import get_session
    from ..db.repo import get_active_subscribers, shared_complex_nos, subscribed_complex_nos

    op_ids = set(settings.telegram_allowlist_ids)
    plans: list[tuple[str, int | None, int | None, set[str] | None]] = []
    with get_session(engine) as session:
        subs = get_active_subscribers(session)
        shared = shared_complex_nos(session)
        for sub in subs:
            only = (
                None  # 운영자 — 단지 제한 없음(전체)
                if sub.chat_id in op_ids
                else shared | subscribed_complex_nos(session, sub.chat_id)
            )
            plans.append((sub.chat_id, sub.price_min_manwon, sub.price_max_manwon, only))
    out: list[tuple[str, str]] = []
    for chat_id, lo, hi, only in plans:
        text = build_for(lo, hi, only)
        if text is not None:
            out.append((chat_id, text))
    return out


def broadcast_personalized(
    notifier: TelegramNotifier,
    engine,
    settings: Settings,
    build_for: Callable[[int | None, int | None, set[str] | None], str | None],
) -> int:
    """구독자별 개인화 메시지를 전송. 전송한 구독자 수를 반환한다."""
    plans = build_personalized(engine, settings, build_for)
    for chat_id, text in plans:
        notifier.send(text, chat_id=chat_id)
    return len(plans)
