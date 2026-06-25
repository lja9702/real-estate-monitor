"""사건 기일내역 파서·결과도출 — 라이브 검증된 실제 페이로드 픽스처 기반.

HANGARAM = 서울서부 2025타경1678 (probe 2026-06-25 실응답). 매각→미납→유찰→매각(22.36억) 이력.
"""

from __future__ import annotations

from myhouse.court.case_dxdy_parser import (
    CHANGED,
    FAILED,
    SOLD,
    WITHDRAWN,
    derive_outcome,
    parse_case_dxdy,
)

# 라이브 응답 그대로(서울서부 2025타경1678 물건1) — 매각/유찰/미납 + 낙찰가 검증.
HANGARAM = {
    "data": {
        "dlt_dxdyDtsLst": [
            {"dspslGdsSeq": "1", "tsLwsDspslPrc": "2,110,000,000원",
             "dxdyTime": "2026.02.03(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "매각"},
            {"dspslGdsSeq": "1", "tsLwsDspslPrc": "",
             "dxdyTime": "2026.02.10(14:00)", "auctnDxdyKndNm": "매각결정기일", "dxdyRslt": ""},
            {"dspslGdsSeq": "1", "tsLwsDspslPrc": "",
             "dxdyTime": "2026.03.19(17:00)", "auctnDxdyKndNm": "대금지급기한", "dxdyRslt": "미납"},
            {"dspslGdsSeq": "1", "tsLwsDspslPrc": "2,110,000,000원",
             "dxdyTime": "2026.05.19(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "유찰"},
            {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,688,000,000원",
             "dxdyTime": "2026.06.23(10:00)", "auctnDxdyKndNm": "매각기일",
             "dxdyRslt": "매각<br />(2,236,524,000원)"},
            {"dspslGdsSeq": "1", "tsLwsDspslPrc": "",
             "dxdyTime": "2026.06.30(14:00)", "auctnDxdyKndNm": "매각결정기일", "dxdyRslt": ""},
        ]
    }
}


def test_parse_real_payload() -> None:
    events = parse_case_dxdy(HANGARAM)
    assert len(events) == 6
    e = events[4]
    assert e.date == "2026-06-23"
    assert e.kind == "매각기일"
    assert e.result.startswith("매각")
    assert e.low_price_manwon == 168800  # 1,688,000,000원 ÷ 10000


def test_derive_sold_takes_latest_resolved() -> None:
    """매각→미납→유찰→매각 이력에서 가장 늦은 매각(06.23 22.36억)이 결과."""
    out = derive_outcome(parse_case_dxdy(HANGARAM), item_seq="1", today_iso="2026-06-25")
    assert out.outcome == SOLD
    assert out.label == "매각"
    assert out.outcome_date == "2026-06-23"
    assert out.final_bid_manwon == 223652  # 2,236,524,000 ÷ 10000
    assert out.next_sale_date is None


def _events(rows):
    return parse_case_dxdy({"data": {"dlt_dxdyDtsLst": rows}})


def test_failed_with_reschedule() -> None:
    """유찰 + 미래 매각기일(재공고) → FAILED + 다음기일·다음최저가."""
    rows = [
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,000,000,000원",
         "dxdyTime": "2026.06.01(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "유찰"},
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "800,000,000원",
         "dxdyTime": "2026.07.20(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": ""},
    ]
    out = derive_outcome(_events(rows), item_seq="1", today_iso="2026-06-25")
    assert out.outcome == FAILED
    assert out.label == "유찰"
    assert out.next_sale_date == "2026-07-20"
    assert out.next_min_bid_manwon == 80000


def test_failed_reschedule_ignores_past_sale_date() -> None:
    """재공고 매각기일이 이미 지났으면 next_sale_date 로 잡지 않는다(과거날짜 재활성·재정합 루프 방지)."""
    rows = [
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,000,000,000원",
         "dxdyTime": "2026.06.01(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "유찰"},
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "800,000,000원",
         "dxdyTime": "2026.06.10(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": ""},  # 오늘 이전
    ]
    out = derive_outcome(_events(rows), item_seq="1", today_iso="2026-06-25")
    assert out.outcome == FAILED
    assert out.next_sale_date is None  # 과거 매각기일은 다음 회차로 보지 않음


def test_payment_default_flips_to_remarket() -> None:
    """매각 후 대금미납이 더 늦으면 재매각(FAILED)으로 뒤집힘."""
    rows = [
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,000,000,000원",
         "dxdyTime": "2026.05.01(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "매각<br />(1,200,000,000원)"},
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "",
         "dxdyTime": "2026.06.15(17:00)", "auctnDxdyKndNm": "대금지급기한", "dxdyRslt": "미납"},
    ]
    out = derive_outcome(_events(rows), item_seq="1", today_iso="2026-06-25")
    assert out.outcome == FAILED
    assert out.label == "재매각(대금미납)"
    assert out.outcome_date == "2026-06-15"


def test_withdrawn() -> None:
    rows = [
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,000,000,000원",
         "dxdyTime": "2026.06.01(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "취하"},
    ]
    out = derive_outcome(_events(rows), item_seq="1")
    assert out.outcome == WITHDRAWN
    assert out.label == "취하"


def test_changed_with_next_date() -> None:
    rows = [
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,000,000,000원",
         "dxdyTime": "2026.06.01(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "변경"},
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,000,000,000원",
         "dxdyTime": "2026.07.10(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": ""},
    ]
    out = derive_outcome(_events(rows), item_seq="1", today_iso="2026-06-25")
    assert out.outcome == CHANGED
    assert out.next_sale_date == "2026-07-10"


def test_in_progress_when_no_result() -> None:
    """결과가 아직 안 찍힌(예정) 기일만 있으면 미확정(None)."""
    rows = [
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "1,000,000,000원",
         "dxdyTime": "2026.07.01(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": ""},
    ]
    out = derive_outcome(_events(rows), item_seq="1", today_iso="2026-06-25")
    assert out.outcome is None
    assert out.label == "진행중"
    assert out.next_sale_date == "2026-07-01"  # 미래 매각기일은 동기화용으로 동봉


def test_item_seq_filter() -> None:
    """다른 물건(dspslGdsSeq=2)의 기일은 제외."""
    rows = [
        {"dspslGdsSeq": "2", "tsLwsDspslPrc": "",
         "dxdyTime": "2026.06.20(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "매각<br />(9,000,000,000원)"},
        {"dspslGdsSeq": "1", "tsLwsDspslPrc": "",
         "dxdyTime": "2026.06.01(10:00)", "auctnDxdyKndNm": "매각기일", "dxdyRslt": "유찰"},
    ]
    out = derive_outcome(_events(rows), item_seq="1", today_iso="2026-06-25")
    assert out.outcome == FAILED  # 물건1은 유찰, 물건2 매각은 무시
