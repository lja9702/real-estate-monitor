"""SQLite 엔진 — WAL 모드 + busy_timeout 으로 수집기↔대시보드 동시 접근 허용."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from ..constants import SOURCE_TELEGRAM, now_kst, to_iso
from .models import (  # noqa: F401 — table 클래스 등록(create_all 이 인식)
    SCHEMA_VERSION,
    Complex,
    Meta,
    Subscriber,
    Subscription,
)


def make_engine(db_path: str | Path, echo: bool = False) -> Engine:
    """db_path 에 대한 SQLite 엔진 생성 (디렉터리 자동 생성, WAL PRAGMA 설정)."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{p}",
        echo=echo,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


# 기존 테이블에 나중에 추가된 컬럼 — create_all 은 기존 테이블을 변경하지 않으므로
# SQLite ALTER TABLE 로 누락분만 더한다. (table, column, "TYPE [DEFAULT ...]")
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("complex", "pyeongs_json", "VARCHAR"),
    ("complex", "deals_fetched_at", "VARCHAR"),
    ("run", "kind", "VARCHAR DEFAULT 'listings'"),
    ("run", "complexes_done", "INTEGER DEFAULT 0"),
    ("complex", "starred", "BOOLEAN DEFAULT 0"),
    ("complex", "bonbun", "VARCHAR"),
    ("complex", "bubun", "VARCHAR"),
    ("complex", "total_dong_count", "INTEGER"),
    ("complex", "use_approve_ymd", "VARCHAR"),
    ("complex", "floor_area_ratio", "INTEGER"),
    ("complex", "building_coverage_ratio", "INTEGER"),
    ("subscriber", "price_min_manwon", "INTEGER"),
    ("subscriber", "price_max_manwon", "INTEGER"),
    ("subscriber", "approved", "BOOLEAN DEFAULT 0"),
]


def _migrate(engine: Engine) -> None:
    """기존 DB 의 누락 컬럼을 채운다(idempotent). 새 테이블은 create_all 이 이미 생성."""
    with engine.begin() as conn:
        for table, column, decl in _ADDED_COLUMNS:
            existing = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").all()
            }
            if not existing:
                continue  # 테이블 자체가 없으면(create_all 이 막 만든 신규 스키마) 건너뜀
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
                if (table, column) == ("complex", "starred"):
                    # v4 1회 이관: 별표한 매물(cluster)이 있던 단지를 관심 단지로 승격.
                    # 컬럼이 막 생긴 이 순간에만 실행되므로 사용자가 이후 해제해도 되살아나지 않는다.
                    conn.exec_driver_sql(
                        "UPDATE complex SET starred = 1 WHERE complex_no IN ("
                        " SELECT DISTINCT complex_no FROM curation"
                        " WHERE starred = 1 AND complex_no IS NOT NULL)"
                    )
                if (table, column) == ("subscriber", "approved"):
                    # v10 1회 이관: 게이트 도입 전부터 쓰던 기존 구독자는 모두 승인 처리(잠금 방지).
                    # 컬럼이 막 생긴 이 순간에만 실행 — 이후 거절해도 되살아나지 않는다.
                    conn.exec_driver_sql("UPDATE subscriber SET approved = 1")


def _backfill_subscriptions_v11(session: Session) -> None:
    """v11 1회 이관: 기존 telegram 단지를 활성 구독자 전원의 구독으로 귀속(무손실).

    소유 추적 도입 전부터 있던 telegram 단지는 '누가 추가했는지' 기록이 없으므로, 현재 활성
    구독자 모두에게 귀속해 아무도 기존 /list 를 잃지 않게 한다. Meta 마커로 1회만 실행 —
    이후 사용자가 구독을 비워도 되살아나지 않는다.
    """
    if get_meta(session, "subs_backfilled_v11") is not None:
        return
    now = to_iso(now_kst())
    active_ids = list(
        session.exec(select(Subscriber.chat_id).where(Subscriber.active == True))  # noqa: E712
    )
    tele_nos = list(
        session.exec(select(Complex.complex_no).where(Complex.source == SOURCE_TELEGRAM))
    )
    existing = {
        (row[0], row[1])
        for row in session.exec(select(Subscription.chat_id, Subscription.complex_no))
    }
    for cid in active_ids:
        for no in tele_nos:
            if (cid, no) not in existing:
                session.add(Subscription(chat_id=cid, complex_no=no, created_at=now))
    set_meta(session, "subs_backfilled_v11", "done")


def init_db(engine: Engine) -> None:
    """테이블 생성(존재 시 무시) + 누락 컬럼 마이그레이션 + schema_version 기록."""
    SQLModel.metadata.create_all(engine)
    _migrate(engine)
    with Session(engine) as session:
        _backfill_subscriptions_v11(session)
        row = session.get(Meta, "schema_version")
        if row is None:
            session.add(Meta(key="schema_version", value=SCHEMA_VERSION))
        elif row.value != SCHEMA_VERSION:
            row.value = SCHEMA_VERSION
            session.add(row)
        session.commit()


def get_session(engine: Engine) -> Session:
    return Session(engine)


def get_meta(session: Session, key: str) -> str | None:
    row = session.get(Meta, key)
    return row.value if row else None


def set_meta(session: Session, key: str, value: str) -> None:
    row = session.get(Meta, key)
    if row is None:
        session.add(Meta(key=key, value=value))
    else:
        row.value = value
        session.add(row)


__all__ = [
    "make_engine",
    "init_db",
    "get_session",
    "get_meta",
    "set_meta",
    "select",
    "Session",
]
