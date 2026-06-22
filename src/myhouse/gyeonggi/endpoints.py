"""과천시청(gccity.go.kr) 토지거래허가내역 게시판 URL·식별자·법정동 매핑.

⚠️ 비공식(전자정부 표준프레임워크 게시판) 엔드포인트. wire 지식을 이 파일에 모은다.
  - 목록 list.do?ptIdx=259&mId=0305030000 → 월별 글(goTo.view('list', bIdx, '259', mId))
  - 상세 view.do?bIdx=…&ptIdx=259        → 첨부 fn_egov_downFile('atchFileId','fileSn')
  - 다운로드 /cmm/fms/FileDown.do?atchFileId=…&fileSn=… → 월별 HWP(application/x-msdownload)
글은 매월 1건("토지거래계약 허가사항(YYYY.M.)"), 데이터는 HWP PrvText 스트림에 표로 들어있다.
"""

from __future__ import annotations

GCCITY_BASE = "https://www.gccity.go.kr"
BOARD_LIST_PATH = "/dept/bbs/list.do"
BOARD_VIEW_PATH = "/dept/bbs/view.do"
FILE_DOWN_PATH = "/cmm/fms/FileDown.do"

# 토지거래허가내역 게시판 식별자 (도시/부동산 > 부동산 메뉴)
PERMIT_PT_IDX = "259"
PERMIT_M_ID = "0305030000"

GWACHEON_SGG_CD = "41290"  # 과천시 시군구 코드(법정동코드 앞 5자리)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 과천시 법정동명 → 법정동코드(10자리). 허가내역의 '별양동 3' 같은 동명을 단지 cortar_no 와
# 매칭하기 위한 표. 0300/0700/0800/0900/1000 은 추적 단지 cortar_no 로 검증됨(매칭은 이 동들만
# 일어난다). 나머지는 표준 과천 법정동코드(best-effort) — 미추적 동이라 잘못돼도 오매칭은 없다.
GWACHEON_DONG_CORTAR: dict[str, str] = {
    "관문동": "4129010100",  # best-effort
    "문원동": "4129010200",  # best-effort
    "갈현동": "4129010300",  # verified
    "막계동": "4129010400",  # best-effort
    "주암동": "4129010500",  # best-effort
    "과천동": "4129010600",  # best-effort
    "중앙동": "4129010700",  # verified
    "원문동": "4129010800",  # verified
    "별양동": "4129010900",  # verified
    "부림동": "4129011000",  # verified
}


def board_list_url() -> str:
    return f"{GCCITY_BASE}{BOARD_LIST_PATH}"


def board_view_url() -> str:
    return f"{GCCITY_BASE}{BOARD_VIEW_PATH}"


def file_down_url() -> str:
    return f"{GCCITY_BASE}{FILE_DOWN_PATH}"


def board_referer() -> str:
    return f"{GCCITY_BASE}{BOARD_LIST_PATH}?ptIdx={PERMIT_PT_IDX}&mId={PERMIT_M_ID}"
