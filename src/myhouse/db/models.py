"""SQLite 스키마 (SQLModel) — 6 테이블.

식별 원칙:
  - article_no : 매물 수명주기(lifecycle)의 진실 (PK of `listing`)
  - cluster_key: UX 그룹핑·큐레이션 고정 (PK of `curation`)
모든 타임스탬프는 ISO-8601(KST, 오프셋 포함) 문자열로 저장한다.
가격은 만원 단위 정수로 저장한다.
"""

from __future__ import annotations

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from ..constants import EventType, ListingStatus, RunStatus, TradeType


class Complex(SQLModel, table=True):
    """추적 대상 아파트 단지."""

    __tablename__ = "complex"

    complex_no: str = Field(primary_key=True)
    name: str = ""
    cortar_no: str | None = None  # 법정동코드 10자리 (= 토지거래허가 LAWD_CD)
    address: str | None = None
    total_households: int | None = None  # 총 세대수 (naver totalHouseholdCount)
    total_dong_count: int | None = None  # 총 동수 (naver totalDongCount)
    use_approve_ymd: str | None = None  # 사용승인일 'YYYYMMDD' (naver useApproveYmd)
    floor_area_ratio: int | None = None  # 용적률 % (naver batlRatio)
    building_coverage_ratio: int | None = None  # 건폐율 % (naver btlRatio)
    lat: float | None = None
    lon: float | None = None
    source: str = "pinned"  # "pinned" | "discovered:{cortarNo}"
    is_active: bool = True  # 정기 수집 대상 여부(추적 토글)
    starred: bool = False  # 관심 단지(즐겨찾기) — config/추적과 무관한 큐레이션 플래그
    first_seen_at: str = ""
    updated_at: str = ""
    # 실거래용 평형 캐시(complexPyeongDetailList 요약 JSON) — 단지당 1회 조회 후 재사용.
    pyeongs_json: str | None = None
    deals_fetched_at: str | None = None  # 마지막 실거래 수집 시각(ISO)
    # 토지거래허가 매칭용 대표지번(네이버 단지상세 detailAddress 정규화) — 단지당 1회 백필.
    bonbun: str | None = None  # 본번 4자리 zero-pad
    bubun: str | None = None  # 부번 4자리 zero-pad


class Listing(SQLModel, table=True):
    """현재 스냅샷 — 매물 1건 = article_no."""

    __tablename__ = "listing"
    __table_args__ = (
        Index("ix_listing_complex_status", "complex_no", "status"),
        Index("ix_listing_cluster", "cluster_key"),
    )

    article_no: str = Field(primary_key=True)
    complex_no: str = Field(foreign_key="complex.complex_no")
    trade_type: TradeType
    price_deal: int | None = None  # 매매가/보증금 (만원)
    price_rent: int | None = None  # 월세 (만원)
    area_excl: float | None = None  # 전용면적 ㎡
    area_supply: float | None = None  # 공급면적 ㎡
    floor_info: str | None = None  # 원문 "12/15"
    floor_num: int | None = None  # 파싱된 숫자층
    direction: str | None = None  # 향
    dong: str | None = None
    feature_desc: str | None = None  # 특징
    realtor_name: str | None = None  # 중개사
    confirm_date: str | None = None  # 확인일자 (ISO date)
    article_url: str | None = None
    cluster_key: str = ""
    status: ListingStatus = ListingStatus.ACTIVE
    first_seen_at: str = ""
    last_seen_at: str = ""
    first_seen_run_id: int | None = None
    last_seen_run_id: int | None = None
    missing_since: str | None = None  # 삭제 디바운스 기준 (미노출 최초 관측 시각)
    price_fingerprint: str = ""  # f"{price_deal}|{price_rent}"


class ListingHistory(SQLModel, table=True):
    """append-only 이벤트 로그 — 가격이력 뷰의 데이터원."""

    __tablename__ = "listing_history"
    __table_args__ = (Index("ix_history_article", "article_no"),)

    id: int | None = Field(default=None, primary_key=True)
    article_no: str = Field(foreign_key="listing.article_no")
    cluster_key: str = ""
    run_id: int | None = Field(default=None, foreign_key="run.id")
    event_type: EventType
    price_deal: int | None = None
    price_rent: int | None = None
    old_price_deal: int | None = None
    old_price_rent: int | None = None
    recorded_at: str = ""


