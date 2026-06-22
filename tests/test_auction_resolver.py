"""옥션원 리졸버 순수함수 테스트 — 사건번호 파싱·product_id 추출·직링크·로그아웃감지(네트워크 없음)."""

from __future__ import annotations

import pytest

from myhouse.court.auction1_resolver import (
    build_form,
    build_view_url,
    extract_product,
    looks_logged_out,
    parse_case_no,
)


@pytest.mark.parametrize(
    ("raw", "exp"),
    [
        ("2024타경6190", ("2024", "6190")),
        ("2024 타경 6190", ("2024", "6190")),
        ("2024-6190", ("2024", "6190")),
        ("2023타경105432", ("2023", "105432")),
        ("타경", None),
        ("", None),
    ],
)
def test_parse_case_no(raw, exp):
    assert parse_case_no(raw) == exp


def test_build_form_splits_case_no():
    f = build_form("2024", "6190")
    assert f["num1"] == "2024"
    assert f["num2"] == "6190"
    assert f["queryType"] == "favor_serch"  # 라이브 캡처 폼 원형 유지
    assert f["page_code"] == "101010"


def test_build_view_url():
    assert build_view_url("2569881") == (
        "https://www.auction1.co.kr/auction/ca_view.php"
        "?product_id=2569881&line_num=1&line_tnum=1"
    )
    assert build_view_url("123", "2", "3").endswith("product_id=123&line_num=2&line_tnum=3")


def test_extract_product_row_call():
    """난독화 함수명 + (pid, line_num, person_hide, win_key) 호출 — 라이브 구조."""
    html = "<tr onclick=\"zBBTFgUP(2569881,1,0,'key')\">물건</tr>"
    assert extract_product(html) == ("2569881", "1", "1")


def test_extract_product_row_call_quoted():
    html = "<a onclick=\"abcDEF('2569881','2','1','k')\">보기</a>"
    assert extract_product(html) == ("2569881", "2", "1")


def test_extract_product_ignores_function_def():
    """함수 '정의'(인자가 이름)와 템플릿변수 URL 은 매치하지 않는다."""
    html = (
        "function zBBTFgUP(pid, line_num, person_hide, win_key) { "
        "window.open(`/auction/ca_view.php?product_id=${pid}&line_num=${line_num}`); }"
    )
    assert extract_product(html) is None


def test_extract_product_href_fallback():
    html = '<a href="/auction/ca_view.php?product_id=2569881&line_num=1">보기</a>'
    assert extract_product(html) == ("2569881", "1", "1")


def test_extract_product_none():
    assert extract_product("<html><body>검색 결과가 없습니다</body></html>") is None


def test_looks_logged_out():
    assert looks_logged_out("로그인이 필요한 서비스입니다")
    assert not looks_logged_out("<a onclick=\"ca_view('1','1','1')\">물건</a>")
