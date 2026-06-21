"""diff 엔진 단위 테스트 — NEW/PRICE_CHANGED/REMOVED/REAPPEARED + 디바운스 + 안전규칙."""

from __future__ import annotations

from datetime import timedelta

from tests.conftest import make_dto

from myhouse.constants import ListingStatus, now_kst
from myhouse.core.diff import ListingState, diff_complex


def _state_from(dto, status=ListingStatus.ACTIVE, missing_since=None) -> ListingState:
    return ListingState(
        article_no=dto.article_no,
        status=status,
        price_fingerprint=dto.price_fingerprint,
        cluster_key=dto.cluster_key,
        price_deal=dto.price_deal,
        price_rent=dto.price_rent,
        missing_since=missing_since,
    )


def test_new_listing():
    now = now_kst()
    inc = [make_dto("1")]
    d = diff_complex("111", inc, {}, now=now, removal_debounce_hours=20, fetch_complete=True)
    assert len(d.new) == 1
    assert d.new[0].article_no == "1"
    assert not d.price_changed and not d.removed


def test_seen_unchanged():
    now = now_kst()
    dto = make_dto("1", price_deal=158000)
    existing = {"1": _state_from(dto)}
    d = diff_complex(
        "111", [dto], existing, now=now, removal_debounce_hours=20, fetch_complete=True
    )
    assert d.seen and not d.new and not d.price_changed


def test_price_changed_records_old():
    now = now_kst()
    old = make_dto("1", price_deal=158000)
    new = make_dto("1", price_deal=152000)
    existing = {"1": _state_from(old)}
    d = diff_complex(
        "111", [new], existing, now=now, removal_debounce_hours=20, fetch_complete=True
    )
    assert len(d.price_changed) == 1
    op = d.price_changed[0]
    assert op.old_price_deal == 158000
    assert op.dto.price_deal == 152000


def test_disappearance_becomes_pending_not_removed():
    now = now_kst()
    dto = make_dto("1")
    existing = {"1": _state_from(dto, status=ListingStatus.ACTIVE)}
    d = diff_complex("111", [], existing, now=now, removal_debounce_hours=20, fetch_complete=True)
    assert d.pending_removal and not d.removed


def test_removed_after_debounce():
    now = now_kst()
    dto = make_dto("1")
    existing = {
        "1": _state_from(
            dto, status=ListingStatus.PENDING_REMOVAL, missing_since=now - timedelta(hours=25)
        )
    }
    d = diff_complex("111", [], existing, now=now, removal_debounce_hours=20, fetch_complete=True)
    assert len(d.removed) == 1
    assert d.removed[0].old_price_deal == dto.price_deal


def test_not_removed_before_debounce():
    now = now_kst()
    dto = make_dto("1")
    existing = {
        "1": _state_from(
            dto, status=ListingStatus.PENDING_REMOVAL, missing_since=now - timedelta(hours=5)
        )
    }
    d = diff_complex("111", [], existing, now=now, removal_debounce_hours=20, fetch_complete=True)
    assert not d.removed  # 아직 디바운스 미충족 → 계속 PENDING


def test_safety_skip_removal_when_fetch_incomplete():
    """수집 불완전(차단/타임아웃)이면 사라진 매물을 삭제 판정하지 않는다."""
    now = now_kst()
    dto = make_dto("1")
    existing = {
        "1": _state_from(
            dto, status=ListingStatus.PENDING_REMOVAL, missing_since=now - timedelta(hours=99)
        )
    }
    d = diff_complex("111", [], existing, now=now, removal_debounce_hours=20, fetch_complete=False)
    assert not d.removed and not d.pending_removal


def test_reappeared():
    now = now_kst()
    dto = make_dto("1")
    existing = {"1": _state_from(dto, status=ListingStatus.PENDING_REMOVAL, missing_since=now)}
    d = diff_complex(
        "111", [dto], existing, now=now, removal_debounce_hours=20, fetch_complete=True
    )
    assert len(d.reappeared) == 1
    assert not d.removed


def test_duplicate_incoming_article_collapsed():
    now = now_kst()
    dto = make_dto("1")
    d = diff_complex("111", [dto, dto], {}, now=now, removal_debounce_hours=20, fetch_complete=True)
    assert len(d.new) == 1