class Deal(SQLModel, table=True):
    """국토부 실거래 1건 (네이버 prices/real 경유).

    식별: 자연키 `deal_key` = sha1(complex_no|trade_type|deal_date|floor|price|pyeong_no).
    취소(deleteYn="O")는 같은 deal_key 로 다시 관측되므로 키에서 제외 — 취소는 행 갱신으로 처리한다.
    """

    __tablename__ = "deal"
    __table_args__ = (
        Index("ix_deal_complex_date", "complex_no", "deal_date"),
        Index("ix_deal_first_seen_run", "first_seen_run_id"),
        Index("ix_deal_pyeong", "complex_no", "pyeong_no"),
    )

    deal_key: str = Field(primary_key=True)
    complex_no: str = Field(foreign_key="complex.complex_no")
    trade_type: TradeType
    deal_date: str  # 거래일 ISO 'YYYY-MM-DD'
    price_deal: int  # 매매가/보증금 (만원)
    price_rent: int | None = None  # 월세 (만원)
    floor: int | None = None  # 거래 층
    pyeong_no: str | None = None  # 평형 식별자(areaNo)
    pyeong_name: str | None = None  # 평형 라벨 "80B"
    area_excl: float | None = None  # 전용면적 ㎡
    area_supply: float | None = None  # 공급면적 ㎡
    cancelled: bool = False  # 거래취소(deleteYn="O")
    first_seen_at: str = ""
    first_seen_run_id: int | None = None
    last_seen_at: str = ""
    cancel_seen_at: str | None = None  # 취소를 처음 관측한 시각


class LandPermit(SQLModel, table=True):
    """서울시 토지거래허가 1건 (land.seoul.go.kr 경유) — 추적 단지에 매칭된 것만 저장.

    실거래(Deal)의 *선행* 신호: 거래 완료·신고 전에 뜨는 허가다. 단 응답에 가격·면적이
    없어 '단지에서 허가 N건' 수준의 거래활성 신호로만 쓴다(가격은 실거래로 보완).
    식별: 자연키 permit_key = sha1(SGG_CD|ACC_YEAR|ACC_NO|OBJ_SEQNO). 처리구분(허가/취소)은
    키에서 제외 — 같은 접수가 상태만 바뀌면 같은 키로 행 갱신한다.
    """

    __tablename__ = "land_permit"
    __table_args__ = (
        Index("ix_permit_complex_date", "complex_no", "permit_date"),
        Index("ix_permit_first_seen_run", "first_seen_run_id"),
    )

    permit_key: str = Field(primary_key=True)
    complex_no: str = Field(foreign_key="complex.complex_no")  # 매칭된 추적 단지
    sgg_cd: str  # 자치구 코드(11xxx)
    lawd_cd: str | None = None  # 법정동코드 10자리
    address: str = ""  # "강남구 청담동 127-31" (표시용)
    bonbun: str | None = None  # 본번 4자리 zero-pad
    bubun: str | None = None  # 부번 4자리 zero-pad
    permit_date: str | None = None  # 허가일 ISO 'YYYY-MM-DD'
    job_gbn: str | None = None  # 처리구분(허가/취소/불허가/취하/반려)
    use_purp: str | None = None  # 이용목적(주거용 등)
    jimok: str | None = None  # 지목(대 등)
    first_seen_at: str = ""
    first_seen_run_id: int | None = None
    last_seen_at: str = ""


class FlashDeal(SQLModel, table=True):
    """급매 1건 — 같은 단지·평수·거래유형의 직전 호가 하한가를 일정 비율 이상 언더컷한 매물.

    매물 수집(collect)에 얹혀 탐지하며, 발생 '순간'의 맥락(prior_floor·하락폭)을 박제한다.
    식별: article_no(매물 1건 = 급매 1건) — 같은 매물이 다시 잡혀도 첫 발생만 보존한다.
    현재 가격·상태는 listing 행을 조인해 보고, 이 테이블은 발생 시점 스냅샷을 담는다.
    """

    __tablename__ = "flash_deal"
    __table_args__ = (
        Index("ix_flash_complex", "complex_no"),
        Index("ix_flash_detected_run", "detected_run_id"),
    )

    article_no: str = Field(primary_key=True, foreign_key="listing.article_no")
    complex_no: str = Field(foreign_key="complex.complex_no")
    cluster_key: str = ""
    trade_type: TradeType
    area_excl: float | None = None  # 전용면적 ㎡
    area_key: int | None = None     # area_match_key(버림) — 평형 매칭/그룹 키
    price_deal: int                 # 급매 발생 당시 가격 (만원)
    prior_floor: int                # 직전 같은 평수 하한가 (만원) — 판정 기준
    drop_amount: int                # prior_floor - price_deal (만원)
    drop_pct: float                 # drop_amount / prior_floor * 100
    trigger: str = "new"            # "new"(신규) | "price_drop"(가격인하)
    detected_at: str = ""
    detected_run_id: int | None = None
    notified: bool = False          # 텔레그램 알림 완료 여부 — sticky


