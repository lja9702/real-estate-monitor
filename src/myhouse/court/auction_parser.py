"""원시 JSON(경매 물건 1건) → 정규화 AuctionDTO.

courtauction.go.kr `/pgj/pgjsearch/searchControllerMain.on` 응답 data.dlt_srchResult[] 기준
(라이브 검증 2026-06):
  docid(물건 고유키), boCd/jiwonNm(법원), saNo/srnSaNo("2008타경25092"),
  hjguSido/hjguSigu/hjguDong + daepyoLotno(소재지·지번), buldNm(단지명, 빈값 가능),
  gamevalAmt(감정가)·minmaePrice(최저가) **원 단위**, yuchalCnt(유찰), maeGiil(매각기일 YYYYMMDD),
  mulStatcd/jinstatCd/mulJinYn(상태), sclsUtilCd/dspslUsgNm(용도=아파트 식별),
  srchHjguDongCd(법정동 8자리 = 단지 cortar_no[:8] 매칭키).

⚠️ 금액은 원 단위 → 만원으로 환산(÷10000). 단지 매칭은 (srchHjguDongCd, 지번 본번/부번)을
네이버 단지상세(cortarNo[:8], detailAddress)와 비교 — 지번 정규화는 permits 의 normalize_jibun 재사용.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..seoul.permit_parser import normalize_jibun
from .endpoints import APARTMENT_SCLS_CD, APARTMENT_USAGE_NAME
from .errors import CourtAuctionParseError


class AuctionDTO(BaseModel):
    """정규화된 경매 물건 1건 (DB·diff 공유 값 객체). 금액은 만원 단위."""

    auction_key: str  # = docid (물건 단위 고유 자연키)
    court_code: str | None = None  # boCd
    court_name: str | None = None  # jiwonNm
    case_no: str  # 표시 사건번호 "2008타경25092" (srnSaNo)
    case_no_raw: str | None = None  # 내부 saNo "20080130025092"
    item_no: str | None = None  # 물건일련(mokmulSer)
    dong_code: str | None = None  # 법정동 8자리(srchHjguDongCd) — 매칭키
    address: str = ""  # "서울특별시 성북구 정릉동 508-123" (표시용)
    lotno: str | None = None  # 대표지번 "508-123"
    bonbun: str | None = None  # 본번 4자리(매칭키)
    bubun: str | None = None  # 부번 4자리(매칭키)
    building_name: str | None = None  # 단지/건물명(buldNm, 빈값 가능)
    usage_name: str | None = None  # dspslUsgNm("아파트")
    scls_util_cd: str | None = None  # 소분류 용도코드
    appraisal_manwon: int | None = None  # 감정가(만원)
    min_bid_manwon: int | None = None  # 최저매각가(만원)
    min_bid_ratio: int | None = None  # 최저가/감정가 % (유찰 저감 깊이)
    fail_count: int = 0  # 유찰횟수(yuchalCnt)
    sale_date: str | None = None  # 매각기일 ISO 'YYYY-MM-DD'
    status_code: str | None = None  # 물건상태(mulStatcd)
    progress_code: str | None = None  # 진행상태(jinstatCd)
    in_progress: bool = True  # mulJinYn == "Y"
    area_min: float | None = None  # 전용 추정 ㎡(minArea)
    area_max: float | None = None
    remarks: str | None = None  # 물건비고(mulBigo) — 지분매각·위반건축물·대지권 등 권리/하자

    @property
    def is_apartment(self) -> bool:
        return self.usage_name == APARTMENT_USAGE_NAME or self.scls_util_cd == APARTMENT_SCLS_CD

    @property
    def flags(self) -> list[str]:
        """물건비고에서 추출한 핵심 위험/특이 플래그(짧은 라벨)."""
        return extract_flags(self.remarks)


# 물건비고 텍스트 → 짧은 위험/특이 플래그. 매수인이 가장 주의해야 할 항목 위주(부분일치).
# (검색 키워드, 표시 라벨) — 앞쪽이 더 구체적이도록 정렬.
_FLAG_RULES: list[tuple[tuple[str, ...], str]] = [
    (("지분",), "지분매각"),
    (("위반건축물",), "위반건축물"),
    (("대지권 없", "대지권없", "대지지분 없", "대지지분없", "건물만 매각", "건물만매각"), "대지권미포함"),
    (("유치권",), "유치권"),
    (("법정지상권", "분묘기지권"), "법정지상권"),
    (("선순위",), "선순위"),
    (("임차권등기",), "임차권등기"),
    (("별도등기",), "별도등기"),
    (("재매각",), "재매각"),
    (("농지취득", "농취"), "농취증"),
    (("토지거래", "허가구역"), "토지거래허가"),
    (("맹지",), "맹지"),
]


def extract_flags(remarks: str | None) -> list[str]:
    """물건비고에서 위험/특이 플래그 라벨 리스트(중복 제거·순서 유지). 없으면 빈 리스트."""
    if not remarks:
        return []
    out: list[str] = []
    for keys, label in _FLAG_RULES:
        if any(k in remarks for k in keys) and label not in out:
            out.append(label)
    return out


def _clean(value: object) -> str | None:
    """문자열 정리. None/빈/'-'/'null' → None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ("-", "null", "None"):
        return None
    return s


