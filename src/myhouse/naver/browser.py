"""Playwright 기반 new.land 세션.

헤드리스 Chromium 으로 new.land 를 열어 ① authorization 토큰을 자동 캡처하고,
② 같은 브라우저 컨텍스트(context.request)로 API 를 호출한다. 실제 브라우저 지문/쿠키를
쓰므로 토큰 3시간 만료·rate-limit·봇 차단 문제를 우회한다.
"""

from __future__ import annotations

import logging

from .endpoints import NEW_LAND_BASE, USER_AGENT
from .errors import NaverApiError

log = logging.getLogger(__name__)


class NaverBrowser:
    """new.land 헤드리스 세션. with 문으로 사용."""

    def __init__(
        self,
        headless: bool = True,
        user_agent: str = USER_AGENT,
        nav_timeout_ms: int = 30000,
        token_wait_ms: int = 12000,
    ):
        self.headless = headless
        self.user_agent = user_agent
        self.nav_timeout = nav_timeout_ms
        self.token_wait = token_wait_ms
        self._pw = None
        self._browser = None
        self._ctx = None
        self._token: str | None = None

    def __enter__(self) -> NaverBrowser:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._ctx = self._browser.new_context(user_agent=self.user_agent, locale="ko-KR")
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        for obj, meth in ((self._ctx, "close"), (self._browser, "close"), (self._pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, meth)()
            except Exception:  # noqa: BLE001
                pass
        self._ctx = self._browser = self._pw = None

    def ensure_token(self, seed_complex_no: str) -> str:
        """seed 단지 페이지를 열어 토큰을 1회 캡처(이후 재사용)."""
        if self._token:
            return self._token
        if self._ctx is None:
            raise NaverApiError("브라우저 미시작 — with 문 안에서 사용하세요")

        page = self._ctx.new_page()
        holder: dict[str, str | None] = {"t": None}

        def on_request(req) -> None:  # noqa: ANN001
            if holder["t"] is None and "/api/" in req.url:
                auth = req.headers.get("authorization")
                if auth and auth.lower().startswith("bearer"):
                    holder["t"] = auth

        page.on("request", on_request)
        try:
            page.goto(
                f"{NEW_LAND_BASE}/complexes/{seed_complex_no}",
                wait_until="domcontentloaded",
                timeout=self.nav_timeout,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("토큰 캡처용 페이지 로드 경고: %s", e)

        waited = 0
        while holder["t"] is None and waited < self.token_wait:
            page.wait_for_timeout(500)
            waited += 500
        page.close()

        if not holder["t"]:
            raise NaverApiError("authorization 토큰 캡처 실패 — new.land 구조 변경/차단 의심")
        self._token = holder["t"]
        log.info("new.land 토큰 캡처 완료")
        return self._token

    def fetch_json(self, url: str, referer: str) -> dict:
        """브라우저 컨텍스트로 GET(JSON). 토큰 자동 첨부."""
        if self._ctx is None or not self._token:
            raise NaverApiError("토큰 미발급 — ensure_token 먼저 호출하세요")
        resp = self._ctx.request.get(
            url,
            headers={
                "authorization": self._token,
                "referer": referer,
                "accept": "application/json, text/plain, */*",
                "accept-language": "ko-KR,ko;q=0.9",
            },
            timeout=self.nav_timeout,
        )
        if resp.status != 200:
            raise NaverApiError(f"HTTP {resp.status} — {url}")
        try:
            return resp.json()
        except Exception as e:  # noqa: BLE001
            raise NaverApiError(f"JSON 파싱 실패: {e}") from e
