"""FastAPI 앱 팩토리 — 수집기와 동일한 SQLModel/DB 를 공유한다."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..db.engine import init_db, make_engine
from ..settings import Settings, load_config
from .auth import GateMiddleware
from .routes import router

WEB_DIR = Path(__file__).parent
logger = logging.getLogger(__name__)


def _start_sync_refresh(app: FastAPI, settings, db_path: str, state: dict) -> None:
    """백그라운드로 최신 DB 를 받아 교체. 기동 직후 즉시 1회 + 이후 주기적으로.

    create_app(=서버 기동) 을 막지 않으려고 초기 pull 도 이 스레드에서 한다 — 50MB 다운로드가
    시작을 지연시키지 않아 /healthz 가 곧장 통과하고(재시작 루프 방지), 다운로드는 스트리밍이라
    메모리 스파이크가 없다. DB 가 도착하면 엔진을 dispose 해 다음 요청이 새 파일로 재연결된다.
    """
    from ..cloud.sync import s3_from_settings

    if s3_from_settings(settings) is None:
        return
    interval = max(30, int(settings.sync_pull_interval_seconds))

    def _loop() -> None:
        from ..cloud.sync import pull_db

        first = True
        while True:
            if not first:
                time.sleep(interval)
            first = False
            try:
                if pull_db(settings, db_path, state=state):
                    app.state.engine.dispose()  # 다음 요청이 새 파일로 재연결
                    logger.info("DB 동기화 반영 (etag=%s)", state.get("etag"))
            except Exception:
                logger.warning("DB pull 실패", exc_info=True)

    threading.Thread(target=_loop, name="myhouse-sync-pull", daemon=True).start()


class SPAStaticFiles(StaticFiles):
    """SPA용 StaticFiles — 파일이 없으면 index.html 을 반환해 client-side 라우팅을 지원."""

    async def get_response(self, path: str, scope: dict):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def create_app(config_path: str | None = None) -> FastAPI:
    # uvicorn 의 factory 는 인자 없이 호출하므로 serve 가 설정한 환경변수로 config 경로를 받는다.
    config_path = config_path or os.environ.get("MYHOUSE_CONFIG", "config.yaml")
    config = load_config(config_path)
    settings = Settings(_env_file=config.app.env_file)
    readonly = settings.cloud_readonly

    # 읽기 전용(클라우드): DB 를 ro 로 연다. 최신 DB 는 백그라운드 스레드가 받아 교체하므로
    # 기동을 막지 않는다. 쓰기인 init_db·좀비정리는 건너뛴다(스키마는 동기화 원본 맥이 이미 끝낸 상태).
    sync_state: dict = {}
    engine = make_engine(config.app.db_path, readonly=readonly)
    if not readonly:
        init_db(engine)
        # 좀비 정리(안전망): 비정상 종료(SIGKILL·크래시)로 RUNNING 에 고착된 수집을 FAILED 로.
        # 살아있는 락이 있는 run 은 실제 실행 중이므로 보존된다.
        from ..core.collector import fail_orphan_runs
        from ..db.engine import get_session

        with get_session(engine) as session:
            fail_orphan_runs(session, Path(config.app.db_path).parent)

    app = FastAPI(title="myhouse 부동산 모니터", docs_url=None, redoc_url=None)
    app.state.engine = engine
    app.state.config = config
    app.state.settings = settings

    # 읽기 전용: 주기적으로 최신 DB 를 받아 교체(R2 설정 없으면 no-op).
    if readonly:
        _start_sync_refresh(app, settings, config.app.db_path, sync_state)

    # 초대코드 게이트 — 미들웨어가 전 라우트(SPA 마운트 포함)를 감싼다.
    # WEB_INVITE_CODES 가 비면 게이트는 비활성(전체 허용)이라 로컬/기존 동작에 영향이 없다.
    app.add_middleware(GateMiddleware)

    # API/뮤테이션 라우트를 먼저 등록해야 루트(/)의 SPA catch-all 이 /api/* 를 먹지 않는다.
    app.include_router(router)

    # React SPA — Vite 빌드 산출물을 루트(/)에 서빙(단계 6: /app→/ 승격).
    # dist 가 없으면(빌드 전) 조용히 건너뛴다.
    dist = WEB_DIR / "dist"
    if dist.exists():
        app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="spa")

    return app
