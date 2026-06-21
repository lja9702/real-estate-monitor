"""원시 JSON(토지거래허가 1건) → 정규화 PermitDTO.

land.seoul.go.kr `/land/wsklis/getContractList.do` 응답 result[] 원소 기준:
  ADDRESS("강남구 청담동 127-31"), LAWD_CD(법정동코드 10자리), BOBN/BUBN(본번/부번 4자리),
  HNDL_YMD("20260619" 허가일), JOB_GBN_NM("허가"|"취소"|"불허가"|"취하"|"반려"),
  USE_PURP("주거용"), JIMOK("대"), SGG_CD, ACC_YEAR/ACC_NO/OBJ_SEQNO(접수 자연키).
  result[0].MESSAGE=="EXCEPTION" 이면 한국토지정보시스템 점검(데이터 없음).

⚠️ 가격·면적·단지명은 응답에 없다. 단지 매칭은 (LAWD_CD, 본번, 부번) ↔
네이버 단지상세(cortarNo, detailAddress)로 한다. 정규화 규칙은 normalize_jibun 참조.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel

from .errors import SeoulParseError

# 거래 성사 신호로 보는 처리구분(JOB_GBN_NM). 그 외(취소/불허가/취하/반려)는 저장은 하되 알림 제외.
JOB_GRANTED = "허가"
# 이용목적(USE_PURP) — 아파트 거래로 한정하는 필터값. 그 외 농업·사업·복지편익시설용 등은 제외.
RESIDENTIAL = "주거용"


class PermitDTO(BaseModel):
    """정규화된 토지거래허가 1건 (DB·diff 공유 값 객체). 가격·면적 없음."""

    permit_key: str
    sgg_cd: str
    lawd_cd: str | None = None
    address: str  # "강남구 청담동 127-31" (표시용)
    bonbun: str | None = None  # 본번 4자리 zero-pad (매칭키)
    bubun: str | None = None  # 부번 4자리 zero-pad (매칭키)
    permit_date: str | None = None  # 허가일 ISO 'YYYY-MM-DD'
    job_gbn: str | None = None  # 처리구분명(허가/취소/…)
    use_purp: str | None = None  # 이용목적(주거용 등)
    jimok: str | None = None  # 지목(대 등)

    @property
    def granted(self) -> bool:
        return self.job_gbn == JOB_GRANTED


def _clean(value: object) -> str | None:
    """문자열 정리. None/빈/'-'/'null' → None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ("-", "null", "None"):
        return None
    return s


def _pad4(raw: object) -> str | None:
    """지번 한 토막을 4자리 zero-pad. 0/음수/비숫자 → None."""
    s = _clean(raw)
    if s is None:
        return None
    try:
        n = int(s)
    except ValueError:
        return None
    return f"{n:04d}" if n > 0 else None


def normalize_jibun(raw: object) -> tuple[str, str] | None:
    """단지 detailAddress('770-1', '974', '974 외')를 (본번, 부번) 4자리 쌍으로. 불가 시 None.

    '770-1' → ('0770','0001'), '974' → ('0974','0000'). '산12-3'(임야)은 아파트가 아니므로
    None. 허가내역 BOBN/BUBN(이미 분리)과 같은 자릿수 규칙(_pad4)으로 맞춰 동일 비교를 보장한다.
    """
    s = _clean(raw)
    if s is None or s.startswith("산"):  # 임야/산 지번 — 아파트 아님
        return None
    head = s.split()[0].split("-")  # "974 외" 꼬리 제거 후 본번-부번 분리
    bonbun = _pad4(head[0])
    if bonbun is None:
        return None
    bubun = _pad4(head[1]) if len(head) > 1 else None
    return bonbun, bubun or "0000"


def jibun_from_parts(bobn: object, bubn: object) -> tuple[str | None, str | None]:
    """허가내역의 분리된 BOBN/BUBN → (본번4, 부번4). 본번 결손이면 (None, None)."""
    bonbun = _pad4(bobn)
    if bonbun is None:
        return None, None
    return bonbun, (_pad4(bubn) or "0000")


def _permit_date(raw: object) -> str | None:
    """'20260619' → '2026-06-19'. 불완전하면 None."""
    s = _clean(raw)
    if s is None or not s.isdigit() or len(s) != 8:
        return None
    try:
        return f"{int(s[:4]):04d}-{int(s[4:6]):02d}-{int(s[6:8]):02d}"
    except ValueError:
        return None


def compute_permit_key(sgg_cd: str, acc_year: str, acc_no: str, obj_seqno: str) -> str:
    """허가 자연키 = 접수 식별자(자치구|접수년도|접수번호|대상순번). 처리구분은 제외
    (같은 접수가 허가→취소로 재관측되면 같은 키로 행 갱신)."""
    raw = f"{sgg_cd}|{acc_year}|{acc_no}|{obj_seqno}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def extract_permit_rows(payload: dict) -> list[dict]:
    """응답에서 result[] 추출. 시스템 점검(EXCEPTION)은 빈 리스트, 구조 불일치는 SeoulParseError."""
    if not isinstance(payload, dict):
        raise SeoulParseError(f"허가내역 응답이 dict 아님: {type(payload)}")
    rows = payload.get("result")
    if rows is None:
        raise SeoulParseError(f"허가내역 배열(result) 없음: keys={sorted(payload)[:12]}")
    if not isinstance(rows, list):
        raise SeoulParseError(f"result 가 list 아님: {type(rows)}")
    if rows and isinstance(rows[0], dict) and rows[0].get("MESSAGE") == "EXCEPTION":
        return []  # 한국토지정보시스템 점검 — 일시적, 다음 회차 포착
    return rows


def parse_permits(payload: dict, sgg_cd: str) -> list[PermitDTO]:
    """자치구 허가내역 응답 → PermitDTO 리스트. 자연키 결손 행은 조용히 skip."""
    out: list[PermitDTO] = []
    for r in extract_permit_rows(payload):
        acc_year = _clean(r.get("ACC_YEAR"))
        acc_no = _clean(r.get("ACC_NO"))
        obj_seqno = _clean(r.get("OBJ_SEQNO")) or "1"
        address = _clean(r.get("ADDRESS"))
        if not (acc_year and acc_no and address):
            continue
        row_sgg = _clean(r.get("SGG_CD")) or sgg_cd
        bonbun, bubun = jibun_from_parts(r.get("BOBN"), r.get("BUBN"))
        out.append(
            PermitDTO(
                permit_key=compute_permit_key(row_sgg, acc_year, acc_no, obj_seqno),
                sgg_cd=row_sgg,
                lawd_cd=_clean(r.get("LAWD_CD")),
                address=address,
                bonbun=bonbun,
                bubun=bubun,
                permit_date=_permit_date(r.get("HNDL_YMD")),
                job_gbn=_clean(r.get("JOB_GBN_NM")),
                use_purp=_clean(r.get("USE_PURP")),
                jimok=_clean(r.get("JIMOK")),
            )
        )
    return out
