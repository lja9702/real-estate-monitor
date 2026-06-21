"""원시 JSON(매물 1건) → 정규화된 ArticleDTO.

new.land.naver.com `/api/articles/complex/{complexNo}` 응답의 articleList[] 원소 기준:
  articleNo(매물번호), tradeTypeCode(A1/B1/B2), dealOrWarrantPrc(매매가/보증금, "6억 5,000" 문자열),
  rentPrc(월세, 문자열), area1/area2(공급/전용 ㎡ 정수), areaName(평형 "82A"), floorInfo("2/12"),
  direction(향), buildingName(동), articleConfirmYmd("20260620"), realtorName(중개사),
  articleFeatureDesc(특징), sameAddrCnt(동일주소 매물 수).

응답 구조가 바뀌면 NaverParseError 로 시끄럽게 실패한다(쓰레기 저장 방지).
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel

from ..constants import TRADE_CODE_TO_TYPE, TradeType
from ..util import parse_confirm_date, parse_float, parse_floor
from .errors import NaverParseError


class ArticleDTO(BaseModel):
    """정규화된 매물 1건 (DB·diff 가 공유하는 값 객체)."""

    article_no: str
    complex_no: str
    trade_type: TradeType
    price_deal: int | None = None      # 매매가/보증금 (만원)
    price_rent: int | None = None      # 월세 (만원)
    area_excl: float | None = None     # 전용면적 ㎡
    area_supply: float | None = None   # 공급면적 ㎡
    area_name: str | None = None       # 평형 라벨 "82A"
    floor_info: str | None = None
    floor_num: int | None = None
    direction: str | None = None
    dong: str | None = None
    feature_desc: str | None = None
    realtor_name: str | None = None
    confirm_date: str | None = None
    article_url: str | None = None
    cluster_key: str = ""

    @property
    def price_fingerprint(self) -> str:
        return f"{self.price_deal}|{self.price_rent}"


def parse_korean_price(value: object) -> int | None:
    """'6억 5,000' → 65000 (만원), '25억' → 250000, '150' → 150. 실패 시 None."""
    if value is None or value == "":
        return None
    s = str(value).replace(" ", "")
    total = 0
    if "억" in s:
        eok, _, rest = s.partition("억")
        try:
            total += int(eok.replace(",", "")) * 10000
        except ValueError:
            return None
        s = rest
    s = s.replace(",", "")
    if s:
        try:
            total += int(s)
        except ValueError:
            return None
    return total


def compute_cluster_key(
    complex_no: str,
    area_name: str | None,
    floor_num: int | None,
    floor_info: str | None,
    direction: str | None,
    trade_type: TradeType,
) -> str:
    """같은 물리적 유닛(동일 단지·평형·층·향·거래유형)을 묶는 키.

    가격은 의도적으로 제외 — 중개사별 호가 차이로 클러스터가 쪼개지는 것을 막는다.
    평형(areaName, 예 '82A')이 면적보다 안정적인 유닛 식별자라 이를 우선 사용한다.
    """
    area_part = (area_name or "?").strip()
    if floor_num is not None:
        floor_part = str(floor_num)
    elif floor_info:
        floor_part = str(floor_info).split("/", 1)[0].strip() or "?"
    else:
        floor_part = "?"
    dir_part = (direction or "?").strip()
    raw = f"{complex_no}|{area_part}|{floor_part}|{dir_part}|{trade_type.value}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def parse_article(raw: dict, complex_no: str) -> ArticleDTO:
    """원시 매물 dict → ArticleDTO. 필수 필드 부재 시 NaverParseError."""
    article_no = raw.get("articleNo")
    if not article_no:
        raise NaverParseError(f"매물번호(articleNo) 없음: keys={sorted(raw)[:12]}")
    article_no = str(article_no)

    code = raw.get("tradeTypeCode")
    trade_type = TRADE_CODE_TO_TYPE.get(str(code)) if code is not None else None
    if trade_type is None:
        name = raw.get("tradeTypeName")
        for ko, tt in {"매매": TradeType.SALE, "전세": TradeType.JEONSE, "월세": TradeType.WOLSE}.items():
            if name == ko:
                trade_type = tt
                break
    if trade_type is None:
        raise NaverParseError(
            f"거래유형 해석 불가: tradeTypeCode={code!r} tradeTypeName={raw.get('tradeTypeName')!r}"
        )

    price_deal = parse_korean_price(raw.get("dealOrWarrantPrc"))
    price_rent = parse_korean_price(raw.get("rentPrc")) or None
    area_supply = parse_float(raw.get("area1"))
    area_excl = parse_float(raw.get("area2"))
    area_name = (raw.get("areaName") or None) or None
    floor_info, floor_num = parse_floor(raw.get("floorInfo"))
    direction = (raw.get("direction") or None) or None
    dong = (raw.get("buildingName") or None) or None
    feature_desc = (raw.get("articleFeatureDesc") or None) or None
    realtor_name = (raw.get("realtorName") or None) or None
    confirm_date = parse_confirm_date(raw.get("articleConfirmYmd"))

    cluster_key = compute_cluster_key(
        complex_no, area_name, floor_num, floor_info, direction, trade_type
    )

    return ArticleDTO(
        article_no=article_no,
        complex_no=complex_no,
        trade_type=trade_type,
        price_deal=price_deal,
        price_rent=price_rent,
        area_excl=area_excl,
        area_supply=area_supply,
        area_name=area_name,
        floor_info=floor_info,
        floor_num=floor_num,
        direction=direction,
        dong=dong,
        feature_desc=feature_desc,
        realtor_name=realtor_name,
        confirm_date=confirm_date,
        article_url=f"https://m.land.naver.com/article/info/{article_no}",
        cluster_key=cluster_key,
    )


def extract_article_body(payload: dict) -> list[dict]:
    """응답에서 매물 배열(articleList) 추출. 구조 불일치 시 NaverParseError."""
    if not isinstance(payload, dict):
        raise NaverParseError(f"응답이 dict 아님: {type(payload)}")
    body = payload.get("articleList")
    if body is None:
        raise NaverParseError(f"매물 배열(articleList) 없음: keys={sorted(payload)[:12]}")
    if not isinstance(body, list):
        raise NaverParseError(f"articleList 가 list 아님: {type(body)}")
    return body


def has_more(payload: dict) -> bool:
    """다음 페이지 존재 여부 (isMoreData)."""
    return bool(payload.get("isMoreData"))
