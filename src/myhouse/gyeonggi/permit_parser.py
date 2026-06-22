"""과천시 게시판/HWP → 정규화 PermitDTO (서울과 동일 값 객체 재사용).

게시판 목록 HTML, 상세 HTML(첨부 식별자), HWP PrvText(허가 표)를 각각 파싱한다.

HWP PrvText 한 줄(데이터 행) 예:
  <1><경기도 과천시 별양동 3><대><2026.03.04.><주거용><2026.04.><><취득일로부터 2년><->
셀은 `<…>` 로 구분된다. 인덱스: 0=연번 1=소재지지번 2=지목 3=허가년월일 4=이용목적 ….
이 서식("토지거래계약 허가사항")은 *허가된* 건만 싣는다 → job_gbn 은 항상 '허가'.

소재지는 단일/복수 지번이 섞인다("중앙동 97, 99, 100, 101", "원문동 10 별양동 91").
동(洞)별로 잘라 지번마다 PermitDTO 1건을 만든다 — 단지 매칭(cortar_no+본번/부번)은 서울과 동일.
가격·면적은 없다(거래활성 선행신호).
"""

from __future__ import annotations

import hashlib
import re

from ..seoul.permit_parser import JOB_GRANTED, PermitDTO, normalize_jibun
from .endpoints import GWACHEON_DONG_CORTAR, GWACHEON_SGG_CD
from .errors import GyeonggiParseError

# goTo.view('list','<bIdx>','259','<mId>') — 목록 행의 상세 링크
_VIEW_RE = re.compile(r"goTo\.view\('list','(\d+)','" + r"\d+" + r"'")
# 제목의 연·월: "토지거래계약 허가사항(2026.5.)" / "(2026. 5.)" / "('26.5월)"
_TITLE_YM_RE = re.compile(r"허가사항\s*\(?\s*'?(\d{2,4})\s*[.\-]\s*(\d{1,2})")
# 상세 페이지의 첨부 다운로드: fn_egov_downFile('atchFileId','fileSn')
_ATTACH_RE = re.compile(r"fn_egov_downFile\('([^']+)','([^']+)'\)")
# PrvText 셀: <...>
_CELL_RE = re.compile(r"<([^<>]*)>")
# 동(洞) + 지번 묶음: "별양동 3", "과천동 376-11", "중앙동 97, 99, 100, 101"
_PARCEL_RE = re.compile(r"([가-힣]+[동리])\s*([0-9][0-9,\s\-]*)")
# 허가년월일: "2026.03.04." / "2026. 3. 4"
_DATE_RE = re.compile(r"(\d{4})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})")


def parse_board_list(html: str) -> list[tuple[str, int, int]]:
    """게시판 목록 HTML → [(bIdx, year, month)] (최신순). 행 단위로 상세링크+제목을 짝짓는다."""
    out: list[tuple[str, int, int]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        mv = _VIEW_RE.search(tr)
        if not mv:
            continue
        text = re.sub(r"<[^>]+>", " ", tr)
        mt = _TITLE_YM_RE.search(text)
        if not mt:
            continue
        yr = int(mt.group(1))
        if yr < 100:  # '26 → 2026
            yr += 2000
        out.append((mv.group(1), yr, int(mt.group(2))))
    return out


def parse_view_attachment(html: str) -> tuple[str, str]:
    """상세 HTML → (atchFileId, fileSn). 첨부가 없으면 GyeonggiParseError."""
    m = _ATTACH_RE.search(html)
    if not m:
        raise GyeonggiParseError("상세 페이지에서 첨부(fn_egov_downFile) 를 찾지 못함")
    return m.group(1), m.group(2)


def _permit_date(raw: str) -> str | None:
    m = _DATE_RE.search(raw or "")
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _parcels(address: str) -> list[tuple[str, str]]:
    """소재지 문자열 → [(동명, 지번문자열)]. '원문동 10 별양동 91' → [('원문동','10'),('별양동','91')]."""
    out: list[tuple[str, str]] = []
    for m in _PARCEL_RE.finditer(address):
        dong = m.group(1)
        for jb in re.split(r"[,\s]+", m.group(2).strip()):
            if jb:
                out.append((dong, jb))
    return out


def _permit_key(year: int, month: int, seq: str, dong: str, bonbun: str, bubun: str) -> str:
    """과천 허가 자연키. 접수번호가 없어 (연월|연번|동|본번|부번)로 구성 — 같은 글 재수집 시 동일."""
    raw = f"GC|{year:04d}{month:02d}|{seq}|{dong}|{bonbun}|{bubun}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def parse_gwacheon_prvtext(text: str, year: int, month: int) -> list[PermitDTO]:
    """HWP PrvText('토지거래계약 허가사항' 표) → PermitDTO 리스트. 데이터 행만 추린다.

    데이터 행 = 첫 셀이 숫자(연번)이고 소재지에 동(洞)+지번이 있는 줄. 복수 지번은 행마다 분해.
    """
    out: list[PermitDTO] = []
    for line in text.splitlines():
        cells = _CELL_RE.findall(line)
        if len(cells) < 5:
            continue
        seq = cells[0].strip()
        if not seq.isdigit():  # 헤더/주석 행 skip
            continue
        address = cells[1].strip()
        jimok = cells[2].strip() or None
        permit_date = _permit_date(cells[3])
        use_purp = cells[4].strip() or None
        for dong, jibun in _parcels(address):
            norm = normalize_jibun(jibun)
            if norm is None:  # 산/임야 등 — 아파트 아님
                continue
            bonbun, bubun = norm
            lawd_cd = GWACHEON_DONG_CORTAR.get(dong)  # 미등록 동 → None(매칭 제외)
            out.append(
                PermitDTO(
                    permit_key=_permit_key(year, month, seq, dong, bonbun, bubun),
                    sgg_cd=GWACHEON_SGG_CD,
                    lawd_cd=lawd_cd,
                    address=f"과천시 {dong} {jibun}",
                    bonbun=bonbun,
                    bubun=bubun,
                    permit_date=permit_date,
                    job_gbn=JOB_GRANTED,  # '허가사항' 서식 — 모두 허가
                    use_purp=use_purp,
                    jimok=jimok,
                )
            )
    return out
