"""네이버 연동 예외."""

from __future__ import annotations


class NaverError(Exception):
    """네이버 연동 일반 오류."""


class NaverApiError(NaverError):
    """HTTP/응답 코드 오류 (차단·5xx 등)."""


class NaverParseError(NaverError):
    """응답 구조가 예상과 달라 파싱 불가 — 조용히 쓰레기를 저장하지 않고 시끄럽게 실패."""
