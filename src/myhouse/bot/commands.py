"""봇 명령 파싱 + 처리(디스패치) — 네트워크 루프와 분리해 단위 테스트 가능하게 둔다.

핸들러는 코어(on_demand)로 단지를 수집하고, 웹 쿼리로 현재 스냅샷을 읽어 reply 로 포매팅한다.
브라우저 클라이언트는 `ctx.open_client()` 컨텍스트매니저로 명령당 1회 열고 닫는다(토큰 신선도↑).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from html import escape

from sqlmodel import select

from ..constants import SOURCE_TELEGRAM
from ..core import on_demand
from ..core.collector import CollectorLocked
from ..db.engine import get_session
from ..db.models import Complex
from ..naver.client import NaverLandClient
from ..naver.errors import NaverApiError, NaverParseError
from ..notify import reply
from ..notify.bands import EOK, format_band
from ..settings import Config, Settings
from ..web.queries import (
    Filters,
    PermitFilters,
    build_cluster_rows,
    build_permit_rows,
    recent_deals_for_complex,
)

log = logging.getLogger(__name__)

KNOWN = {"help", "start", "stop", "add", "check", "deals", "permits", "list", "discover", "band", "join", "as"}
LOCKED_MSG = "⏳ 지금 정기 수집이 진행 중입니다. 잠시 후 다시 시도하세요."
JOIN_GATE_HINT = (
    "🔒 초대받은 사람만 쓸 수 있는 봇이에요.\n"
    "참여하려면 <code>/join 초대코드</code> 를 보내세요(코드는 운영자에게 문의)."
)


@dataclass
class BotContext:
    config: Config
    settings: Settings
    engine: object
    open_client: Callable[[], AbstractContextManager[NaverLandClient]]
    send_progress: Callable[[str], None] | None = None
    chat_id: str = ""

    @property
    def dashboard_url(self) -> str:
        return self.config.app.dashboard_url

    def progress(self, msg: str) -> None:
        if self.send_progress is not None:
            try:
                self.send_progress(msg)
            except Exception:  # noqa: BLE001 — 진행 알림 실패는 무시
                log.debug("진행 알림 전송 실패", exc_info=True)


def parse_command(text: str) -> tuple[str, str]:
    """입력 텍스트 → (명령, 인자). '/' 없는 평문은 매물 조회(check)로 본다."""
    t = (text or "").strip()
    if not t:
        return ("help", "")
    if t.startswith("/"):
        head, _, rest = t[1:].partition(" ")
        cmd = head.split("@", 1)[0].lower()  # '/check@MyBot' 대응
        return (cmd, rest.strip())
    return ("check", t)


def handle_join_attempt(text: str, chat_id: str, engine, join_code: str | None) -> str:
    """미승인 chat 의 메시지 처리 — <code>/join 코드</code> 만 통과시킨다.

    코드 일치 시 DB 에 승인(approve_chat)하고 환영+도움말을 돌려준다. 그 외(틀린 코드·
    다른 명령·평문)는 가입 안내만 한다. 일반 명령 디스패치(handle_text)에는 도달하지 않는다.
    """
    from ..db.repo import approve_chat

    cmd, arg = parse_command(text)
    if cmd != "join":
        return JOIN_GATE_HINT
    if not join_code or arg.strip() != join_code:
        return "❌ 초대코드가 올바르지 않습니다. 운영자에게 코드를 확인해 다시 시도하세요."
    with get_session(engine) as session:
        approve_chat(session, chat_id)
    return (
        "✅ 참여 완료! 이제 봇을 쓸 수 있어요.\n\n"
        + reply.format_help()
        + "\n\n관심 가격대를 정하려면 <code>/band 7 12</code> 처럼 보내세요."
    )


def _is_operator(ctx: BotContext) -> bool:
    """운영자(allowlist) chat 여부 — 운영자는 단지 제한 없이 전체를 보고/받는다."""
    return bool(ctx.chat_id) and ctx.chat_id in ctx.settings.telegram_allowlist_ids


def handle_text(text: str, ctx: BotContext) -> str:
    """메시지 1건 → 응답 문자열(HTML). 예외는 잡아 사용자용 메시지로 변환."""
    cmd, arg = parse_command(text)
    try:
        if cmd == "help":
            return reply.format_help(_is_operator(ctx))
        if cmd == "start":
            return _handle_start(ctx)
        if cmd == "stop":
            return _handle_stop(ctx)
        if cmd == "list":
            return _handle_list(ctx)
        if cmd == "add":
            return _handle_add(arg, ctx)
        if cmd == "check":
            return _handle_check(arg, ctx)
        if cmd == "deals":
            return _handle_deals(arg, ctx)
        if cmd == "permits":
            return _handle_permits(arg, ctx)
        if cmd == "discover":
            return _handle_discover(ctx)
        if cmd == "band":
            return _handle_band(arg, ctx)
        if cmd == "join":
            return "이미 참여 중입니다. <code>/help</code> 로 명령을 확인하세요."
        if cmd == "as":
            return _handle_as(arg, ctx)
        return reply.format_unknown(cmd)
    except CollectorLocked:
        return LOCKED_MSG
    except (NaverApiError, NaverParseError) as e:
        log.warning("명령 처리 중 네이버 오류: %s", e)
        return f"⚠ 네이버 조회 실패: {e}\n잠시 후 다시 시도하세요."
    except Exception as e:  # noqa: BLE001 — 봇은 죽지 않고 사용자에게 알린다
        log.exception("명령 처리 실패: %s", text)
        return f"⚠ 처리 중 오류가 발생했습니다: {type(e).__name__}"


def _handle_start(ctx: BotContext) -> str:
    from ..db.engine import get_session
    from ..db.repo import is_subscribed

    already = False
    if ctx.chat_id:
        with get_session(ctx.engine) as session:
            already = is_subscribed(session, ctx.chat_id)
    suffix = "이미 구독 중입니다." if already else "알림 구독이 시작되었습니다. ✅"
    return reply.format_help(_is_operator(ctx)) + f"\n\n{suffix}"


def _handle_stop(ctx: BotContext) -> str:
    from ..db.engine import get_session
    from ..db.repo import unsubscribe

    if not ctx.chat_id:
        return "⚠ 구독 해제에 실패했습니다."
    with get_session(ctx.engine) as session:
        removed = unsubscribe(session, ctx.chat_id)
    if removed:
        return "🔕 알림 구독이 해제되었습니다. 다시 받으려면 /start 를 보내세요."
    return "현재 구독 중이 아닙니다."


_BAND_OFF = {"off", "all", "0", "전체", "해제", "reset"}
_BAND_USAGE = (
    "관심 가격대를 <b>억 단위</b>로 보내세요.\n"
    "• <code>/band 7 12</code> — 7억~12억만\n"
    "• <code>/band 15</code> — 15억 이상\n"
    "• <code>/band 0 12</code> — 12억 이하\n"
    "• <code>/band off</code> — 전체(밴드 해제)\n"
    "• <code>/band</code> — 현재 밴드 보기"
)


def _parse_band(arg: str) -> tuple[str, int | None, int | None]:
    """'/band' 인자 해석 → (종류, lo, hi). 종류: show|off|set|error. 가격은 만원 단위.

    숫자는 억 단위(소수 허용). 1개=하한(이상), 2개=[lo,hi](순서 무관). 구분자 공백/-/~ 허용.
    """
    s = arg.strip().lower()
    if not s:
        return ("show", None, None)
    if s in _BAND_OFF:
        return ("off", None, None)
    parts = s.replace("~", " ").replace("-", " ").split()
    nums: list[float] = []
    for p in parts:
        try:
            nums.append(float(p))
        except ValueError:
            return ("error", None, None)
    if any(n < 0 for n in nums):
        return ("error", None, None)
    if len(nums) == 1:
        return ("set", int(round(nums[0] * EOK)), None)
    if len(nums) == 2:
        lo, hi = sorted(nums)
        return ("set", int(round(lo * EOK)), int(round(hi * EOK)))
    return ("error", None, None)


def _handle_band(arg: str, ctx: BotContext) -> str:
    """관심 가격밴드 설정/조회 — 정기 푸시 다이제스트를 이 가격대로 필터한다."""
    from ..db.repo import get_subscriber, set_subscriber_band

    if not ctx.chat_id:
        return "⚠ 가격밴드를 설정할 수 없습니다."
    kind, lo, hi = _parse_band(arg)
    if kind == "error":
        return _BAND_USAGE
    if kind == "show":
        with get_session(ctx.engine) as session:
            sub = get_subscriber(session, ctx.chat_id)
        if sub is None:
            return (
                "아직 구독 전입니다. 아무 메시지나 보내면 구독되고, "
                "<code>/band 7 12</code> 처럼 관심 가격대를 정할 수 있어요."
            )
        label = format_band(sub.price_min_manwon, sub.price_max_manwon)
        if label is None:
            return "현재 가격밴드: <b>전체</b>(제한 없음)\n바꾸려면 예: <code>/band 7 12</code>"
        return (
            f"현재 가격밴드: <b>{label}</b>\n"
            "바꾸려면 <code>/band 7 12</code> · 해제 <code>/band off</code>"
        )
    # set / off
    with get_session(ctx.engine) as session:
        set_subscriber_band(session, ctx.chat_id, lo, hi)
    label = format_band(lo, hi)
    if label is None:
        return "✅ 가격밴드 <b>해제</b> — 이제 전체 가격대 알림을 받습니다."
    return (
        f"✅ 가격밴드 설정: <b>{label}</b>\n"
        "이 가격대의 매물·실거래·신규단지만 정기 알림으로 받습니다."
    )


def _handle_list(ctx: BotContext) -> str:
    """추적 단지 목록 — 운영자는 전체 텔레그램 단지, 일반 유저는 본인이 /add 한 단지만."""
    from ..db.repo import list_subscribed_complexes

    with get_session(ctx.engine) as session:
        if _is_operator(ctx):
            rows = session.exec(
                select(Complex).where(
                    Complex.source == SOURCE_TELEGRAM,
                    Complex.is_active == True,  # noqa: E712
                )
            ).all()
        else:
            rows = list_subscribed_complexes(session, ctx.chat_id)
    pairs = sorted(((c.complex_no, c.name or c.complex_no) for c in rows), key=lambda x: x[1])
    return reply.format_list(pairs)


def _handle_as(arg: str, ctx: BotContext) -> str:
    """운영자 전용 시점전환 — '/as <chat_id> <명령>' 을 그 유저 시점으로 실행(개인화 검증용).

    예: '/as 7745991913 list' → 그 지인이 보는 /list 결과를 운영자 텔레그램에서 즉시 확인.
    하위 명령은 슬래시 없이 적어도 된다('list' → '/list'). /as 중첩은 막는다.
    """
    if not _is_operator(ctx):
        return "🔒 <code>/as</code> 는 운영자만 쓸 수 있습니다."
    target, _, rest = arg.strip().partition(" ")
    rest = rest.strip()
    if not target or not rest:
        return (
            "운영자 검증용 — 다른 유저 시점으로 명령을 실행합니다.\n"
            "예: <code>/as 7745991913 list</code> · <code>/as 7745991913 check 1234</code>"
        )
    sub_text = rest if rest.startswith("/") else "/" + rest
    sub_cmd, _ = parse_command(sub_text)
    if sub_cmd == "as":
        return "❌ <code>/as</code> 는 중첩할 수 없습니다."
    body = handle_text(sub_text, replace(ctx, chat_id=target))
    return f"👤 <code>{escape(target)}</code> 시점 — <code>/{escape(sub_cmd)}</code>\n\n{body}"


def _split_add_arg(arg: str) -> tuple[str | None, str | None]:
    parts = arg.split(maxsplit=1)
    if not parts:
        return None, None
    no = parts[0].strip()
    alias = parts[1].strip() if len(parts) > 1 else None
    return no, alias


def _do_add(no: str, alias: str | None, client, ctx: BotContext) -> str:
    """단지번호로 추적 추가 + 구독 기록 + 첫 수집 후 응답 구성(번호/검색 분기 공용)."""
    from ..db.repo import add_subscription

    add = on_demand.add_complex(
        ctx.config, ctx.settings, ctx.engine, no, alias=alias, client=client
    )
    with get_session(ctx.engine) as session:
        if ctx.chat_id:
            add_subscription(session, ctx.chat_id, no)  # 추가한 사람의 구독으로 기록
        snapshot = build_cluster_rows(
            session, Filters(complex_no=no, status="all", sort="price_asc"), add.run.run_id
        )
    return reply.format_add_reply(add, snapshot, dashboard_url=ctx.dashboard_url)


def _handle_add(arg: str, ctx: BotContext) -> str:
    no, alias = _split_add_arg(arg)
    if not no:
        return (
            "추가할 단지번호 또는 주소/단지명을 보내세요.\n"
            "예: <code>/add 1234</code> · <code>/add 1234 도곡렉슬</code> · <code>/add 방배 삼호1차</code>"
        )
    # 숫자 → 단지번호로 바로 추가
    if no.isdigit():
        ctx.progress(f"⏳ 단지 {no} 추가 + 첫 매물 수집 중… (브라우저 기동/토큰 발급)")
        with ctx.open_client() as client:
            return _do_add(no, alias, client, ctx)
    # 비숫자 → 주소/단지명으로 검색해 단지번호 역추적
    keyword = arg.strip()
    ctx.progress(f"⏳ '{keyword}' 단지 검색 중…")
    with ctx.open_client() as client:
        hits = on_demand.search_address(ctx.config, ctx.engine, client, keyword)
        if not hits:
            return reply.format_add_not_found(keyword)
        if len(hits) == 1:
            h = hits[0]
            ctx.progress(f"⏳ '{h.name}'({h.complex_no}) 추가 + 첫 매물 수집 중…")
            return _do_add(h.complex_no, h.name, client, ctx)
        return reply.format_add_candidates(keyword, hits)


def _resolve_local(q: str, ctx: BotContext) -> tuple[str | None, str | None, bool]:
    """비숫자 입력을 로컬(config/DB)에서 해석. 반환 (complex_no, 즉시응답, 검색필요).

    - (번호, None, False): 확정 → 바로 작업
    - (None, 메시지, False): 후보 안내 등 즉시 응답
    - (None, None, True): 로컬에 없음 → 라이브 검색 필요(브라우저)
    """
    if q.isdigit():
        return q, None, False
    res = on_demand.resolve_query(ctx.config, ctx.engine, q)
    if res.found:
        return res.complex_no, None, False
    if res.candidates:
        return None, reply.format_candidates(q, res.candidates), False
    return None, None, True


def _resolve_via_search(
    q: str, ctx: BotContext, client, command: str
) -> tuple[str | None, str | None, str | None]:
    """로컬에서 못 찾은 입력을 라이브 검색(주소/단지명)으로 해석. 반환 (번호, 즉시응답, 단지명)."""
    hits = on_demand.search_address(ctx.config, ctx.engine, client, q)
    if not hits:
        return None, reply.format_not_found(q), None
    if len(hits) > 1:
        return None, reply.format_search_candidates(q, hits, command), None
    return hits[0].complex_no, None, hits[0].name


def _handle_check(arg: str, ctx: BotContext) -> str:
    q = arg.strip()
    if not q:
        return "조회할 단지번호·이름·주소를 보내세요. 예: <code>/check 1234</code> 또는 <code>/check 방배 삼호1차</code>"
    no, early, need_search = _resolve_local(q, ctx)
    if early:
        return early
    name = None
    ctx.progress(f"⏳ '{q}' 매물 조회 중…")
    with ctx.open_client() as client:
        if need_search:
            no, early, name = _resolve_via_search(q, ctx, client, "check")
            if early:
                return early
        run = on_demand.check_complex(
            ctx.config, ctx.settings, ctx.engine, no, client=client, name=name
        )
    tracked = on_demand.is_tracked(ctx.config, ctx.engine, no)
    with get_session(ctx.engine) as session:
        snapshot = build_cluster_rows(
            session, Filters(complex_no=no, status="all", sort="price_asc"), run.run_id
        )
    return reply.format_check_reply(
        run, snapshot, complex_no=no, tracked=tracked, dashboard_url=ctx.dashboard_url
    )


def _handle_permits(arg: str, ctx: BotContext) -> str:
    """토지거래허가 조회 — /permits [단지번호·이름].

    단지 지정 시: 지번 백필 + 서울시 API 온디맨드 수집 (/deals 와 동일한 패턴).
    단지 미지정: 전체 단지 DB 캐시(최근 3개월).
    """
    from ..core.permit_collector import run_permit_for_one

    q = arg.strip()
    months = 3
    complex_no: str | None = None
    name: str | None = None

    if q:
        no, early, need_search = _resolve_local(q, ctx)
        if early:
            return early

        ctx.progress(f"⏳ '{q}' 토지거래허가 조회 중… (서울시 API)")
        with ctx.open_client() as naver_client:
            if need_search:
                no, early, name = _resolve_via_search(q, ctx, naver_client, "permits")
                if early:
                    return early

            complex_no = no
            if name is None:
                with get_session(ctx.engine) as session:
                    from ..db.models import Complex
                    cx = session.get(Complex, complex_no)
                    name = cx.name if cx else complex_no

            # 온디맨드 수집 — 지번 백필 + 서울시 API 패칭
            cr = run_permit_for_one(ctx.config, ctx.engine, complex_no, naver_client=naver_client)

        if cr.error:
            return (
                f"🏛 <b>토지거래허가</b> <b>{escape(name or complex_no)}</b>\n"
                f"⚠ {escape(cr.error)}"
            )

    with get_session(ctx.engine) as session:
        f = PermitFilters(complex_no=complex_no, months=months, sort="date_desc")
        rows = build_permit_rows(session, f, last_permit_run_id=None)

    return reply.format_permits_reply(
        rows,
        complex_no=complex_no,
        name=name,
        dashboard_url=ctx.dashboard_url,
        months=months,
    )


def _handle_discover(ctx: BotContext) -> str:
    """지역 단지를 즉시 탐색해 신규 편입분을 알린다(주간 자동탐색의 수동 버전)."""
    disc = ctx.config.discover
    if not disc.enabled or not disc.regions:
        return "주간 탐색이 꺼져 있습니다. <code>config.yaml</code> 의 <code>discover.enabled</code> 를 켜세요."
    from ..core.discover import run_discovery
    from ..notify.discover_digest import build_discover_digest

    ctx.progress("⏳ 지역 단지 탐색 중… (지도 마커 수집, 30초~1분 소요)")
    with ctx.open_client() as client:
        result = run_discovery(
            ctx.config, ctx.settings, ctx.engine, trigger=SOURCE_TELEGRAM, client=client
        )
    if result.first_run:
        return (
            f"🔭 기준선(baseline) 확립 — 현재 조건에 맞는 단지 <b>{result.total_found}</b>개를 "
            "기록했습니다. 다음부터 <b>새로 편입</b>되는 단지를 알려드립니다."
        )
    return build_discover_digest(result, ctx.dashboard_url)


def _handle_deals(arg: str, ctx: BotContext) -> str:
    q = arg.strip()
    if not q:
        return "실거래를 조회할 단지번호·이름·주소를 보내세요. 예: <code>/deals 1234</code> 또는 <code>/deals 방배 삼호1차</code>"
    no, early, need_search = _resolve_local(q, ctx)
    if early:
        return early
    name = None
    ctx.progress(f"⏳ '{q}' 실거래 갱신 중… (평형별 조회로 시간이 걸릴 수 있어요)")
    with ctx.open_client() as client:
        if need_search:
            no, early, name = _resolve_via_search(q, ctx, client, "deals")
            if early:
                return early
        result = on_demand.check_deals(
            ctx.config, ctx.settings, ctx.engine, no, client=client, name=name
        )
    name = name or (result.complexes[0].name if result.complexes else no)
    with get_session(ctx.engine) as session:
        recent = recent_deals_for_complex(session, no, result.run_id, months=24)
    return reply.format_deals_reply(
        result, recent, complex_no=no, name=name, dashboard_url=ctx.dashboard_url
    )
