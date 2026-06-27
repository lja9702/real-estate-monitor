"""웹 대시보드 초대코드 게이트 — stdlib HMAC 서명 쿠키 + 미들웨어.

`WEB_INVITE_CODES` 가 비어 있으면 게이트는 비활성(전체 허용)이라 로컬/기존 동작에 영향이 없다.
지인 공개 시 `WEB_INVITE_CODES`(쉼표 복수)·`SESSION_SECRET` 을 `.env` 에 채운다(텔레그램 `/join` 코드와 같은 철학).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

COOKIE_NAME = "myhouse_session"
MAX_AGE_SECONDS = 30 * 24 * 3600  # 30일
# 게이트 없이 통과시킬 경로(게이트 페이지 자신 + 헬스체크 + 파비콘)
_OPEN_PREFIXES = ("/gate", "/healthz", "/favicon")
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_loopback_request(request: Request) -> bool:
    """프록시 뒤가 아니고 클라이언트가 루프백이면 True.

    클라우드/터널은 X-Forwarded-* 헤더를 붙이므로, 그 헤더가 있으면(프록시 경유)
    소켓이 루프백으로 보여도 면제하지 않는다 — 클라우드에서 전원이 우회되는 사고를 막는다.
    """
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return False
    client = request.client
    return bool(client) and client.host in _LOOPBACK_HOSTS


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sig(secret: str, body: str) -> str:
    return _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def sign_token(secret: str, role: str = "member") -> str:
    """{role, iat} 를 HMAC-SHA256 으로 서명한 `body.sig` 토큰."""
    payload = json.dumps({"r": role, "iat": int(time.time())}, separators=(",", ":")).encode()
    body = _b64e(payload)
    return f"{body}.{_sig(secret, body)}"


def verify_token(secret: str, token: str | None, max_age: int = MAX_AGE_SECONDS) -> dict | None:
    """서명·만료 검증 통과 시 payload dict, 아니면 None."""
    if not token or "." not in token:
        return None
    body, _, sig = token.partition(".")
    if not hmac.compare_digest(sig, _sig(secret, body)):
        return None
    try:
        data = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "iat" not in data:
        return None
    try:
        if int(time.time()) - int(data["iat"]) > max_age:
            return None
    except (TypeError, ValueError):
        return None
    return data


def safe_next(raw: str | None) -> str:
    """오픈 리다이렉트 방지 — 같은 사이트 상대경로만 허용(외부 URL·`//` 차단)."""
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


def cookie_is_secure(request: Request) -> bool:
    """https 요청일 때만 Secure 쿠키(로컬 http·TestClient 에선 False 라 쿠키가 동작)."""
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def gate_page(next_path: str = "/", error: bool = False) -> str:
    """자족적(인라인 CSS) 초대코드 입력 페이지 — 인증 전엔 SPA 가 로드되지 않는다."""
    nxt = html.escape(safe_next(next_path), quote=True)
    err = '<p class="err">초대코드가 올바르지 않습니다.</p>' if error else ""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>myhouse — 초대코드</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; background:#0b0b0c; color:#e7e7e9; }}
  .card {{ width:min(92vw,360px); padding:28px 24px; border:1px solid #2a2a2e; border-radius:14px; background:#141416; }}
  h1 {{ font-size:18px; font-weight:600; margin:0 0 4px; }}
  p.sub {{ margin:0 0 18px; color:#9a9aa0; font-size:13px; }}
  input {{ width:100%; height:42px; padding:0 12px; font-size:15px; border:1px solid #2a2a2e;
    border-radius:9px; background:#0b0b0c; color:#e7e7e9; }}
  button {{ width:100%; height:42px; margin-top:12px; font-size:15px; font-weight:600; border:0;
    border-radius:9px; background:#3b6cff; color:#fff; cursor:pointer; }}
  .err {{ color:#ff6b6b; font-size:13px; margin:12px 0 0; }}
</style></head>
<body>
  <form class="card" method="post" action="/gate">
    <h1>🏠 myhouse</h1>
    <p class="sub">초대코드를 입력하면 들어갈 수 있어요.</p>
    <input name="code" type="text" placeholder="초대코드" autofocus autocomplete="off" required>
    <input type="hidden" name="next" value="{nxt}">
    <button type="submit">입장</button>
    {err}
  </form>
</body></html>"""


class GateMiddleware(BaseHTTPMiddleware):
    """초대코드 쿠키가 없으면 HTML 요청은 게이트 페이지, `/api/*` 는 401."""

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = request.app.state.settings
        path = request.url.path

        # 읽기 전용(클라우드): 변경 메서드는 게이트와 무관하게 차단 — /run* 의 서브프로세스 spawn 까지
        # 라우트 진입 전에 막는다. /gate 로그인(open) 은 DB 를 안 건드리므로 허용.
        if (
            settings.cloud_readonly
            and request.method in ("POST", "PUT", "PATCH", "DELETE")
            and not path.startswith(_OPEN_PREFIXES)
        ):
            return JSONResponse({"detail": "읽기 전용 모드입니다."}, status_code=403)

        if not settings.web_gate_enabled:
            return await call_next(request)

        if path.startswith(_OPEN_PREFIXES):
            return await call_next(request)

        # 로컬 면제 — 운영자가 localhost 로 쓸 땐 코드 없이 통과(클라우드/터널은 프록시 헤더로 차단됨).
        if settings.gate_local_bypass and is_loopback_request(request):
            request.state.role = "local"
            return await call_next(request)

        data = verify_token(settings.gate_signing_secret, request.cookies.get(COOKIE_NAME))
        if data is not None:
            request.state.role = data.get("r", "member")
            return await call_next(request)

        if path.startswith("/api"):
            return JSONResponse({"detail": "초대코드가 필요합니다."}, status_code=401)
        return HTMLResponse(gate_page(next_path=path), status_code=200)
