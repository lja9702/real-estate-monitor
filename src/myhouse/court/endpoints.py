"""courtauction.go.kr 신규시스템(WebSquare) 물건상세검색 API URL·헤더·바디.

⚠️ 비공식(화면 내부 XHR) 엔드포인트 — wire 지식을 이 파일에 모은다. 라이브 검증 2026-06.
  ① warmup GET (PGJ151F00 화면) → 세션 쿠키(JSESSIONID 등) 획득
  ② POST searchControllerMain.on (JSON) → data.dlt_srchResult[] 물건 목록
검색은 법원(cortOfcCd)+매각기일 범위(cortStDvs="1") 단위로 하고, 추적단지 지번에
매칭(srchHjguDongCd==cortar_no[:8] + daepyoLotno)되는 물건만 추린다 — permits 와 같은 철학.

주의: POST 에 submissionid/sc-userid 헤더가 없으면 빈 응답이 온다. 용도(아파트) 입력필터는
코드체계가 응답 코드와 달라 0건 위험이 있어, 무필터로 받아 응답에서 로컬 필터한다.
"""

from __future__ import annotations

COURT_AUCTION_BASE = "https://www.courtauction.go.kr"
WARMUP_PATH = "/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml&pgjId=151F00"
SEARCH_PATH = "/pgj/pgjsearch/searchControllerMain.on"
COURTS_PATH = "/pgj/pgjComm/selectCortOfcCdLst.on"
CASE_DETAIL_PATH = "/pgj/pgj15A/selectAuctnCsSrchRslt.on"  # 사건 단위 상세(기일이력 등) — 추후

# POST 필수 헤더값 — 빠지면 빈 응답.
SEARCH_SUBMISSION_ID = "mf_wfm_mainFrame_sbm_selectGdsDtlSrch"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 아파트 식별값 — 응답 dlt_srchResult 행의 sclsUtilCd / dspslUsgNm 기준(로컬 필터).
APARTMENT_SCLS_CD = "20104"
APARTMENT_USAGE_NAME = "아파트"


def warmup_url() -> str:
    return f"{COURT_AUCTION_BASE}{WARMUP_PATH}"


def search_url() -> str:
    return f"{COURT_AUCTION_BASE}{SEARCH_PATH}"


def courts_url() -> str:
    return f"{COURT_AUCTION_BASE}{COURTS_PATH}"


def search_referer() -> str:
    return warmup_url()


def build_search_body(
    court_code: str,
    begin_ymd: str,
    end_ymd: str,
    *,
    page_no: int = 1,
    page_size: int = 40,
) -> dict:
    """법원+매각기일 범위 물건상세검색 바디(cortStDvs='1', 용도 무필터).

    begin/end 는 'YYYYMMDD'. court_code 가 빈 문자열이면 전국(양 많음).
    """
    return {
        "dma_pageInfo": {
            "pageNo": page_no,
            "pageSize": page_size,
            "bfPageNo": "",
            "startRowNo": "",
            "totalCnt": "",
            "totalYn": "Y",
            "groupTotalCount": "",
        },
        "dma_srchGdsDtlSrchInfo": {
            "rletDspslSpcCondCd": "",
            "bidDvsCd": "000331",  # 기일입찰
            "mvprpRletDvsCd": "00031R",  # 부동산
            "cortAuctnSrchCondCd": "0004601",
            "rprsAdongSdCd": "",
            "rprsAdongSggCd": "",
            "rprsAdongEmdCd": "",
            "rdnmSdCd": "",
            "rdnmSggCd": "",
            "rdnmNo": "",
            "mvprpDspslPlcAdongSdCd": "",
            "mvprpDspslPlcAdongSggCd": "",
            "mvprpDspslPlcAdongEmdCd": "",
            "rdDspslPlcAdongSdCd": "",
            "rdDspslPlcAdongSggCd": "",
            "rdDspslPlcAdongEmdCd": "",
            "cortOfcCd": court_code,
            "jdbnCd": "",
            "execrOfcDvsCd": "",
            "lclDspslGdsLstUsgCd": "",  # 용도 무필터(로컬에서 아파트 필터)
            "mclDspslGdsLstUsgCd": "",
            "sclDspslGdsLstUsgCd": "",
            "cortAuctnMbrsId": "",
            "aeeEvlAmtMin": "",
            "aeeEvlAmtMax": "",
            "lwsDspslPrcRateMin": "",
            "lwsDspslPrcRateMax": "",
            "flbdNcntMin": "",
            "flbdNcntMax": "",
            "objctArDtsMin": "",
            "objctArDtsMax": "",
            "mvprpArtclKndCd": "",
            "mvprpArtclNm": "",
            "mvprpAtchmPlcTypCd": "",
            "notifyLoc": "off",
            "lafjOrderBy": "",
            "pgmId": "PGJ151F01",
            "csNo": "",
            "cortStDvs": "1",  # 법원/날짜 검색="1", 지역검색="2"
            "statNum": 1,
            "bidBgngYmd": begin_ymd,
            "bidEndYmd": end_ymd,
            "dspslDxdyYmd": "",
            "fstDspslHm": "",
            "scndDspslHm": "",
            "thrdDspslHm": "",
            "fothDspslHm": "",
            "dspslPlcNm": "",
            "lwsDspslPrcMin": "",
            "lwsDspslPrcMax": "",
            "grbxTypCd": "",
            "gdsVendNm": "",
            "fuelKndCd": "",
            "carMdyrMax": "",
            "carMdyrMin": "",
            "carMdlNm": "",
            "sideDvsCd": "",
        },
    }
