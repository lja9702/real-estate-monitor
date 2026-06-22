"""법원경매 수집 예외 (네이버/서울시 errors 와 분리 — 데이터원이 다르다)."""

from __future__ import annotations


class CourtAuctionApiError(Exception):
    """HTTP/네트워크/JSON 실패 등 일시적 오류."""


class CourtAuctionParseError(Exception):
    """응답 구조가 예상과 달라 파싱 불가 — 쓰레기 저장 방지용으로 시끄럽게 실패."""


class CourtAuctionBlockedError(CourtAuctionApiError):
    """IP 차단(응답 data.ipcheck=false). 1시간 이상 대기 후 재시도해야 한다."""