def _amount_manwon(raw: object) -> int | None:
    """원 단위 금액 문자열 → 만원 단위 정수. '0'/빈값 → None."""
    s = _clean(raw)
    if s is None:
        return None
    digits = s.replace(",", "")
    if not digits.lstrip("-").isdigit():
        return None
    won = int(digits)
    return won // 10000 if won > 0 else None


def _float(raw: object) -> float | None:
    s = _clean(raw)
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _ymd_iso(raw: object) -> str | None:
    """'20260625' → '2026-06-25'. 불완전하면 None."""
    s = _clean(raw)
    if s is None or not s.isdigit() or len(s) != 8:
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _ratio(min_won: object, appraisal_won: object) -> int | None:
    """최저가/감정가 백분율(정수). 둘 중 하나라도 결손이면 None."""
    a = _clean(appraisal_won)
    m = _clean(min_won)
    if not (a and m):
        return None
    try:
        av = int(a.replace(",", ""))
        mv = int(m.replace(",", ""))
    except ValueError:
        return None
    if av <= 0:
        return None
    return round(mv / av * 100)


def _build_address(row: dict) -> str:
    parts = [
        _clean(row.get("hjguSido")),
        _clean(row.get("hjguSigu")),
        _clean(row.get("hjguDong")),
        _clean(row.get("daepyoLotno")),
    ]
    return " ".join(p for p in parts if p)


def extract_rows(payload: dict) -> list[dict]:
    """응답에서 data.dlt_srchResult[] 추출. data 없으면 ParseError, 결과없음은 빈 리스트."""
    if not isinstance(payload, dict):
        raise CourtAuctionParseError(f"경매 검색 응답이 dict 아님: {type(payload)}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise CourtAuctionParseError(f"경매 검색 응답에 data 없음: keys={sorted(payload)[:12]}")
    rows = data.get("dlt_srchResult")
    if rows is None:
        return []  # totalCnt 0 — 검색결과 없음(에러 아님)
    if not isinstance(rows, list):
        raise CourtAuctionParseError(f"dlt_srchResult 가 list 아님: {type(rows)}")
    return rows


def parse_auction_row(row: dict) -> AuctionDTO | None:
    """물건 1행 → AuctionDTO. 고유키(docid)/사건번호 결손이면 None(skip)."""
    docid = _clean(row.get("docid"))
    case_no = _clean(row.get("srnSaNo")) or _clean(row.get("printCsNo"))
    if not (docid and case_no):
        return None

    lotno = _clean(row.get("daepyoLotno"))
    jibun = normalize_jibun(lotno) if lotno else None
    bonbun, bubun = (jibun[0], jibun[1]) if jibun else (None, None)

    return AuctionDTO(
        auction_key=docid,
        court_code=_clean(row.get("boCd")),
        court_name=_clean(row.get("jiwonNm")),
        case_no=case_no,
        case_no_raw=_clean(row.get("saNo")),
        item_no=_clean(row.get("mokmulSer")) or _clean(row.get("maemulSer")),
        dong_code=_clean(row.get("srchHjguDongCd")),
        address=_build_address(row),
        lotno=lotno,
        bonbun=bonbun,
        bubun=bubun,
        building_name=_clean(row.get("buldNm")),
        usage_name=_clean(row.get("dspslUsgNm")),
        scls_util_cd=_clean(row.get("sclsUtilCd")),
        appraisal_manwon=_amount_manwon(row.get("gamevalAmt")),
        min_bid_manwon=_amount_manwon(row.get("minmaePrice")),
        min_bid_ratio=_ratio(row.get("minmaePrice"), row.get("gamevalAmt")),
        fail_count=int(_clean(row.get("yuchalCnt")) or 0),
        sale_date=_ymd_iso(row.get("maeGiil")),
        status_code=_clean(row.get("mulStatcd")),
        progress_code=_clean(row.get("jinstatCd")),
        in_progress=_clean(row.get("mulJinYn")) == "Y",
        area_min=_float(row.get("minArea")),
        area_max=_float(row.get("maxArea")),
        remarks=_clean(row.get("mulBigo")),
    )


def parse_auctions(payload: dict) -> list[AuctionDTO]:
    """경매 물건검색 응답 → AuctionDTO 리스트. 키 결손 행은 조용히 skip."""
    out: list[AuctionDTO] = []
    for row in extract_rows(payload):
        if not isinstance(row, dict):
            continue
        dto = parse_auction_row(row)
        if dto is not None:
            out.append(dto)
    return out