class Curation(SQLModel, table=True):
    """사용자 큐레이션 — cluster_key 기준(중개사 article_no 교체에도 유지).

    제외/메모는 매물(cluster) 단위 큐레이션이다. 관심(별표)은 단지 단위로 옮겨갔으므로
    `starred` 는 더 이상 쓰지 않는다(스키마 v4 에서 `Complex.starred` 로 1회 이관). 컬럼은
    파괴적 마이그레이션을 피하려 남겨둘 뿐이다 — 새 코드는 읽지도 쓰지도 않는다.
    """

    __tablename__ = "curation"

    cluster_key: str = Field(primary_key=True)
    complex_no: str | None = None
    starred: bool = False  # deprecated(v4) — Complex.starred 로 이관됨. 미사용.
    excluded: bool = False
    memo: str | None = None
    created_at: str = ""
    updated_at: str = ""


class DiscoverCandidate(SQLModel, table=True):
    """주간 탐색으로 발견한 단지 후보(가격대 편입). 알림은 단지당 1회(notified).

    추적과 무관한 '발견 스냅샷'이다. 사용자가 /add 하면 별도로 complex 행이 생긴다.
    첫 탐색 회차는 baseline 으로 기록만 하고 알리지 않는다(notified=True 로 흡수).
    """

    __tablename__ = "discover_candidate"

    complex_no: str = Field(primary_key=True)
    name: str = ""
    region: str | None = None  # 발견한 config 지역 라벨(best-effort)
    real_estate_type: str | None = None
    price_min: int | None = None  # 만원 (마커 minDealPrice)
    price_max: int | None = None  # 만원 (마커 maxDealPrice)
    households: int | None = None
    area_min: float | None = None  # 공급 추정 ㎡
    area_max: float | None = None
    tracked_at_discovery: bool = False  # 발견 시 이미 추적 중(config/DB)이었는지
    notified: bool = False  # 알림(또는 baseline 흡수) 완료 여부 — sticky
    first_seen_at: str = ""  # 처음 밴드 편입으로 관측한 시각
    last_seen_at: str = ""  # 최근 관측 시각
    notified_at: str | None = None  # 알림 전송 시각


class Run(SQLModel, table=True):
    """수집 1회 실행 로그."""

    __tablename__ = "run"

    id: int | None = Field(default=None, primary_key=True)
    started_at: str = ""
    finished_at: str | None = None
    trigger: str = "scheduled"  # scheduled | manual
    kind: str = "listings"  # listings(매물) | deals(실거래)
    status: RunStatus = RunStatus.RUNNING
    targets_count: int = 0
    complexes_done: int = 0  # 실행 중 진행률 — 수집 완료한 단지 수(실시간 갱신)
    articles_fetched: int = 0  # deals: 수집한 실거래 raw 건수
    new_count: int = 0  # deals: 신규 실거래 수
    price_changed_count: int = 0  # deals: 미사용(0)
    removed_count: int = 0  # deals: 취소 실거래 수
    http_errors: int = 0
    error: str | None = None


class Subscriber(SQLModel, table=True):
    """텔레그램 봇 구독자 — 첫 메시지 전송 시 자동 등록, /stop 으로 해제.

    가격밴드(price_min/max_manwon)는 정기 푸시 다이제스트를 이 구독자의 관심 가격대로
    필터하는 데 쓴다(None=무제한). 수집·diff 는 전역 1회로 두고 발송 직전 구독자별로
    걸러낸다 — 가격은 매물(article) 속성이라 단지 분리가 아니라 알림 시점 필터가 맞다.
    """

    __tablename__ = "subscriber"

    chat_id: str = Field(primary_key=True)
    subscribed_at: str = ""
    active: bool = True
    unsubscribed_at: str | None = None
    price_min_manwon: int | None = None  # 관심 가격 하한(만원). None=하한 없음.
    price_max_manwon: int | None = None  # 관심 가격 상한(만원). None=상한 없음.
    approved: bool = False  # 봇 사용 승인 여부 — /join 초대코드로 셀프 등록 시 True(active 와 독립).


