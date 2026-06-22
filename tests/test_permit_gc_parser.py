"""과천 토지거래허가 파서/라우팅 테스트 — HWP PrvText 표 파싱·복수지번·산 스킵·동매핑·키안정성."""

from __future__ import annotations

import pytest

from myhouse.core.permit_collector import _is_supported_zone
from myhouse.gyeonggi.errors import GyeonggiParseError
from myhouse.gyeonggi.permit_parser import (
    parse_board_list,
    parse_gwacheon_prvtext,
    parse_view_attachment,
)

# 실제 HWP PrvText 구조 기반(셀=<…>). 1행 단일지번 / 2행 본번-부번 / 3행 복수지번 /
# 4행 한 칸에 두 동 / 5행 산(임야→스킵) / 6행 비주거(상업용·파서는 보존, 필터는 수집기 담당).
PRVTEXT = "\n".join(
    [
        "■ 토지거래업무처리규정〔별지 제3호서식〕",
        "토지거래계약 허가사항",
        "<연번><시군구 지번><지목><허가년월일><이용목적><착수><준공><이용의무종료일><신고고발>",
        "<1><경기도 과천시 별양동 3><대><2026.03.04.><주거용><2026.04.><><취득일로부터 2년><->",
        "<2><경기도 과천시 과천동 376-11><대><2026.03.06.><주거용><2026.03.><><취득일로부터 2년><->",
        "<3><경기도 과천시 중앙동 97, 99, 100, 101><대><2026.03.10.><주거용><2026.05.><><2년><->",
        "<4><경기도 과천시 원문동 10 별양동 91><대><2026.03.12.><주거용><2026.05.><><2년><->",
        "<5><경기도 과천시 문원동 산12-3><임야><2026.03.15.><사업용><2026.05.><><2년><->",
        "<6><경기도 과천시 부림동 96><대><2026.03.17.><상업용><2026.05.><><2년><->",
    ]
)


def test_parse_single_parcel():
    dtos = parse_gwacheon_prvtext(PRVTEXT, 2026, 3)
    byaddr = {d.address: d for d in dtos}
    d = byaddr["과천시 별양동 3"]
    assert d.sgg_cd == "41290"
    assert d.lawd_cd == "4129010900"  # 별양동
    assert (d.bonbun, d.bubun) == ("0003", "0000")
    assert d.permit_date == "2026-03-04"
    assert d.use_purp == "주거용"
    assert d.jimok == "대"
    assert d.job_gbn == "허가"  # '허가사항' 서식 — 모두 허가
    assert d.granted is True


def test_bonbun_bubun_split():
    d = {x.address: x for x in parse_gwacheon_prvtext(PRVTEXT, 2026, 3)}["과천시 과천동 376-11"]
    assert (d.bonbun, d.bubun) == ("0376", "0011")
    assert d.lawd_cd == "4129010600"  # 과천동


def test_multi_jibun_one_cell_expands():
    """'중앙동 97, 99, 100, 101' → 4건으로 분해, 모두 중앙동 코드."""
    addrs = {d.address for d in parse_gwacheon_prvtext(PRVTEXT, 2026, 3)}
    for jb in ("97", "99", "100", "101"):
        assert f"과천시 중앙동 {jb}" in addrs
    jung = [d for d in parse_gwacheon_prvtext(PRVTEXT, 2026, 3) if d.address.startswith("과천시 중앙동")]
    assert {d.lawd_cd for d in jung} == {"4129010700"}


def test_two_dong_in_one_cell():
    """'원문동 10 별양동 91' → 두 동·두 지번으로 분해."""
    byaddr = {d.address: d for d in parse_gwacheon_prvtext(PRVTEXT, 2026, 3)}
    assert byaddr["과천시 원문동 10"].lawd_cd == "4129010800"
    assert byaddr["과천시 별양동 91"].lawd_cd == "4129010900"


def test_san_parcel_skipped():
    """임야(산) 지번은 아파트가 아니므로 제외."""
    addrs = {d.address for d in parse_gwacheon_prvtext(PRVTEXT, 2026, 3)}
    assert not any("문원동" in a for a in addrs)


