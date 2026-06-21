"""표준 logging 설정 — stdout(launchd 가 캡처) + logs/ 파일."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False


def setup_logging(level: int = logging.INFO, log_dir: str | Path = "logs") -> None:
    """루트 로거를 콘솔 + 파일 핸들러로 1회 구성."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        d = Path(log_dir)
        d.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(d / "myhouse.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        # 파일 로깅 실패해도 콘솔 로깅은 유지
        root.warning("파일 로그 디렉터리를 만들 수 없어 콘솔 로깅만 사용합니다: %s", log_dir)

    # 외부 라이브러리 소음 줄이기
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _CONFIGURED = True


def mask_secret(value: str | None, keep: int = 4) -> str:
    """토큰 등 비밀값을 로그용으로 마스킹."""
    if not value:
        return "<none>"
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "…" + "*" * 4
