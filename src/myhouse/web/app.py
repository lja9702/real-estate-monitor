"""FastAPI 앱 팩토리 — 수집기와 동일한 SQLModel/DB 를 공유한다."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..db.engine import init_db, make_engine
from ..settings import Settings, load_config
from .routes import router

WEB_DIR = Path(__file__).parent


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
    engine = make_engine(config.app.db_path)
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
    app.state.settings = Settings(_env_file=config.app.env_file)

    # API/뮤테이션 라우트를 먼저 등록해야 루트(/)의 SPA catch-all 이 /api/* 를 먹지 않는다.
    app.include_router(router)

    # React SPA — Vite 빌드 산출물을 루트(/)에 서빙(단계 6: /app→/ 승격).
    # dist 가 없으면(빌드 전) 조용히 건너뛴다.
    dist = WEB_DIR / "dist"
    if dist.exists():
        app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="spa")

    return app
