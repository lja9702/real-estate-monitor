"""옥션원·법원경매 진입 링크 빌더.

⚠️ 옥션원(auction1.co.kr)은 **물건 딥링크가 구조적으로 불가**하다(라이브 확인 2026-06):
  ① 검색이 POST 라 사건번호가 URL 에 안 실린다, ② 로그인 월이라 검색엔진 색인도 안 된다,
  ③ 물건 상세는 내부 product_id(+세션 user_ssid)가 필요한데 우리 데이터(법원 docid/사건번호)로는
  product_id 를 알 수 없다(옥션원에 질의=스크래핑해야 얻음 — 원칙상 안 함).
따라서 옥션원 링크는 '진입점'만 제공하고, 실제 식별키인 **사건번호를 메시지에 노출**해 사용자가
로그인 상태에서 검색하게 한다. 법원경매 공식(courtauction)은 공개 사건검색 화면으로 연결한다.
product_id 확보 경로가 생기면 ca_view.php 직링크로 교체 가능(아래 _AUCTION1_VIEW 참고).
"""

from __future__ import annotations

AUCTION1_HOME = "https://www.auction1.co.kr/"
# 물건 직링크 형태(참고용) — product_id 를 알 수 있게 되면 이걸로 교체:
#   https://www.auction1.co.kr/auction/ca_view.php?product_id={pid}&line_num=1&line_tnum=1
_AUCTION1_VIEW = "https://www.auction1.co.kr/auction/ca_view.php"

# 법원경매 신규시스템 경매사건검색 화면(PGJ159M00) — 사건번호로 직접 조회하는 공개 진입점.
_COURT_CASE_SEARCH = (
    "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ159M00.xml&pgjId=159M00"
)


def auction1_search_url() -> str:
    """옥션원 진입점. 딥링크 불가(POST검색·로그인월·내부 product_id)라 메인으로 보내고,
    사용자는 메시지의 사건번호로 검색한다."""
    return AUCTION1_HOME


def court_case_search_url() -> str:
    """법원경매 신규시스템 경매사건검색 화면(사건번호로 직접 조회·공개)."""
    return _COURT_CASE_SEARCH
