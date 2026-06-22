"""digest 메시지 구성 테스트."""

from __future__ import annotations

from tests.conftest import make_dto

from myhouse.constants import RunStatus, TradeType, now_kst
from myhouse.core.collector import ComplexResult, RunResult
from myhouse.core.diff import NEW, PRICE_CHANGED, REMOVED, ComplexDiff, DiffOp
from myhouse.core.flash import FlashSignal
from myhouse.naver.client import FetchResult
from myhouse.notify.digest import build_digest


def _run_result_with_changes() -> RunResult:
    a = make_dto("1", price_deal=158000)  # 유닛 X (중개사 1)
    b = make_dto("2", price_deal=159000)  # 유닛 X (중개사 2) → 같은 cluster
    c_new = make_dto("3", floor_num=5, price_deal=200000)  # 유닛 Y 가격하락

    cdiff = ComplexDiff(
        "111",
        True,
        [
            DiffOp(NEW, "1", a.cluster_key, dto=a),
            DiffOp(NEW, "2", b.cluster_key, dto=b),
            DiffOp(PRICE_CHANGED, "3", c_new.cluster_key, dto=c_new, old_price_deal=210000),
            DiffOp(REMOVED, "4", "ckX", old_price_deal=99000),
        ],
    )
    cr = ComplexResult(
        complex_no="111",
        label="테스트단지",
        name="한솔마을주공5단지",
        diff=cdiff,
        fetch=FetchResult("111", [], complete=True),
    )
    return RunResult(
        run_id=1,
        started_at=now_kst(),
        status=RunStatus.SUCCESS,
        complexes=[cr],
        new_count=2,
        price_changed_count=1,
        removed_count=1,
        starred_complexes={"111"},  # 관심 단지
    )


def test_digest_contains_sections_and_links():
    msg = build_digest(_run_result_with_changes(), "http://localhost:8765")
    assert "부동산 모니터" in msg
    assert "신규 2" in msg and "가격변동 1" in msg and "거래완료 1" in msg
    assert "한솔마을주공5단지" in msg
    assert "🆕" in msg and "📉" in msg and "✅" in msg
    assert "중개 2곳" in msg  # 같은 유닛 다른 중개사 → 접힘
    assert "★" in msg  # 별표 단지
    assert "▼" in msg  # 가격 하락 화살표
    assert 'href="http://localhost:8765"' in msg
    assert 'href="https://m.land.naver.com/article/info/' in msg


def test_digest_no_change():
    rr = RunResult(run_id=2, started_at=now_kst(), status=RunStatus.SUCCESS, complexes=[])
    msg = build_digest(rr, "http://localhost:8765")
    assert "변동 없음" in msg


# ── 가격밴드(구독자별) 필터 ────────────────────────────────────────────────────
def test_digest_band_keeps_only_in_range_new():
    # 신규 a/b=15.8·15.9억, 가격변동 20억(←21억), 거래완료 9.9억
    msg = build_digest(_run_result_with_changes(), "http://localhost:8765",
                       price_min=150000, price_max=180000)
    assert msg is not None
    assert "신규 2" in msg and "가격변동 0" in msg and "거래완료 0" in msg
    assert "🎯 15억~18억" in msg  # 밴드 라벨
    assert "🆕" in msg
    assert "📉" not in msg and "✅" not in msg  # 밴드 밖은 빠짐


def test_digest_band_keeps_only_removed():
    msg = build_digest(_run_result_with_changes(), "http://localhost:8765",
                       price_min=90000, price_max=100000)
    assert msg is not None
    assert "신규 0" in msg and "거래완료 1" in msg
    assert "✅" in msg and "🆕" not in msg


def test_digest_band_empty_drop_returns_none():
    # 30억 이상 밴드 — 해당 매물 없음
    msg = build_digest(_run_result_with_changes(), "http://localhost:8765",
                       price_min=300000, price_max=None, drop_empty=True)
    assert msg is None


def test_digest_band_empty_no_drop_returns_text():
    msg = build_digest(_run_result_with_changes(), "http://localhost:8765",
                       price_min=300000, price_max=None, drop_empty=False)
    assert msg is not None and "변동 없음" in msg and "🎯 30억↑" in msg


def test_digest_unbounded_matches_global_counts():
    # 밴드 없음 = 기존 전체 동작(신규 2·가격변동 1·거래완료 1)
    msg = build_digest(_run_result_with_changes(), "http://localhost:8765")
    assert "신규 2" in msg and "가격변동 1" in msg and "거래완료 1" in msg
    assert "🎯" not in msg  # 밴드 라벨 없음


# ── 🔥 급매 섹션 ──────────────────────────────────────────────────────────────
def _run_result_with_flash() -> RunResult:
    d = make_dto("3", price_deal=110000)  # 신규이자 급매(하한 12억 대비 11억)
    cdiff = ComplexDiff("111", True, [DiffOp(NEW, "3", d.cluster_key, dto=d)])
    sig = FlashSignal(
        article_no="3", complex_no="111", cluster_key=d.cluster_key,
        trade_type=TradeType.SALE, area_excl=81.0, area_key=81, price_deal=110000,
        prior_floor=120000, drop_amount=10000, drop_pct=8.33, trigger="new",
    )
    cr = ComplexResult(
        complex_no="111", label="테스트단지", name="한솔마을주공5단지",
        diff=cdiff, fetch=FetchResult("111", [], complete=True), flash=[sig],
    )
    return RunResult(
        run_id=1, started_at=now_kst(), status=RunStatus.SUCCESS,
        complexes=[cr], new_count=1, flash_count=1,
    )


def test_digest_flash_section():
    msg = build_digest(_run_result_with_flash(), "http://localhost:8765")
    assert "🔥 급매" in msg       # 섹션 헤더
    assert "🔥급매 1" in msg       # 상단 카운트
    assert "하한 12억" in msg      # 직전 하한가
    assert "8.33" in msg          # 하락률
    assert "[신규]" in msg         # 트리거 태그
    assert "🆕" in msg             # 급매여도 신규 섹션엔 그대로 남음(부분집합 강조)


def test_digest_flash_hidden_when_off():
    msg = build_digest(_run_result_with_flash(), "http://localhost:8765", show_flash=False)
    assert msg is not None
    assert "🔥" not in msg         # 섹션·카운트 모두 숨김
    assert "🆕" in msg             # 신규는 그대로
