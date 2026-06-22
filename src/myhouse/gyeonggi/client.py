"""GwacheonLandClient — 과천시청 게시판→HWP 토지거래허가내역 수집(httpx 직접).

서울(SeoulLandClient)과 같은 인터페이스(fetch_permits(sgg_cd, begin, end) → list[PermitDTO])라
permit_collector 가 시군구 코드로 라우팅만 하면 그대로 흐른다. 차이는 데이터원: 자치구 JSON 이
아니라 월별 HWP 첨부라 (목록→상세→다운로드→PrvText 파싱) 다단계로 받는다.
"""

from __future__ import annotations

import io
import logging

import httpx
import olefile

from ..seoul.permit_parser import PermitDTO
from .endpoints import (
    GWACHEON_SGG_CD,
    PERMIT_M_ID,
    PERMIT_PT_IDX,
    USER_AGENT,
    board_list_url,
    board_referer,
    board_view_url,
    file_down_url,
)
from .errors import GyeonggiApiError, GyeonggiParseError
from .permit_parser import parse_board_list, parse_gwacheon_prvtext, parse_view_attachment

log = logging.getLogger(__name__)


def _ym(s: str) -> tuple[int, int]:
    """'YYYYMMDD' → (year, month)."""
    return int(s[:4]), int(s[4:6])


class GwacheonLandClient:
    """과천시 토지거래허가내역 클라이언트. 월별 게시글의 HWP 를 파싱한다."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Referer": board_referer()},
        )

    def __enter__(self) -> GwacheonLandClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        try:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as e:
            raise GyeonggiApiError(f"요청 실패 {url}: {e}") from e

    def list_posts(self) -> list[tuple[str, int, int]]:
        """월별 글 목록 [(bIdx, year, month)] (최신순)."""
        resp = self._get(board_list_url(), {"ptIdx": PERMIT_PT_IDX, "mId": PERMIT_M_ID})
        return parse_board_list(resp.text)

    def _attachment(self, b_idx: str) -> tuple[str, str]:
        resp = self._get(
            board_view_url(), {"bIdx": b_idx, "ptIdx": PERMIT_PT_IDX, "mId": PERMIT_M_ID}
        )
        return parse_view_attachment(resp.text)

    def _prvtext(self, atch_file_id: str, file_sn: str) -> str:
        """첨부 HWP 다운로드 → PrvText(미리보기 텍스트) 스트림 추출."""
        content = self._get(
            file_down_url(), {"atchFileId": atch_file_id, "fileSn": file_sn}
        ).content
        buf = io.BytesIO(content)
        if not olefile.isOleFile(buf):
            raise GyeonggiParseError("첨부가 HWP(OLE) 형식이 아님")
        ole = olefile.OleFileIO(buf)
        try:
            if not ole.exists("PrvText"):
                raise GyeonggiParseError("HWP 에 PrvText 스트림이 없음")
            return ole.openstream("PrvText").read().decode("utf-16le", "ignore")
        finally:
            ole.close()

    def _permits_for_post(self, b_idx: str, year: int, month: int) -> list[PermitDTO]:
        atch = self._attachment(b_idx)
        text = self._prvtext(*atch)
        return parse_gwacheon_prvtext(text, year, month)

    def fetch_months(self, n: int) -> list[PermitDTO]:
        """최신 n개 월별 글의 허가내역(날짜 필터 없음) — 검증(probe)용."""
        out: list[PermitDTO] = []
        for b_idx, year, month in self.list_posts()[:n]:
            out.extend(self._permits_for_post(b_idx, year, month))
        return out

    def fetch_permits(self, sgg_cd: str, begin_date: str, end_date: str) -> list[PermitDTO]:
        """기간 [begin,end] 에 걸친 월별 글을 받아 허가일이 기간 내인 건만 반환.

        sgg_cd 는 인터페이스 호환용(과천=41290 고정). begin/end 는 'YYYYMMDD'.
        """
        if sgg_cd and sgg_cd != GWACHEON_SGG_CD:
            raise GyeonggiApiError(f"과천 클라이언트에 잘못된 시군구: {sgg_cd}")
        lo, hi = _ym(begin_date), _ym(end_date)
        begin_iso = f"{begin_date[:4]}-{begin_date[4:6]}-{begin_date[6:8]}"
        end_iso = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

        out: list[PermitDTO] = []
        for b_idx, year, month in self.list_posts():
            if lo <= (year, month) <= hi:  # 글의 대상 월이 기간과 겹치면 받는다
                out.extend(self._permits_for_post(b_idx, year, month))
        return [p for p in out if p.permit_date and begin_iso <= p.permit_date <= end_iso]
