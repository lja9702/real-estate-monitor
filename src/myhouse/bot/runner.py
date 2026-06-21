"""텔레그램 롱폴링 루프 — getUpdates 로 명령을 받아 처리하고 응답을 보낸다.

상시 구동(launchd KeepAlive) 전제. 브라우저 클라이언트는 명령당 새로 열어(토큰 신선도)
처리하고 닫는다. 누구든 봇에게 메시지를 보내면 구독자로 자동 등록된다(/stop 으로 해제).
"""

from __future__ import annotations

import logging
import time

import httpx

from ..db.engine import get_meta, get_session, init_db, make_engine, set_meta
from ..db.repo import is_approved, is_subscribed, subscribe
from ..logging_conf import setup_logging
from ..naver.client import NaverLandClient
from ..notify.telegram import TelegramNotifier
from ..settings import Settings, load_config
from .commands import BotContext, handle_join_attempt, handle_text

log = logging.getLogger("myhouse.bot")

OFFSET_KEY = "telegram_bot_offset"


def _load_offset(engine) -> int | None:
    with get_session(engine) as session:
        v = get_meta(session, OFFSET_KEY)
    return int(v) if v and v.lstrip("-").isdigit() else None


def _save_offset(engine, offset: int) -> None:
    with get_session(engine) as session:
        set_meta(session, OFFSET_KEY, str(offset))
        session.commit()


def _process_update(
    update: dict,
    notifier: TelegramNotifier,
    engine,
    ctx_factory,
    allowed: set[str] | None = None,
    join_code: str | None = None,
) -> None:
    msg = update.get("message")
    if not isinstance(msg, dict):
        return
    text = msg.get("text")
    if not isinstance(text, str):
        return
    chat_id = (msg.get("chat") or {}).get("id")
    if chat_id is None:
        return
    cid = str(chat_id)

    # 게이트: 정적 허용목록(.env TELEGRAM_ALLOWLIST) ∪ DB 승인(초대코드 /join).
    # 둘 다 미설정이면 게이트 끔 = 전체 허용(역호환).
    if allowed or join_code:
        authorized = bool(allowed and cid in allowed)
        if not authorized:
            with get_session(engine) as session:
                authorized = is_approved(session, cid)
        if not authorized:
            # 미승인 chat — /join <초대코드> 만 통과(맞으면 DB 승인). 그 외엔 가입 안내.
            reply_text = handle_join_attempt(text, cid, engine, join_code)
            try:
                notifier.send(reply_text, chat_id=cid)
            except Exception:  # noqa: BLE001
                log.exception("가입 안내 전송 실패 (chat_id=%s)", cid)
            return

    # /stop 이 아닌 첫 메시지면 자동 구독
    is_stop = text.strip().lower().startswith("/stop")
    with get_session(engine) as session:
        if not is_stop and not is_subscribed(session, cid):
            subscribe(session, cid)
            log.info("신규 구독자 등록: chat_id=%s", cid)

    ctx = ctx_factory(chat_id)
    reply_text = handle_text(text, ctx)
    try:
        notifier.send(reply_text, chat_id=cid)
    except Exception:  # noqa: BLE001 — 전송 실패가 루프를 멈추지 않게
        log.exception("응답 전송 실패 (chat_id=%s)", cid)


def run_bot(config_path: str = "config.yaml", *, poll_timeout: int = 50) -> None:
    """봇 롱폴링 루프 진입점. 텔레그램 미설정이면 즉시 종료."""
    setup_logging()
    config = load_config(config_path)
    settings = Settings(_env_file=config.app.env_file)
    if not settings.telegram_configured:
        raise SystemExit(
            "❌ 텔레그램 미설정 — .env 에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 를 넣으세요."
        )

    engine = make_engine(config.app.db_path)
    init_db(engine)

    notifier = TelegramNotifier(
        settings.telegram_bot_token,  # type: ignore[arg-type]
        settings.telegram_chat_ids,
        timeout=poll_timeout + 15,
    )

    def open_client():
        return NaverLandClient(
            request_delay_seconds=config.app.request_delay_seconds,
            headless=config.app.headless,
        )

    def ctx_factory(chat_id) -> BotContext:
        return BotContext(
            config=config,
            settings=settings,
            engine=engine,
            open_client=open_client,
            send_progress=lambda m: notifier.send(m, chat_id=chat_id),
            chat_id=str(chat_id),
        )

    allowed = set(settings.telegram_allowlist_ids)
    join_code = settings.telegram_join_code or None
    if allowed or join_code:
        log.info(
            "chat 게이트 ON — 정적 허용 %d명%s",
            len(allowed),
            " + 초대코드(/join) 셀프등록" if join_code else " (초대코드 미설정: 셀프등록 불가)",
        )
    else:
        log.warning(
            "chat 게이트 OFF — 누구나 봇 명령을 쓸 수 있습니다"
            " (.env 의 TELEGRAM_ALLOWLIST/TELEGRAM_JOIN_CODE 로 제한 권장)"
        )

    offset = _load_offset(engine)
    log.info("🤖 봇 시작 (offset=%s, poll=%ss) — /help 로 명령 확인", offset, poll_timeout)

    try:
        while True:
            try:
                updates = notifier.get_updates(offset, timeout=poll_timeout)
            except (httpx.HTTPError, RuntimeError) as e:
                log.warning("getUpdates 오류 — 5초 후 재시도: %s", e)
                time.sleep(5)
                continue

            for update in updates:
                uid = update.get("update_id")
                if isinstance(uid, int):
                    offset = uid + 1
                    _save_offset(
                        engine, offset
                    )  # 처리 전에 offset 확정(poison 메시지 무한루프 방지)
                try:
                    _process_update(update, notifier, engine, ctx_factory, allowed, join_code)
                except Exception:  # noqa: BLE001 — 한 업데이트 실패가 루프를 멈추지 않게
                    log.exception("업데이트 처리 실패: %s", update.get("update_id"))
    except KeyboardInterrupt:
        log.info("봇 종료(사용자 중단)")
    finally:
        notifier.close()
