"""데이터 접근(repo) — 수집기/대시보드가 쓰는 DB 질의·변경 함수."""

from __future__ import annotations

from sqlmodel import Session, select

from ..constants import SOURCE_TELEGRAM, RunStatus, now_kst, to_iso
from .models import (
    Auction,
    Complex,
    Curation,
    Deal,
    DiscoverCandidate,
    FlashDeal,
    LandPermit,
    Listing,
    Run,
    Subscriber,
    Subscription,
)


# ── Run ────────────────────────────────────────────────────────────────────
def create_run(session: Session, trigger: str = "scheduled", kind: str = "listings") -> Run:
    run = Run(
        started_at=to_iso(now_kst()), trigger=trigger, kind=kind, status=RunStatus.RUNNING
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finalize_run(
    session: Session,
    run: Run,
    status: RunStatus,
    *,
    targets_count: int = 0,
    articles_fetched: int = 0,
    new_count: int = 0,
    price_changed_count: int = 0,
    removed_count: int = 0,
    http_errors: int = 0,
    error: str | None = None,
) -> Run:
    run.finished_at = to_iso(now_kst())
    run.status = status
    run.targets_count = targets_count
    run.articles_fetched = articles_fetched
    run.new_count = new_count
    run.price_changed_count = price_changed_count
    run.removed_count = removed_count
    run.http_errors = http_errors
    run.error = error
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


# ── Complex ────────────────────────────────────────────────────────────────
def get_complex(session: Session, complex_no: str) -> Complex | None:
    return session.get(Complex, complex_no)


def upsert_complex(session: Session, complex_no: str, **fields) -> Complex:
    """단지 upsert. None 값 필드는 기존 값을 덮어쓰지 않는다."""
    now = to_iso(now_kst())
    row = session.get(Complex, complex_no)
    if row is None:
        row = Complex(complex_no=complex_no, first_seen_at=now, updated_at=now)
        for k, v in fields.items():
            if v is not None and hasattr(row, k):
                setattr(row, k, v)
        session.add(row)
    else:
        for k, v in fields.items():
            if v is not None and hasattr(row, k):
                setattr(row, k, v)
        row.updated_at = now
        session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_active_complexes(session: Session) -> list[Complex]:
    return list(session.exec(select(Complex).where(Complex.is_active == True)))  # noqa: E712


def list_complexes_by_source(
    session: Session, source: str, *, active_only: bool = True
) -> list[Complex]:
    """출처(source)로 단지 조회. 텔레그램으로 추가한 추적 단지를 정기 수집에 병합할 때 사용."""
    stmt = select(Complex).where(Complex.source == source)
    if active_only:
        stmt = stmt.where(Complex.is_active == True)  # noqa: E712
    return list(session.exec(stmt))


def list_inactive_complex_nos(session: Session) -> set[str]:
    """추적 해제(is_active=False)된 단지번호 집합. resolve_targets 가 정기 수집에서 제외할 때 사용."""
    return set(
        session.exec(select(Complex.complex_no).where(Complex.is_active == False))  # noqa: E712
    )


def set_complex_active(session: Session, complex_no: str, active: bool) -> Complex | None:
    """단지 추적 on/off 토글. 행이 없으면 None(출처는 건드리지 않는다)."""
    row = session.get(Complex, complex_no)
    if row is None:
        return None
    row.is_active = active
    row.updated_at = to_iso(now_kst())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def set_complex_starred(session: Session, complex_no: str, starred: bool) -> Complex | None:
    """단지 관심(별표) on/off 토글. 행이 없으면 None(추적/출처는 건드리지 않는다)."""
    row = session.get(Complex, complex_no)
    if row is None:
        return None
    row.starred = starred
    row.updated_at = to_iso(now_kst())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_starred_complexes(session: Session) -> list[Complex]:
    """관심(별표) 단지 — 추적 여부와 무관. 관심목록 페이지·다이제스트 강조용."""
    return list(session.exec(select(Complex).where(Complex.starred == True)))  # noqa: E712


def starred_complex_nos(session: Session) -> set[str]:
    """관심 단지번호 집합. deals.scope='starred' 필터·다이제스트 ★ 판정에 사용."""
    return set(session.exec(select(Complex.complex_no).where(Complex.starred == True)))  # noqa: E712


# ── Listing ────────────────────────────────────────────────────────────────
def get_listings_for_complex(session: Session, complex_no: str) -> list[Listing]:
    return list(session.exec(select(Listing).where(Listing.complex_no == complex_no)))


def get_listing(session: Session, article_no: str) -> Listing | None:
    return session.get(Listing, article_no)


# ── Curation ───────────────────────────────────────────────────────────────
def get_curation_map(
    session: Session, cluster_keys: list[str] | None = None
) -> dict[str, Curation]:
    stmt = select(Curation)
    if cluster_keys:
        stmt = stmt.where(Curation.cluster_key.in_(cluster_keys))  # type: ignore[attr-defined]
    return {c.cluster_key: c for c in session.exec(stmt)}


# ── Deal (실거래) ────────────────────────────────────────────────────────────
def get_deals_for_complex(session: Session, complex_no: str) -> list[Deal]:
    return list(session.exec(select(Deal).where(Deal.complex_no == complex_no)))


# ── FlashDeal (급매) ──────────────────────────────────────────────────────────
def add_flash_deals(session: Session, signals: list, *, run_id: int, now: str) -> int:
    """급매 신호(core.flash.FlashSignal 목록)를 적재한다. 커밋은 호출측(_collect_one)이 한다.

    article_no 가 이미 있으면 skip — 급매는 '첫 발생'만 박제한다(현재가/상태는 listing 조인으로 본다).
    실제 적재한 신규 건수를 반환한다.
    """
    if not signals:
        return 0
    # 같은 회차의 신규 매물(부모)을 먼저 반영한다. flash_deal.article_no 는 listing 의 FK 인데
    # PK=FK 컬럼이라 SQLAlchemy 가 같은 flush 에서 listing→flash_deal 삽입 순서를 보장하지 못한다.
    session.flush()
    added = 0
    for sig in signals:
        if session.get(FlashDeal, sig.article_no) is not None:
            continue
        session.add(
            FlashDeal(
                article_no=sig.article_no,
                complex_no=sig.complex_no,
                cluster_key=sig.cluster_key,
                trade_type=sig.trade_type,
                area_excl=sig.area_excl,
                area_key=sig.area_key,
                price_deal=sig.price_deal,
                prior_floor=sig.prior_floor,
                drop_amount=sig.drop_amount,
                drop_pct=sig.drop_pct,
                trigger=sig.trigger,
                detected_at=now,
                detected_run_id=run_id,
                notified=False,
            )
        )
        added += 1
    return added


def get_flash_deals_for_complex(session: Session, complex_no: str) -> list[FlashDeal]:
    return list(session.exec(select(FlashDeal).where(FlashDeal.complex_no == complex_no)))


# ── LandPermit (토지거래허가) ──────────────────────────────────────────────────
def get_permits_for_complex(session: Session, complex_no: str) -> list[LandPermit]:
    return list(session.exec(select(LandPermit).where(LandPermit.complex_no == complex_no)))


# ── Auction (법원경매) ────────────────────────────────────────────────────────
def get_auctions_for_complex(session: Session, complex_no: str) -> list[Auction]:
    return list(session.exec(select(Auction).where(Auction.complex_no == complex_no)))


def get_auctions_to_reconcile(
    session: Session, today_iso: str, *, limit: int | None = None
) -> list[Auction]:
    """결과 미확정(outcome IS NULL)이면서 매각기일이 지난(sale_date<오늘) 물건 — 사후 정합 대상.

    forward 검색에서 사라진 종결/유찰 물건을 사건 기일내역으로 확정하기 위한 폴링 목록.
    오래된 것부터(매각기일 오름차순). limit 으로 회차당 폴링량을 제한(차단 회피).
    """
    stmt = (
        select(Auction)
        .where(
            Auction.outcome == None,  # noqa: E711
            Auction.sale_date != None,  # noqa: E711
            Auction.sale_date < today_iso,
        )
        .order_by(Auction.sale_date)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.exec(stmt))


def purge_old_auctions(session: Session, cutoff_date: str) -> int:
    """매각기일(sale_date)이 cutoff_date(YYYY-MM-DD) 이전인 지난 경매를 삭제. 삭제 건수 반환.

    수집은 미래 매각기일만 가져오므로(begin=오늘) 매각기일이 지나면 그 행은 더는 갱신되지
    않고 '지난 경매'로 고정된다. 이를 보관기간(auctions.retention_days)만 남기고 정리한다.
    매각기일 미상(sale_date is None)인 행은 나이를 알 수 없어 보존한다.
    """
    stale = list(
        session.exec(
            select(Auction).where(
                Auction.sale_date != None,  # noqa: E711
                Auction.sale_date < cutoff_date,
            )
        )
    )
    for row in stale:
        session.delete(row)
    if stale:
        session.commit()
    return len(stale)


def list_complexes_missing_jibun(session: Session) -> list[Complex]:
    """대표지번(bonbun)이 아직 없는 활성 단지 — 토지거래허가 매칭용 백필 대상."""
    return list(
        session.exec(
            select(Complex).where(
                Complex.is_active == True,  # noqa: E712
                Complex.bonbun == None,  # noqa: E711
            )
        )
    )


# ── DiscoverCandidate (주간 탐색 후보) ─────────────────────────────────────────
def get_discover_candidate(session: Session, complex_no: str) -> DiscoverCandidate | None:
    return session.get(DiscoverCandidate, complex_no)


def list_discover_candidate_nos(session: Session) -> set[str]:
    """기존에 발견·기록된 후보 단지번호 집합(신규 편입 판정 기준선)."""
    return set(session.exec(select(DiscoverCandidate.complex_no)))


def count_discover_candidates(session: Session) -> int:
    return len(list(session.exec(select(DiscoverCandidate.complex_no))))


def list_discover_candidates(session: Session) -> list[DiscoverCandidate]:
    return list(session.exec(select(DiscoverCandidate)))


def upsert_discover_candidate(
    session: Session, complex_no: str, **fields
) -> DiscoverCandidate:
    """탐색 후보 upsert. None 값은 기존 값을 덮어쓰지 않는다(first_seen_at 보존)."""
    now = to_iso(now_kst())
    row = session.get(DiscoverCandidate, complex_no)
    if row is None:
        row = DiscoverCandidate(complex_no=complex_no, first_seen_at=now, last_seen_at=now)
        for k, v in fields.items():
            if v is not None and hasattr(row, k):
                setattr(row, k, v)
        session.add(row)
    else:
        for k, v in fields.items():
            if v is not None and hasattr(row, k):
                setattr(row, k, v)
        row.last_seen_at = now
        session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ── Subscriber (텔레그램 구독자) ───────────────────────────────────────────────
def get_active_subscriber_ids(session: Session) -> list[str]:
    """알림을 받을 활성 구독자 chat_id 목록."""
    return list(session.exec(select(Subscriber.chat_id).where(Subscriber.active == True)))  # noqa: E712


def get_active_subscribers(session: Session) -> list[Subscriber]:
    """활성 구독자 전체 행(가격밴드 포함) — 개인화 다이제스트 발송용."""
    return list(session.exec(select(Subscriber).where(Subscriber.active == True)))  # noqa: E712


def get_subscriber(session: Session, chat_id: str) -> Subscriber | None:
    return session.get(Subscriber, chat_id)


def is_approved(session: Session, chat_id: str) -> bool:
    """봇 사용 승인 여부(초대코드로 /join 했거나 마이그레이션으로 grandfather 된 구독자)."""
    row = session.get(Subscriber, chat_id)
    return row is not None and row.approved


def approve_chat(session: Session, chat_id: str) -> Subscriber:
    """초대코드 검증 통과 → 승인 + 구독 활성화. 없으면 생성한다."""
    now = to_iso(now_kst())
    row = session.get(Subscriber, chat_id)
    if row is None:
        row = Subscriber(chat_id=chat_id, subscribed_at=now, active=True, approved=True)
    else:
        row.approved = True
        row.active = True
        row.unsubscribed_at = None
        if not row.subscribed_at:
            row.subscribed_at = now
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def set_subscriber_band(
    session: Session, chat_id: str, price_min: int | None, price_max: int | None
) -> Subscriber:
    """구독자의 관심 가격밴드(만원) 설정. 없으면 활성 구독자로 생성한다."""
    now = to_iso(now_kst())
    row = session.get(Subscriber, chat_id)
    if row is None:
        row = Subscriber(chat_id=chat_id, subscribed_at=now, active=True)
    row.price_min_manwon = price_min
    row.price_max_manwon = price_max
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def is_subscribed(session: Session, chat_id: str) -> bool:
    row = session.get(Subscriber, chat_id)
    return row is not None and row.active


def subscribe(session: Session, chat_id: str) -> None:
    """구독 등록(이미 활성이면 no-op, 해제 상태면 재활성)."""
    now = to_iso(now_kst())
    row = session.get(Subscriber, chat_id)
    if row is None:
        session.add(Subscriber(chat_id=chat_id, subscribed_at=now, active=True))
        session.commit()
    elif not row.active:
        row.active = True
        row.subscribed_at = now
        row.unsubscribed_at = None
        session.add(row)
        session.commit()


def unsubscribe(session: Session, chat_id: str) -> bool:
    """구독 해제. 활성 구독자였으면 True, 아니면 False."""
    now = to_iso(now_kst())
    row = session.get(Subscriber, chat_id)
    if row and row.active:
        row.active = False
        row.unsubscribed_at = now
        session.add(row)
        session.commit()
        return True
    return False


# ── Subscription (유저별 단지 구독) ───────────────────────────────────────────
def add_subscription(session: Session, chat_id: str, complex_no: str) -> None:
    """유저↔단지 구독 기록(idempotent). 이미 있으면 no-op."""
    if session.get(Subscription, (chat_id, complex_no)) is not None:
        return
    session.add(
        Subscription(chat_id=chat_id, complex_no=complex_no, created_at=to_iso(now_kst()))
    )
    session.commit()


def remove_subscription(session: Session, chat_id: str, complex_no: str) -> bool:
    """구독 해제. 있었으면 True, 없었으면 False."""
    row = session.get(Subscription, (chat_id, complex_no))
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def subscribed_complex_nos(session: Session, chat_id: str) -> set[str]:
    """유저가 /add 한 단지번호 집합 — 개인화 알림의 개인 단지 풀."""
    return set(
        session.exec(select(Subscription.complex_no).where(Subscription.chat_id == chat_id))
    )


def list_subscribed_complexes(session: Session, chat_id: str) -> list[Complex]:
    """유저가 구독한 활성 단지 행 목록 — /list 표시용(이름순 정렬은 호출측)."""
    return list(
        session.exec(
            select(Complex)
            .join(Subscription, Subscription.complex_no == Complex.complex_no)  # type: ignore[arg-type]
            .where(
                Subscription.chat_id == chat_id,
                Complex.is_active == True,  # noqa: E712
            )
        )
    )


def shared_complex_nos(session: Session) -> set[str]:
    """공통 단지(텔레그램 외 출처 = pinned/web) 번호 집합 — 모든 구독자에게 가는 알림 풀."""
    return set(
        session.exec(
            select(Complex.complex_no).where(
                Complex.source != SOURCE_TELEGRAM,
                Complex.is_active == True,  # noqa: E712
            )
        )
    )


def upsert_curation(session: Session, cluster_key: str, **fields) -> Curation:
    now = to_iso(now_kst())
    row = session.get(Curation, cluster_key)
    if row is None:
        row = Curation(cluster_key=cluster_key, created_at=now, updated_at=now)
        session.add(row)
    for k, v in fields.items():
        if hasattr(row, k):
            setattr(row, k, v)
    row.updated_at = now
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
