"""FastAPI 앱 팩토리 — 수집기와 동일한 SQLModel/DB 를 공유한다."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..db.engine import init_db, make_engine
from ..settings import Settings, load_config
from ..util import format_manwon, format_price
from .routes import router

WEB_DIR = Path(__file__).parent


def create_app(config_path: str | None = None) -> FastAPI:
    # uvicorn 의 factory 는 인자 없이 호출하므로 serve 가 설정한 환경변수로 config 경로를 받는다.
    config_path = config_path or os.environ.get("MYHOUSE_CONFIG", "config.yaml")
    config = load_config(config_path)
    engine = make_engine(config.app.db_path)
    init_db(engine)

    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    templates.env.filters["manwon"] = format_manwon
    templates.env.filters["price"] = format_price

    app = FastAPI(title="myhouse 부동산 모니터", docs_url=None, redoc_url=None)
    app.state.engine = engine
    app.state.config = config
    app.state.settings = Settings(_env_file=config.app.env_file)
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.include_router(router)
    return app
