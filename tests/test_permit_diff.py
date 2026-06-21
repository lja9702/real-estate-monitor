"""토지거래허가 diff 테스트 — 신규/기존 분류·incoming 중복 제거."""

from __future__ import annotations

from myhouse.core.permit_diff import NEW, SEEN, diff_permits
from myhouse.seoul.permit_parser import PermitDTO


def _permit(key: str, job_gbn: str = "허가") -> PermitDTO:
    return PermitDTO(permit_key=key, sgg_cd="11680", address="강남구 대치동 974", job_gbn=job_gbn)


def test_diff_new_and_seen():
    incoming = [_permit("a"), _permit("b")]
    diff = diff_permits("971", incoming, existing_keys={"a"})
    kinds = {op.dto.permit_key: op.kind for op in diff.ops}
    assert kinds == {"a": SEEN, "b": NEW}
    assert [op.dto.permit_key for op in diff.new] == ["b"]


def test_diff_all_new_when_no_existing():
    diff = diff_permits("971", [_permit("a"), _permit("b")], existing_keys=set())
    assert len(diff.new) == 2


def test_diff_dedup_incoming():
    """같은 permit_key 가 응답에 중복으로 와도 한 번만 처리."""
    diff = diff_permits("971", [_permit("a"), _permit("a")], existing_keys=set())
    assert len(diff.ops) == 1
    assert len(diff.new) == 1


def test_diff_empty():
    diff = diff_permits("971", [], existing_keys={"a"})
    assert diff.ops == []
    assert diff.new == []
