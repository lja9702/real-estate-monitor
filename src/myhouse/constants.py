"""앱 전역 상수·열거형·시간 헬퍼.

모든 타임스탬프는 KST(Asia/Seoul) tz-aware 로 다루고, DB 에는 ISO-8601(오프셋 포함)
문자열로 저장한다. naive datetime 은 절대 쓰지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """현재 시각(KST, tz-aware)."""
    return datetime.now(KST)


def to_iso(dt: datetime) -> str:
    """tz-aware datetime → ISO-8601 문자열(오프셋 포함)."""
    return dt.isoformat()


def from_iso(value: str | None) -> datetime | None:
    """ISO-8601 문자열 → tz-aware datetime. None/빈값은 None."""
    if not value:
        return None
    return datetime.fromisoformat(value)


class TradeType(str, Enum):
    """거래 유형."""

    SALE = "SALE"  # 매매
    JEONSE = "JEONSE"  # 전세
    WOLSE = "WOLSE"  # 월세


class ListingStatus(str, Enum):
    """매물(article) 수명주기 상태."""

    ACTIVE = "ACTIVE"
    PENDING_REMOVAL = "PENDING_REMOVAL"  # 미노출 감지됨, 디바운스 대기 중
    REMOVED = "REMOVED"  # 거래완료/내림 확정


class EventType(str, Enum):
    """listing_history 이벤트 종류."""

    NEW = "NEW"
    PRICE_CHANGED = "PRICE_CHANGED"
    REMOVED = "REMOVED"
    REAPPEARED = "REAPPEARED"


class RunStatus(str, Enum):
    """수집 1회 실행 상태."""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"  # 일부 단지 수집 실패(차단/타임아웃 등)
    FAILED = "FAILED"


# ── 단지 출처(complex.source) ──────────────────────────────────────────────
SOURCE_PINNED = "pinned"      # config.yaml 고정 타겟
SOURCE_TELEGRAM = "telegram"  # 텔레그램 /add 로 추가 — 정기 수집(하루 2회)에 포함
SOURCE_WEB = "web"            # 대시보드에서 추가 — 정기 수집에 포함(텔레그램과 동일 의미)
SOURCE_ADHOC = "adhoc"        # /check 1회 조회용 — 추적 안 함(is_active=False), 정기 수집 제외

# 단지 출처 → 표시 라벨(대시보드 배지)
SOURCE_KO: dict[str, str] = {
    SOURCE_PINNED: "고정",
    SOURCE_TELEGRAM: "텔레그램",
    SOURCE_WEB: "웹",
    SOURCE_ADHOC: "1회조회",
}


# ── 네이버 코드 ↔ 내부 enum 매핑 ───────────────────────────────────────────
NAVER_TRADE_CODE: dict[TradeType, str] = {
    TradeType.SALE: "A1",
    TradeType.JEONSE: "B1",
    TradeType.WOLSE: "B2",
}
TRADE_CODE_TO_TYPE: dict[str, TradeType] = {v: k for k, v in NAVER_TRADE_CODE.items()}
TRADE_TYPE_KO: dict[TradeType, str] = {
    TradeType.SALE: "매매",
    TradeType.JEONSE: "전세",
    TradeType.WOLSE: "월세",
}
