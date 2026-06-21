"""SeoulLandClient — land.seoul.go.kr 토지거래허가 내역 수집(httpx 직접).

네이버와 달리 봇 차단이 없어 브라우저·토큰이 불필요하다. with 문으로 httpx 세션을 연다.
"""

from __future__ import annotations

import logging

import httpx

from .endpoints import (
    USER_AGENT,
    contract_list_url,
    contract_referer,
    sgg_list_url,
)
from .errors import SeoulApiError
from .permit_parser import PermitDTO, parse_permits

log = logging.getLogger(__name__)


class SeoulLandClient:
    """토지거래허가 내역 클라이언트. 자치구 단위·최대 62일 조회."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": contract_referer(),
                "X-Requested-With": "XMLHttpRequest",
            },
        )

    def __enter__(self) -> SeoulLandClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get_json(self, url: str, *, data: dict | None = None) -> dict:
        try:
            resp = (
                self._client.post(url, data=data)
                if data is not None
                else self._client.get(url)
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise SeoulApiError(f"요청 실패 {url}: {e}") from e
        except ValueError as e:  # JSON 디코드 실패
            raise SeoulApiError(f"JSON 파싱 실패 {url}: {e}") from e

    def fetch_sgg_list(self) -> dict[str, str]:
        """자치구 코드→이름 맵. {'11680': '강남구', …}. '11000'(서울특별시 전체)은 제외."""
        payload = self._get_json(sgg_list_url())
        rows = payload.get("result") or []
        return {
            str(r["sggCd"]): str(r.get("sggNm") or "")
            for r in rows
            if r.get("sggCd") and str(r["sggCd"]) != "11000"
        }

    def fetch_permits(self, sgg_cd: str, begin_date: str, end_date: str) -> list[PermitDTO]:
        """자치구 1개의 허가내역(기간 최대 62일). begin/end 는 'YYYYMMDD'."""
        payload = self._get_json(
            contract_list_url(),
            data={"sggCd": sgg_cd, "beginDate": begin_date, "endDate": end_date},
        )
        return parse_permits(payload, sgg_cd)
