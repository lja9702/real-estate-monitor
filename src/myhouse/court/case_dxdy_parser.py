"""법원경매 사건 기일내역(selectCsDtlDxdyDts) → 물건 결과(매각/유찰/취하…) 도출.

forward 검색(client.fetch_auctions)은 미래 매각기일만 돌려줘 종결(매각·취하)이나 유찰 후
재공고를 못 잡는다 — 매각기일이 지나면 그 행은 DB 에 '지난'으로 박제된다. 매각기일이 지난
물건은 이 사건상세 기일내역을 따로 조회해 실제 결과를 확정한다(core/auction_collector 의 정합 패스).

응답 `data.dlt_dxdyDtsLst[]` (라이브 검증 2026-06, 서울서부 2025타경1678):
  dxdyTime("2026.06.23(10:00)"), auctnDxdyKndNm(매각기일/매각결정기일/대금지급기한),
  dxdyRslt(매각/유찰/미납/변경/취하 … 매각이면 "매각<br />(2,236,524,000원)"로 낙찰가 포함),
  tsLwsDspslPrc("1,688,000,000원" 해당 기일 최저가), dspslGdsSeq(물건일련 — 한 사건 다물건 구분).
한 물건의 기일은 여러 회차다(유찰→재공고, 매각→미납→재매각). 가장 늦은 '확정된' 회차가 현재 결과.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

# 물건 결과 코드(Auction.outcome). None = 미확정(아직 진행중/예정).
SOLD = "sold"  # 매각(낙찰)
FAILED = "failed"  # 유찰 또는 대금미납에 따른 재매각
WITHDRAWN = "withdrawn"  # 취하·취소·기각·각하·정지 등 종국
CHANGED = "changed"  # 기일 변경·연기

_KIND_SALE = "매각기일"  # 입찰 회차(매각결정기일·대금지급기한과 구분)
_KIND_PAYMENT = "대금지급기한"

_DATE_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")
_WON_RE = re.compile(r"([\d,]+)\s*원")


class AuctionDateEvent(BaseModel):
    """기일 1행."""

    date: str | None  # ISO 'YYYY-MM-DD'
    kind: str  # auctnDxdyKndNm
    result: str  # dxdyRslt 원문(HTML 태그 제거)
    low_price_manwon: int | None = None  # tsLwsDspslPrc(만원)
    item_seq: str | None = None  # dspslGdsSeq


class AuctionOutcome(BaseModel):
    """한 물건의 정합 결과(가장 늦은 확정 회차 기준)."""

    outcome: str | None  # SOLD/FAILED/WITHDRAWN/CHANGED 또는 None(미확정)
    label: str  # 사람용 라벨("매각"·"유찰"·"재매각(대금미납)"·"취하"·"변경"·"진행중")
    outcome_date: str | None = None  # 확정 회차 날짜
    final_bid_manwon: int | None = None  # 낙찰가(SOLD)
    next_sale_date: str | None = None  # 재공고된 다음 매각기일(FAILED/CHANGED)
    next_min_bid_manwon: int | None = None  # 다음 회차 최저가


def _iso_date(dxdy_time: str | None) -> str | None:
    if not dxdy_time:
        return None
    m = _DATE_RE.search(dxdy_time)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _won_to_manwon(raw: str | None) -> int | None:
    if not raw:
        return None
    m = _WON_RE.search(raw.replace("<br />", " ").replace("<br/>", " "))
    if not m:
        return None
    won = int(m.group(1).replace(",", ""))
    return won // 10000 if won > 0 else None


def _strip_tags(text: str | None) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def parse_case_dxdy(payload: dict) -> list[AuctionDateEvent]:
    """selectCsDtlDxdyDts 응답 → 기일 이벤트 리스트(원문 그대로, 날짜 오름차순 아님)."""
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = (data or {}).get("dlt_dxdyDtsLst") if isinstance(data, dict) else None
    out: list[AuctionDateEvent] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append(
            AuctionDateEvent(
                date=_iso_date(row.get("dxdyTime")),
                kind=(row.get("auctnDxdyKndNm") or "").strip(),
                result=_strip_tags(row.get("dxdyRslt")),
                low_price_manwon=_won_to_manwon(row.get("tsLwsDspslPrc")),
                item_seq=(str(row.get("dspslGdsSeq")).strip() if row.get("dspslGdsSeq") else None),
            )
        )
    return out


def _classify(result: str) -> str | None:
    """기일 결과 원문 → 결과 코드. 미정('')·미해석은 None."""
    t = result
    if not t:
        return None
    if "불허" in t:  # 매각불허가 → 재매각
        return FAILED
    if "매각" in t or "낙찰" in t or "허가" in t:  # 매각/낙찰/매각허가결정
        return SOLD
    if "유찰" in t:
        return FAILED
    if "미납" in t:  # 대금미납 → 재매각
        return FAILED
    if any(k in t for k in ("취하", "취소", "기각", "각하", "정지", "배당", "종결", "완료")):
        return WITHDRAWN
    if any(k in t for k in ("변경", "연기", "추후")):
        return CHANGED
    return None


_LABEL = {
    SOLD: "매각",
    FAILED: "유찰",
    WITHDRAWN: "취하",
    CHANGED: "변경",
}


def derive_outcome(
    events: list[AuctionDateEvent],
    item_seq: str | None = None,
    *,
    today_iso: str | None = None,
) -> AuctionOutcome:
    """기일내역에서 현재 결과를 도출. item_seq 가 주어지면 그 물건의 기일만 본다.

    규칙: '확정된' 회차(매각/유찰/미납/취하/변경 결과가 찍힌 기일) 중 날짜가 가장 늦은 것이
    현재 상태다. 매각 후 대금미납이면 미납 회차가 더 늦으므로 재매각(FAILED)으로 뒤집힌다.
    FAILED/CHANGED 면 빈 결과의 미래 매각기일을 다음 기일로 함께 돌려준다(재활성용).
    """
    evs = [e for e in events if item_seq is None or e.item_seq is None or e.item_seq == item_seq]
    evs = [e for e in evs if e.date]

    def _next_open_sale(after: str) -> AuctionDateEvent | None:
        """after(및 오늘) 이후의, 결과가 아직 안 찍힌 매각기일(=재공고된 다음 회차) 중 가장 이른 것.

        today_iso 가 주어지면 이미 지난 매각기일은 '다음 회차'로 보지 않는다 — 과거 날짜로 재활성돼
        잘못된 '다음 매각' 알림이 나가고 outcome 미확정이라 매 실행 재정합되는 루프를 막는다.
        """
        floor = max(after, today_iso or "")
        future = sorted(
            (e for e in evs if e.kind == _KIND_SALE and not e.result and e.date and e.date > floor),
            key=lambda e: e.date or "",
        )
        return future[0] if future else None

    # 확정 회차: 결과가 해석되는 매각기일/대금지급기한.
    resolved = [
        (e, _classify(e.result))
        for e in evs
        if e.kind in (_KIND_SALE, _KIND_PAYMENT) and _classify(e.result) is not None
    ]
    if not resolved:
        # 확정 회차 없음 = 아직 진행 전/예정. 다만 매각기일이 미래로 잡혀 있으면 동기화용으로 동봉.
        nxt = _next_open_sale("")
        return AuctionOutcome(
            outcome=None,
            label="진행중",
            next_sale_date=nxt.date if nxt else None,
            next_min_bid_manwon=nxt.low_price_manwon if nxt else None,
        )

    latest_event, code = max(resolved, key=lambda pair: pair[0].date or "")

    # 빈 결과의 미래 매각기일 = 재공고된 다음 회차.
    nxt = _next_open_sale(latest_event.date or "")

    if code == SOLD:
        return AuctionOutcome(
            outcome=SOLD,
            label="매각",
            outcome_date=latest_event.date,
            final_bid_manwon=_won_to_manwon(latest_event.result),
        )
    if code == WITHDRAWN:
        return AuctionOutcome(outcome=WITHDRAWN, label="취하", outcome_date=latest_event.date)

    # FAILED(유찰/미납) 또는 CHANGED(변경/연기): 다음 회차가 있으면 재활성 정보 동봉.
    label = "재매각(대금미납)" if (code == FAILED and "미납" in latest_event.result) else _LABEL[code]
    return AuctionOutcome(
        outcome=code,
        label=label,
        outcome_date=latest_event.date,
        next_sale_date=nxt.date if nxt else None,
        next_min_bid_manwon=nxt.low_price_manwon if nxt else None,
    )


__all__ = [
    "AuctionDateEvent",
    "AuctionOutcome",
    "parse_case_dxdy",
    "derive_outcome",
    "SOLD",
    "FAILED",
    "WITHDRAWN",
    "CHANGED",
]
