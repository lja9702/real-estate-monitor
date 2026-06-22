"""옥션원 사건번호 → 물건 직링크(ca_view.php?product_id=) 리졸버.

옥션원은 딥링크가 막혀 있어(POST검색·로그인월·내부 product_id), 사용자 본인 세션 쿠키로
검색(ca_list.php)을 1회 호출해 응답 HTML 에서 product_id 를 뽑아 직링크를 만든다.
결과는 Auction 행에 캐시 → 물건당 평생 1회만 조회("1회 조회").

⚠️ 쿠키는 .env(AUCTION1_COOKIE)에서만 — 만료 시 None 반환(상위에서 진입점 폴백). 사용자 머신
(브라우저와 같은 IP)에서 실행되어야 세션이 안전하다. wire 라이브 캡처: 2026-06-22.
"""

from __future__ import annotations

import logging
import re

import httpx

log = logging.getLogger(__name__)

CA_LIST_URL = "https://www.auction1.co.kr/auction/ca_list.php"
CA_VIEW_URL = "https://www.auction1.co.kr/auction/ca_view.php"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

# 사건번호 검색 폼(라이브 캡처) — num1=연도, num2=번호. 나머지 빈/기본값은 원형 유지(호환).
_FORM_BASE: dict[str, str] = {
    "lawsup": "", "lesson": "", "num1": "", "num2": "",
    "ju_price1": "", "ju_price2": "", "state": "", "b_count1": "", "b_count2": "",
    "s_class": "", "power_flag": "0", "bi_price1": "", "bi_price2": "", "clg_all": "",
    "s_class2": "", "next_biddate1": "", "next_biddate2": "", "b_area1": "", "b_area2": "",
    "b_area_p1": "", "b_area_p2": "", "e_area1": "", "e_area2": "", "e_area_p1": "", "e_area_p2": "",
    "bojon_date1": "", "bojon_date2": "", "sido": "0", "gugun": "0", "dong": "0",
    "ref_page": "", "ref_sido": "", "ref_gugun": "", "ref_dong": "", "am_cnt": "0",
    "sido_multi": "", "bunji_key": "", "bunji1": "", "bunji2": "", "address": "", "address2": "",
    "special": "0", "order": "", "scale": "", "sagun_type": "", "page_code": "101010",
    "subcode": "", "ck_photo": "1", "favor_mode": "", "favor_edit": "0", "from_favor": "",
    "from_my_search": "", "search_mode": "1", "favor_idx": "", "queryType": "favor_serch",
}

# product_id 추출 — 라이브 구조(2026-06): 결과 행 클릭 핸들러가 '난독화 함수명'으로
#   func(pid, line_num, person_hide, win_key) 형태로 호출된다(내부에서 window.open ca_view.php?product_id=${pid}…).
#   함수명은 페이지마다 랜덤이라 이름에 의존하지 않고 인자 시그니처로 잡는다:
#   첫 인자=5자리+ pid, 둘째=line_num, 셋째=person_hide(0/1). line_tnum 은 URL 에 1 로 고정.
#   (함수 '정의'는 인자가 이름이라 매치 안 됨. 일부 페이지의 리터럴 ca_view 링크는 폴백.)
_RE_ROW_CALL = re.compile(
    r"""[A-Za-z_]\w*\(\s*['"]?(\d{5,})['"]?\s*,\s*['"]?(\d+)['"]?\s*,\s*['"]?[01]['"]?\s*[,)]"""
)
_RE_VIEW_HREF_PID = re.compile(r"""ca_view\.php\?[^"'<>]*?product_id=(\d{3,})""")


def parse_case_no(case_no: str) -> tuple[str, str] | None:
    """'2024타경6190' → ('2024','6190'). '2024-6190'·'2024 6190' 등도 허용. 불가 시 None."""
    m = re.search(r"(\d{4})\D+(\d+)", case_no or "")
    return (m.group(1), m.group(2)) if m else None


def build_form(year: str, num: str) -> dict[str, str]:
    return {**_FORM_BASE, "num1": year, "num2": num}


def build_view_url(product_id: str, line_num: str = "1", line_tnum: str = "1") -> str:
    return f"{CA_VIEW_URL}?product_id={product_id}&line_num={line_num}&line_tnum={line_tnum}"


def extract_product(html: str) -> tuple[str, str, str] | None:
    """리스트 HTML → (product_id, line_num, line_tnum='1'). 못 찾으면 None."""
    m = _RE_ROW_CALL.search(html)
    if m:
        return m.group(1), m.group(2), "1"
    m = _RE_VIEW_HREF_PID.search(html)  # 리터럴 product_id 링크(폴백)
    if m:
        return m.group(1), "1", "1"
    return None


def looks_logged_out(html: str) -> bool:
    """로그인 만료/미로그인 응답 추정(로그인 폼/안내로 리다이렉트)."""
    low = html.lower()
    return ("login" in low and "ca_view" not in low) or "로그인이 필요" in html


def fetch_list_html(case_no: str, cookie: str, *, timeout: float = 15.0) -> str | None:
    """사건번호 검색 결과 HTML. 쿠키 없음/파싱불가/네트워크오류 시 None."""
    parsed = parse_case_no(case_no)
    if not (parsed and cookie):
        return None
    year, num = parsed
    try:
        resp = httpx.post(
            CA_LIST_URL,
            data=build_form(year, num),
            headers={
                "Cookie": cookie,
                "User-Agent": _UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.auction1.co.kr",
                "Referer": CA_LIST_URL,
                "Accept-Language": "ko,en-US;q=0.9",
            },
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("옥션원 검색 실패(%s): %s", case_no, e)
        return None
    return resp.text


def resolve_view_url(case_no: str, cookie: str | None, *, timeout: float = 15.0) -> str | None:
    """사건번호 → ca_view 직링크. 실패(쿠키없음·만료·미발견·네트워크) 시 None(상위 폴백)."""
    if not cookie:
        return None
    html = fetch_list_html(case_no, cookie, timeout=timeout)
    if html is None:
        return None
    found = extract_product(html)
    if found is None:
        if looks_logged_out(html):
            log.warning("옥션원 쿠키 만료 추정 — .env AUCTION1_COOKIE 갱신 필요 (%s)", case_no)
        else:
            log.info("옥션원 product_id 미발견(%s) — 진입점 폴백", case_no)
        return None
    return build_view_url(*found)
