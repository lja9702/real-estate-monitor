"""텔레그램 응답 포매터 — 변동/스냅샷/실거래 메시지 구성."""

from __future__ import annotations

from types import SimpleNamespace

from myhouse.constants import RunStatus, TradeType, now_kst
from myhouse.core.collector import ComplexResult, RunResult
from myhouse.core.deal_collector import ComplexDealResult, DealRunResult
from myhouse.core.diff import NEW, PRICE_CHANGED, ComplexDiff, DiffOp
from myhouse.core.on_demand import AddResult, Candidate
from myhouse.naver.parser import ArticleDTO, compute_cluster_key
from myhouse.notify import reply

DASH = "http://localhost:8765"


def _dto(article_no="1", price_deal=158000, trade_type=TradeType.SALE):
    ck = compute_cluster_key("947", "82A", 12, None, "남향", trade_type)
    return ArticleDTO(
        article_no=article_no,
        complex_no="947",
        trade_type=trade_type,
        price_deal=price_deal,
        area_excl=81.0,
        area_name="82A",
        floor_info="12/15",
        floor_num=12,
        direction="남향",
        article_url=f"https://m.land.naver.com/article/info/{article_no}",
        cluster_key=ck,
    )


def _cluster_row(price_min=158000, price_max=160000, **kw):
    base = dict(
        trade_ko="매매",
        trade_type=TradeType.SALE,
        area_excl=81.0,
        floor_num=12,
        floor_info="12/15",
        direction="남향",
        rent_min=None,
        price_min=price_min,
        price_max=price_max,
        realtor_count=2,
        status="ACTIVE",
        article_url="https://m.land.naver.com/article/info/1",
        starred=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _run_result(
    ops, *, new=0, price=0, removed=0, complete=True, error=None, address="서울 서초구 방배동"
):
    cdiff = ComplexDiff("947", complete, ops)
    fetch = SimpleNamespace(complete=complete, raw_count=5)
    cr = ComplexResult(
        "947", "삼호1차", "삼호1차", address=address, diff=cdiff, fetch=fetch, error=error
    )
    return RunResult(
        run_id=1,
        started_at=now_kst(),
        status=RunStatus.SUCCESS,
        complexes=[cr],
        new_count=new,
        price_changed_count=price,
        removed_count=removed,
    )


# ── 단순 메시지 ──────────────────────────────────────────────────────────────
def test_help_and_unknown():
    assert "명령" in reply.format_help()
    assert "/foo" in reply.format_unknown("foo")


def test_not_found_and_candidates():
    assert "찾지 못" in reply.format_not_found("없는단지")
    msg = reply.format_candidates("우성", [Candidate("1", "우성1차"), Candidate("2", "우성2차")])
    assert "우성1차" in msg and "<code>1</code>" in msg


def test_list_empty_and_filled():
    assert "없습니다" in reply.format_list([])
    msg = reply.format_list([("947", "삼호1차")])
    assert "삼호1차" in msg and "947" in msg


# ── /check ───────────────────────────────────────────────────────────────────
def test_check_reply_with_changes_and_snapshot():
    op_new = DiffOp(NEW, "1", _dto().cluster_key, dto=_dto("1", 158000))
    op_price = DiffOp(
        PRICE_CHANGED, "2", _dto().cluster_key, dto=_dto("2", 160000), old_price_deal=158000
    )
    run = _run_result([op_new, op_price], new=1, price=1)
    snap = [_cluster_row()]
    msg = reply.format_check_reply(run, snap, complex_no="947", tracked=True, dashboard_url=DASH)

    assert "삼호1차" in msg
    assert "이번 갱신" in msg and "🆕 신규" in msg and "📉 가격변동" in msg
    assert "▲" in msg  # 가격 상승 표시
    assert "현재 매물" in msg
    assert "/complex/947" in msg
    assert "추적 중" in msg


def test_check_reply_no_change_untracked_tag():
    run = _run_result([], new=0, price=0)
    msg = reply.format_check_reply(run, [], complex_no="947", tracked=False, dashboard_url=DASH)
    assert "변동 없음" in msg
    assert "현재 매물</b> 없음" in msg
    assert "미추적" in msg


def test_check_reply_error():
    run = _run_result([], error="HTTP 429")
    msg = reply.format_check_reply(run, [], complex_no="947", tracked=False, dashboard_url=DASH)
    assert "수집 실패" in msg and "429" in msg


def test_check_reply_incomplete_warns():
    run = _run_result([], complete=False)
    msg = reply.format_check_reply(run, [], complex_no="947", tracked=True, dashboard_url=DASH)
    assert "일부 수집 실패" in msg


# ── /deals ───────────────────────────────────────────────────────────────────
def _deal_row(cancelled=False, is_new=False):
    return SimpleNamespace(
        trade_ko="매매",
        price_deal=250000,
        price_rent=None,
        pyeong_name="82A",
        area_excl=81.0,
        floor=12,
        deal_date="2026-05-23",
        cancelled=cancelled,
        is_new=is_new,
    )


def test_deals_reply():
    result = DealRunResult(
        run_id=1,
        started_at=now_kst(),
        status=RunStatus.SUCCESS,
        complexes=[
            ComplexDealResult("947", "삼호1차", "삼호1차", new_deals=[], cancelled_deals=[])
        ],
        new_count=1,
        cancelled_count=0,
    )
    recent = [_deal_row(is_new=True), _deal_row(cancelled=True)]
    msg = reply.format_deals_reply(
        result, recent, complex_no="947", name="삼호1차", dashboard_url=DASH
    )
    assert "실거래" in msg
    assert "최근 실거래" in msg
    assert "26.05.23" in msg
    assert "25억" in msg  # 250000 만원
    assert "/deals?complex_no=947" in msg
    # 취소 거래는 '최근 실거래' 목록에서 제외(valid 만)
    assert msg.count("82A") == 1


def test_deals_reply_empty():
    result = DealRunResult(run_id=1, started_at=now_kst(), status=RunStatus.SUCCESS, complexes=[])
    msg = reply.format_deals_reply(result, [], complex_no="947", name="삼호1차", dashboard_url=DASH)
    assert "내역이 없습니다" in msg


# ── /add ─────────────────────────────────────────────────────────────────────
def test_add_reply_resolved():
    add = AddResult("947", "삼호1차", name_resolved=True, run=_run_result([]))
    msg = reply.format_add_reply(add, [_cluster_row()], dashboard_url=DASH)
    assert "추적 시작" in msg and "삼호1차" in msg
    assert "정기 수집" in msg
    assert "현재 매물" in msg


def test_add_reply_unresolved_name_suggests_alias():
    add = AddResult("947", "단지 947", name_resolved=False, run=_run_result([]))
    msg = reply.format_add_reply(add, [], dashboard_url=DASH)
    assert "임시로" in msg and "/add 947" in msg