class Subscription(SQLModel, table=True):
    """텔레그램 유저 ↔ 단지 구독 매핑 — 누가 그 단지를 /add 했는지(소유) 추적.

    개인(텔레그램 추가) 단지에만 의미가 있다. 공통 단지(pinned/web)는 이 매핑과 무관하게
    모두에게 가고, 운영자(allowlist)는 매핑과 무관하게 전체를 받는다 — /list·정기알림 발송
    '시점'에 이 매핑으로 거른다(수집·diff 는 전역 1회 유지). 가격밴드와 같은 철학.
    """

    __tablename__ = "subscription"

    chat_id: str = Field(primary_key=True)
    complex_no: str = Field(primary_key=True, foreign_key="complex.complex_no")
    created_at: str = ""


class Auction(SQLModel, table=True):
    """법원경매 물건 1건 (courtauction.go.kr 신규시스템 경유) — 추적 단지에 매칭된 것만 저장.

    실거래/허가와 달리 물건이 '살아 움직인다'(유찰→최저가 하락·기일 변경·매각/취하). 따라서
    변화는 신규(NEW)뿐 아니라 최저가 하락·기일 변경을 추적한다(diff: core/auction_diff.py).
    식별: 자연키 auction_key = courtauction docid(물건 단위 고유). 한 사건 다물건이면 각각 행.
    금액은 만원 단위. 상세·사진·권리분석은 옥션원(auction1_url)/법원공고(court_url)로 연결.
    """

    __tablename__ = "auction"
    __table_args__ = (
        Index("ix_auction_complex_saledate", "complex_no", "sale_date"),
        Index("ix_auction_first_seen_run", "first_seen_run_id"),
    )

    auction_key: str = Field(primary_key=True)  # = courtauction docid
    complex_no: str = Field(foreign_key="complex.complex_no")  # 매칭된 추적 단지
    court_code: str | None = None
    court_name: str | None = None  # "서울중앙지방법원"
    case_no: str = ""  # 표시 사건번호 "2024타경12345"
    item_no: str | None = None  # 물건번호(한 사건 다물건)
    address: str = ""  # 소재지(지번)
    building_name: str | None = None  # 단지/건물명(빈값 가능)
    usage_name: str | None = None  # 물건종류(아파트 등)
    area_excl: float | None = None  # 전용 추정 ㎡
    appraisal_manwon: int | None = None  # 감정가(만원)
    min_bid_manwon: int | None = None  # 최저매각가(만원)
    min_bid_ratio: int | None = None  # 최저가/감정가 %
    fail_count: int = 0  # 유찰횟수
    sale_date: str | None = None  # 매각기일 ISO
    status_code: str | None = None  # 물건상태(mulStatcd)
    in_progress: bool = True  # 진행 여부(mulJinYn)
    auction1_url: str | None = None  # 옥션원 딥링크
    court_url: str | None = None  # 법원경매 사건검색 딥링크
    first_seen_at: str = ""
    first_seen_run_id: int | None = None
    last_seen_at: str = ""


class Meta(SQLModel, table=True):
    """key/value 메타 — schema_version, last_successful_run_id 등."""

    __tablename__ = "meta"

    key: str = Field(primary_key=True)
    value: str | None = None


SCHEMA_VERSION = "14"  # 14: run.complexes_done — 수집 실행 중 단지 진행률(실시간)
# 12: 급매(flash_deal) 테이블 — 같은 평수 직전 호가하한 ≥임계 언더컷 탐지·적재
# 11: 유저별 단지 구독(subscription) — /add 소유 추적 + /list·알림 개인화
# 10: 구독자 승인(subscriber.approved) — /join 초대코드 셀프등록
# 9: 구독자 가격밴드(subscriber.price_min/max_manwon)
# 8/7: 단지 메타(complex.total_dong_count/use_approve_ymd/floor_area_ratio/building_coverage_ratio)
# 6: 주간탐색 discover_candidate 테이블 + run.kind="discover"
# 5: 토지거래허가 land_permit 테이블 + complex.bonbun/bubun + run.kind="permits"
# 4: 관심=단지 — complex.starred 추가 + curation.starred→complex 이관
# 3: 주간탐색 discover_candidate 테이블 + run.kind="discover"
# 2: 실거래(deal) 테이블 + complex.pyeongs_json/deals_fetched_at + run.kind
