"""서울시 토지거래허가 수집 예외 (네이버 errors 와 분리 — 데이터원이 다르다)."""

from __future__ import annotations


class SeoulApiError(Exception):
    """HTTP/네트워크 실패 또는 시스템 점검(EXCEPTION) 등 일시적 오류."""


class SeoulParseError(Exception):
    """응답 구조가 예상과 달라 파싱 불가 — 쓰레기 저장 방지용으로 시끄럽게 실패."""