def test_non_residential_preserved_for_collector_filter():
    """파서는 use_purp 를 보존하고, 주거용 필터는 수집기가 적용한다."""
    d = {x.address: x for x in parse_gwacheon_prvtext(PRVTEXT, 2026, 3)}["과천시 부림동 96"]
    assert d.use_purp == "상업용"


def test_total_count_and_all_granted():
    dtos = parse_gwacheon_prvtext(PRVTEXT, 2026, 3)
    # 1 + 1 + 4(중앙동) + 2(원문/별양) + 0(산) + 1 = 9
    assert len(dtos) == 9
    assert all(d.job_gbn == "허가" and d.sgg_cd == "41290" for d in dtos)


def test_permit_key_stable_and_unique():
    a = parse_gwacheon_prvtext(PRVTEXT, 2026, 3)
    b = parse_gwacheon_prvtext(PRVTEXT, 2026, 3)
    assert [d.permit_key for d in a] == [d.permit_key for d in b]  # 재파싱 안정
    assert len(set(d.permit_key for d in a)) == len(a)  # 전부 유일


def test_parse_board_list():
    html = """
    <table><tbody>
    <tr><td>139</td><td><a href="#" onclick="goTo.view('list','192526','259','0305030000')">
        토지거래계약 허가사항(2026.5.)</a></td></tr>
    <tr><td>138</td><td><a onclick="goTo.view('list','191978','259','0305030000')">
        토지거래계약 허가사항(2026.4.)</a></td></tr>
    </tbody></table>
    """
    posts = parse_board_list(html)
    assert posts == [("192526", 2026, 5), ("191978", 2026, 4)]


def test_parse_board_list_two_digit_year():
    html = "<tr><td><a onclick=\"goTo.view('list','100','259','0305030000')\">허가사항('26.3월)</a></td></tr>"
    assert parse_board_list(html) == [("100", 2026, 3)]


def test_parse_view_attachment():
    html = """<a href="#" onclick="fn_egov_downFile('ATCH123','SN456'); return false;">file.hwp</a>"""
    assert parse_view_attachment(html) == ("ATCH123", "SN456")


def test_parse_view_attachment_missing_raises():
    with pytest.raises(GyeonggiParseError):
        parse_view_attachment("<div>첨부 없음</div>")


def test_is_supported_zone_routing():
    assert _is_supported_zone("1168010600") is True   # 서울 강남
    assert _is_supported_zone("1159010500") is True   # 서울 동작
    assert _is_supported_zone("4129010900") is True   # 과천 별양동
    assert _is_supported_zone("4113510000") is False  # 성남 분당 — 미지원
    assert _is_supported_zone("4146510000") is False  # 용인 수지 — 미지원
    assert _is_supported_zone(None) is False


def test_shared_jibun_no_duplicate_pk(engine):
    """같은 지번에 추적단지 둘(과천 주공8·9=부림동 41) → 동일 허가가 한쪽에만 귀속, 중복 PK 없음."""
    from sqlmodel import select

    from myhouse.core.permit_collector import _apply_permit_ops
    from myhouse.core.permit_diff import diff_permits
    from myhouse.db.engine import get_session
    from myhouse.db.models import Complex, LandPermit
    from myhouse.seoul.permit_parser import PermitDTO

    dto = PermitDTO(
        permit_key="shared-41", sgg_cd="41290", lawd_cd="4129011000",
        address="과천시 부림동 41", bonbun="0041", bubun="0000",
        permit_date="2026-05-01", job_gbn="허가", use_purp="주거용",
    )
    with get_session(engine) as s:
        s.add(Complex(complex_no="A", name="주공8단지", cortar_no="4129011000",
                      bonbun="0041", bubun="0000"))
        s.add(Complex(complex_no="B", name="주공9단지", cortar_no="4129011000",
                      bonbun="0041", bubun="0000"))
        s.commit()
        g_a = _apply_permit_ops(s, diff_permits("A", [dto], set()), {}, "A", 1, "2026-05-01T00:00:00+09:00")
        g_b = _apply_permit_ops(s, diff_permits("B", [dto], set()), {}, "B", 1, "2026-05-01T00:00:00+09:00")
        assert len(g_a) == 1 and g_b == []  # A 에만 귀속, B 는 중복으로 skip(알림도 1회)
        rows = list(s.exec(select(LandPermit)))
        assert len(rows) == 1 and rows[0].complex_no == "A"
