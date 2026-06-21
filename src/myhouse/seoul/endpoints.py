"""land.seoul.go.kr 토지거래허가 API URL·헤더.

⚠️ 비공식(화면 내부 AJAX) 엔드포인트. wire 지식을 이 파일에 모은다.
  - getSggList   : 자치구 코드 목록(GET)  → result[].sggCd/sggNm
  - getContractList : 자치구별 허가내역(POST) → result[] (ADDRESS/LAWD_CD/BOBN/BUBN/HNDL_YMD…)
조회는 자치구 단위, 기간은 최대 62일(서버 제약).
"""

from __future__ import annotations

LAND_SEOUL_BASE = "https://land.seoul.go.kr"
SGG_LIST_PATH = "/land/common/getSggList.do"
CONTRACT_LIST_PATH = "/land/wsklis/getContractList.do"
CONTRACT_PAGE_PATH = "/land/other/contractStatus.do"  # referer 용

MAX_RANGE_DAYS = 62  # 서버측 기간 제약
SEOUL_SGG_PREFIX = "11"  # 서울 자치구 코드(11xxx)만 이 사이트로 조회 가능

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def sgg_list_url() -> str:
    return f"{LAND_SEOUL_BASE}{SGG_LIST_PATH}"


def contract_list_url() -> str:
    return f"{LAND_SEOUL_BASE}{CONTRACT_LIST_PATH}"


def contract_referer() -> str:
    return f"{LAND_SEOUL_BASE}{CONTRACT_PAGE_PATH}"
