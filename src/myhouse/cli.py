"""myhouse CLI (Typer) — initdb / collect / collect-deals / test-notify / probe / serve / bot / backup-db."""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

import typer

from .constants import now_kst
from .db.engine import init_db, make_engine
from .logging_conf import mask_secret, setup_logging
from .settings import Config, Settings, load_config

app = typer.Typer(add_completion=False, help="네이버부동산 매물 모니터")
log = logging.getLogger("myhouse.cli")


def _load(config_path: str) -> tuple[Config, Settings]:
    setup_logging()
    config = load_config(config_path)
    settings = Settings(_env_file=config.app.env_file)
    return config, settings


def _html_to_text(html: str) -> str:
    """콘솔 미리보기용 — 링크 태그를 'text(url)' 로, 나머지 태그 제거."""
    html = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"\2(\1)", html)
    return re.sub(r"<[^>]+>", "", html)


def _auto_sync_push(cfg: Config, settings: Settings, status) -> None:
    """수집 성공(SUCCESS/PARTIAL) 직후 현재 DB 를 R2 로 업로드 — 클라우드(읽기전용)가 ~10분 내 반영.

    R2 미설정이면 no-op. push 가 실패해도 수집 결과엔 영향 없도록 best-effort(로그만).
    push 자동화가 없던 탓에 클라우드 DB 가 마지막 수동 sync-push 시점에 며칠씩 묶여 있던 문제를 해소.
    """
    sval = getattr(status, "value", status)
    if sval not in ("SUCCESS", "PARTIAL"):
        return
    from .cloud.sync import push_db, s3_from_settings

    if s3_from_settings(settings) is None:
        return  # R2 미설정 — 동기화 비활성
    try:
        etag = push_db(settings, cfg.app.db_path)
        typer.echo(f"☁️  R2 동기화 완료(etag={etag})")
    except Exception as e:  # noqa: BLE001
        log.warning("R2 자동 동기화 실패(무시): %s", e)
        typer.secho(f"⚠️  R2 자동 동기화 실패(무시): {e}", fg="yellow")


@app.command()
def initdb(config: str = typer.Option("config.yaml", help="설정 파일 경로")) -> None:
    """DB 테이블 생성(존재 시 무시)."""
    cfg, _ = _load(config)
    engine = make_engine(cfg.app.db_path)
    init_db(engine)
    typer.echo(f"✅ DB 초기화 완료: {Path(cfg.app.db_path).resolve()}")


def _preview_personalized(engine, settings, build_for) -> None:
    """구독자별로 받게 될 다이제스트를 터미널에 출력(dry-run — 발송하지 않음).

    발송과 동일한 telegram.build_personalized 로직을 타므로, 운영자=전체·일반=공통∪본인구독이
    실제 발송 전에 그대로 검증된다.
    """
    from .notify import telegram

    plans = telegram.build_personalized(engine, settings, build_for)
    typer.echo("----- 구독자별 미리보기(dry-run) -----")
    if not plans:
        typer.echo("(보낼 구독자 없음 — 변동이 각자 밴드·단지 밖)")
    for chat_id, text in plans:
        typer.echo(f"\n[{chat_id}]")
        typer.echo(_html_to_text(text))
    typer.echo("------------------------------------\n")


@app.command()
def collect(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    trigger: str = typer.Option("manual", help="scheduled | manual"),
) -> None:
    """매물 1회 수집 → diff → (변화 시) 텔레그램 알림."""
    from .core.collector import (
        CollectionInterrupted,
        CollectorLocked,
        RunResult,
        install_term_handler,
        run_collection,
    )
    from .notify import telegram
    from .notify.digest import build_digest

    install_term_handler()  # 취소·kill(SIGTERM) 시 run 을 FAILED 로 정리(좀비 방지)
    cfg, settings = _load(config)
    engine = make_engine(cfg.app.db_path)
    init_db(engine)

    notifier = telegram.from_settings(settings)
    if notifier is None:
        log.warning("텔레그램 미설정(.env) — 알림 없이 수집만 합니다.")

    def _notify(result: RunResult) -> None:
        full = build_digest(  # 전체(밴드무관) — 미리보기/하트비트
            result, cfg.app.dashboard_url, show_flash=cfg.flash.notify
        )
        typer.echo("\n----- 다이제스트 미리보기(전체) -----")
        typer.echo(_html_to_text(full or ""))
        typer.echo("------------------------------------\n")
        _preview_personalized(
            engine,
            settings,
            lambda lo, hi, only: build_digest(
                result, cfg.app.dashboard_url, price_min=lo, price_max=hi,
                only_complexes=only, drop_empty=True, show_flash=cfg.flash.notify,
            ),
        )
        if notifier is None:
            return
        if result.total_changes == 0:  # 하트비트: 거를 변동이 없으니 전체에 그대로
            telegram.broadcast(notifier, engine, full)
            typer.echo("📨 텔레그램 전송 완료(전체)")
        else:
            sent = telegram.broadcast_personalized(
                notifier,
                engine,
                settings,
                lambda lo, hi, only: build_digest(
                    result, cfg.app.dashboard_url, price_min=lo, price_max=hi,
                    only_complexes=only, drop_empty=True, show_flash=cfg.flash.notify,
                ),
            )
            typer.echo(f"📨 텔레그램 전송 완료({sent}명 — 가격밴드·단지별)")

    try:
        result = run_collection(cfg, settings, engine, trigger=trigger, notify=_notify)
    except CollectorLocked as e:
        typer.secho(f"⏳ {e} — 건너뜁니다.", fg="yellow")
        raise typer.Exit(code=0) from None
    except CollectionInterrupted as e:
        typer.secho(f"🛑 {e} — 수집 중단(run 은 FAILED 로 정리됨).", fg="yellow")
        raise typer.Exit(code=0) from None
    finally:
        if notifier is not None:
            notifier.close()

    typer.echo(
        f"완료: 상태={result.status.value} · 타겟 {result.targets_count} · "
        f"수집 {result.articles_fetched} · 신규 {result.new_count} · "
        f"가격변동 {result.price_changed_count} · 거래완료 {result.removed_count} · "
        f"오류 {result.http_errors}"
    )
    _auto_sync_push(cfg, settings, result.status)


@app.command(name="collect-deals")
def collect_deals(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    trigger: str = typer.Option("manual", help="scheduled | manual"),
) -> None:
    """실거래(국토부) 1회 수집 → diff(신규/취소) → (변화 시) 텔레그램 알림."""
    from .core.collector import CollectionInterrupted, install_term_handler
    from .core.deal_collector import CollectorLocked, DealRunResult, run_deal_collection
    from .notify import telegram
    from .notify.deal_digest import build_deal_digest

    install_term_handler()  # 취소·kill(SIGTERM) 시 run 을 FAILED 로 정리(좀비 방지)
    cfg, settings = _load(config)
    if not cfg.deals.enabled:
        typer.secho("⏸ 실거래 수집 비활성화 (config: deals.enabled=false)", fg="yellow")
        raise typer.Exit(code=0)
    engine = make_engine(cfg.app.db_path)
    init_db(engine)

    notifier = telegram.from_settings(settings)
    if notifier is None:
        log.warning("텔레그램 미설정(.env) — 알림 없이 수집만 합니다.")

    def _notify(result: DealRunResult) -> None:
        full = build_deal_digest(result, cfg.app.dashboard_url)
        typer.echo("\n----- 실거래 다이제스트 미리보기(전체) -----")
        typer.echo(_html_to_text(full or ""))
        typer.echo("------------------------------------------\n")
        _preview_personalized(
            engine,
            settings,
            lambda lo, hi, only: build_deal_digest(
                result, cfg.app.dashboard_url, price_min=lo, price_max=hi,
                only_complexes=only, drop_empty=True,
            ),
        )
        if notifier is None:
            return
        if result.total_changes == 0:
            telegram.broadcast(notifier, engine, full)
            typer.echo("📨 텔레그램 전송 완료(전체)")
        else:
            sent = telegram.broadcast_personalized(
                notifier,
                engine,
                settings,
                lambda lo, hi, only: build_deal_digest(
                    result, cfg.app.dashboard_url, price_min=lo, price_max=hi,
                    only_complexes=only, drop_empty=True,
                ),
            )
            typer.echo(f"📨 텔레그램 전송 완료({sent}명 — 가격밴드·단지별)")

    try:
        result = run_deal_collection(cfg, settings, engine, trigger=trigger, notify=_notify)
    except CollectorLocked as e:
        typer.secho(f"⏳ {e} — 건너뜁니다.", fg="yellow")
        raise typer.Exit(code=0) from None
    except CollectionInterrupted as e:
        typer.secho(f"🛑 {e} — 수집 중단(run 은 FAILED 로 정리됨).", fg="yellow")
        raise typer.Exit(code=0) from None
    finally:
        if notifier is not None:
            notifier.close()

    typer.echo(
        f"완료: 상태={result.status.value} · 타겟 {result.targets_count} · "
        f"신규 {result.new_count} · 취소 {result.cancelled_count} · 오류 {result.errors}"
    )
    _auto_sync_push(cfg, settings, result.status)


@app.command(name="collect-permits")
def collect_permits(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    trigger: str = typer.Option("manual", help="scheduled | manual"),
) -> None:
    """토지거래허가(서울시) 1회 수집 → diff(신규 허가) → (변화 시) 텔레그램 알림."""
    from .core.collector import CollectionInterrupted, CollectorLocked, install_term_handler
    from .core.permit_collector import PermitRunResult, run_permit_collection
    from .notify import telegram
    from .notify.permit_digest import build_permit_digest

    install_term_handler()  # 취소·kill(SIGTERM) 시 run 을 FAILED 로 정리(좀비 방지)
    cfg, settings = _load(config)
    if not cfg.permits.enabled:
        typer.secho("⏸ 토지거래허가 수집 비활성화 (config: permits.enabled=false)", fg="yellow")
        raise typer.Exit(code=0)
    engine = make_engine(cfg.app.db_path)
    init_db(engine)

    notifier = telegram.from_settings(settings)
    if notifier is None:
        log.warning("텔레그램 미설정(.env) — 알림 없이 수집만 합니다.")

    def _notify(result: PermitRunResult) -> None:
        msg = build_permit_digest(result, cfg.app.dashboard_url)
        typer.echo("\n----- 토지거래허가 다이제스트 미리보기 -----")
        typer.echo(_html_to_text(msg))
        typer.echo("--------------------------------------------\n")
        if notifier is not None:
            telegram.broadcast(notifier, engine, msg)
            typer.echo("📨 텔레그램 전송 완료")

    try:
        result = run_permit_collection(cfg, settings, engine, trigger=trigger, notify=_notify)
    except CollectorLocked as e:
        typer.secho(f"⏳ {e} — 건너뜁니다.", fg="yellow")
        raise typer.Exit(code=0) from None
    except CollectionInterrupted as e:
        typer.secho(f"🛑 {e} — 수집 중단(run 은 FAILED 로 정리됨).", fg="yellow")
        raise typer.Exit(code=0) from None
    finally:
        if notifier is not None:
            notifier.close()

    typer.echo(
        f"완료: 상태={result.status.value} · 단지 {result.targets_count} · "
        f"자치구 {result.sgg_count} · 신규 허가 {result.new_count} · "
        f"지번미보유 {result.missing_jibun} · 오류 {result.errors}"
    )
    _auto_sync_push(cfg, settings, result.status)


def _snapshot_engine(db_path: str):
    """실DB 를 임시 스냅샷으로 복제해 엔진 반환(dry-run — 원본 무변경·WAL 포함 정합 복제)."""
    import sqlite3
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".auction-dryrun.db", delete=False).name
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    engine = make_engine(tmp)
    init_db(engine)
    return engine


@app.command(name="collect-auctions")
def collect_auctions(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    trigger: str = typer.Option("manual", help="scheduled | manual"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="미리보기 — 텔레그램 발송·실DB 쓰기 없음(실DB 스냅샷에서 수집)"
    ),
) -> None:
    """법원경매(courtauction.go.kr) 1회 수집 → diff(신규·최저가하락) → (변화 시) 텔레그램 알림."""
    from .core.auction_collector import AuctionRunResult, run_auction_collection
    from .core.collector import CollectionInterrupted, CollectorLocked, install_term_handler
    from .notify import telegram
    from .notify.auction_digest import build_auction_digest

    install_term_handler()  # 취소·kill(SIGTERM) 시 run 을 FAILED 로 정리(좀비 방지)
    cfg, settings = _load(config)
    if not cfg.auctions.enabled:
        typer.secho("⏸ 법원경매 수집 비활성화 (config: auctions.enabled=false)", fg="yellow")
        raise typer.Exit(code=0)

    if dry_run:
        engine = _snapshot_engine(cfg.app.db_path)  # 실DB 스냅샷 — 발송·원본쓰기 없음
        notifier = None
        typer.secho("🔍 dry-run — 발송·실DB쓰기 없이 미리보기만 합니다.", fg="cyan")
    else:
        engine = make_engine(cfg.app.db_path)
        init_db(engine)
        notifier = telegram.from_settings(settings)
        if notifier is None:
            log.warning("텔레그램 미설정(.env) — 알림 없이 수집만 합니다.")

    def _notify(result: AuctionRunResult) -> None:
        msg = build_auction_digest(result, cfg.app.dashboard_url)
        typer.echo("\n----- 법원경매 다이제스트 미리보기 -----")
        typer.echo(_html_to_text(msg))
        typer.echo("----------------------------------------\n")
        if notifier is not None:
            telegram.broadcast(notifier, engine, msg)
            typer.echo("📨 텔레그램 전송 완료")

    try:
        result = run_auction_collection(cfg, settings, engine, trigger=trigger, notify=_notify)
    except CollectorLocked as e:
        typer.secho(f"⏳ {e} — 건너뜁니다.", fg="yellow")
        raise typer.Exit(code=0) from None
    except CollectionInterrupted as e:
        typer.secho(f"🛑 {e} — 수집 중단(run 은 FAILED 로 정리됨).", fg="yellow")
        raise typer.Exit(code=0) from None
    finally:
        if notifier is not None:
            notifier.close()

    typer.echo(
        f"완료: 상태={result.status.value} · 단지 {result.targets_count} · "
        f"법원 {result.court_count} · 신규 {result.new_count} · "
        f"최저가하락 {result.price_down_count} · 지번미보유 {result.missing_jibun} · "
        f"관할미상 {result.unmatched_court} · 오류 {result.errors}"
    )
    if not dry_run:  # dry-run 은 실DB 무변경 — 동기화 불필요
        _auto_sync_push(cfg, settings, result.status)


@app.command()
def discover(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    trigger: str = typer.Option("manual", help="scheduled | manual"),
) -> None:
    """주간 신규편입 단지 탐색 1회 (single-markers) → (신규 발견 시) 텔레그램 알림."""
    from .core.discover import CollectorLocked, DiscoverResult, run_discovery
    from .notify import telegram
    from .notify.discover_digest import build_discover_digest

    cfg, settings = _load(config)
    if not cfg.discover.enabled:
        typer.secho("⏸ 주간 탐색 비활성화 (config: discover.enabled=false)", fg="yellow")
        raise typer.Exit(code=0)
    if not cfg.discover.regions:
        typer.secho("⚠ 탐색 지역(discover.regions)이 없습니다.", fg="yellow")
        raise typer.Exit(code=0)
    engine = make_engine(cfg.app.db_path)
    init_db(engine)

    notifier = telegram.from_settings(settings)
    if notifier is None:
        log.warning("텔레그램 미설정(.env) — 알림 없이 탐색만 합니다.")

    def _notify(result: DiscoverResult) -> None:
        full = build_discover_digest(result, cfg.app.dashboard_url)
        typer.echo("\n----- 신규편입 다이제스트 미리보기(전체) -----")
        typer.echo(_html_to_text(full or ""))
        typer.echo("--------------------------------------------\n")
        if notifier is None:
            return
        if not result.new_candidates:
            telegram.broadcast(notifier, engine, full)
            typer.echo("📨 텔레그램 전송 완료(전체)")
        else:
            sent = telegram.broadcast_personalized(
                notifier,
                engine,
                lambda lo, hi: build_discover_digest(
                    result, cfg.app.dashboard_url, price_min=lo, price_max=hi, drop_empty=True
                ),
            )
            typer.echo(f"📨 텔레그램 전송 완료({sent}명 — 가격밴드별)")

    try:
        result = run_discovery(cfg, settings, engine, trigger=trigger, notify=_notify)
    except CollectorLocked as e:
        typer.secho(f"⏳ {e} — 건너뜁니다.", fg="yellow")
        raise typer.Exit(code=0) from None
    finally:
        if notifier is not None:
            notifier.close()

    if result.first_run:
        typer.echo(
            f"✅ baseline 확립: 후보 {result.total_found}개 기록(알림 없음). "
            "다음 회차부터 신규 편입분을 알립니다."
        )
    else:
        typer.echo(
            f"완료: 상태={result.status.value} · 지역 {len(result.regions)} · "
            f"편입 {result.total_found} · 신규 {len(result.new_candidates)} · "
            f"오류지역 {result.errors}"
        )


@app.command(name="add-complex")
def add_complex_cmd(
    complex_no: str = typer.Argument(..., help="네이버 단지번호"),
    alias: str = typer.Option("", help="단지 별칭(표시 이름)"),
    source: str = typer.Option("web", help="출처 태그: web | telegram"),
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
) -> None:
    """단지를 추적 목록에 추가하고 즉시 1회 매물 수집. 대시보드 '추적 추가'가 백그라운드로 호출한다."""
    from .core.collector import CollectorLocked
    from .core.on_demand import add_complex, track_complex
    from .naver.client import NaverLandClient

    if not complex_no.isdigit():
        typer.secho(f"❌ 단지번호는 숫자여야 합니다: {complex_no}", fg="red")
        raise typer.Exit(code=1)

    cfg, settings = _load(config)
    engine = make_engine(cfg.app.db_path)
    init_db(engine)

    # 1) 등록(락·네트워크 무관, 항상 성공) → 2) 즉시 수집 시도(정기 수집 중이면 건너뜀)
    nick = alias.strip() or None
    track_complex(cfg, engine, complex_no, alias=nick, source=source)
    typer.echo(f"🌐 단지 {complex_no} 추가 완료 — 첫 매물 수집 중…")
    try:
        with NaverLandClient(
            request_delay_seconds=cfg.app.request_delay_seconds, headless=cfg.app.headless
        ) as client:
            result = add_complex(
                cfg, settings, engine, complex_no, alias=nick, client=client, source=source
            )
    except CollectorLocked as e:
        typer.secho(f"⏳ {e} — 추적 등록은 완료, 수집은 다음 기회에.", fg="yellow")
        raise typer.Exit(code=0) from None

    r = result.run
    typer.echo(
        f"✅ {result.name}({result.complex_no}) · 상태={r.status.value} · "
        f"수집 {r.articles_fetched} · 신규 {r.new_count}"
    )


@app.command(name="test-notify")
def test_notify(config: str = typer.Option("config.yaml", help="설정 파일 경로")) -> None:
    """텔레그램 채널 연결 테스트 메시지 전송."""
    cfg, settings = _load(config)
    from .notify import telegram

    notifier = telegram.from_settings(settings)
    if notifier is None:
        typer.secho(
            "❌ 텔레그램 미설정 — .env 에 TELEGRAM_BOT_TOKEN 을 넣으세요.",
            fg="red",
        )
        raise typer.Exit(code=1)
    engine = make_engine(cfg.app.db_path)
    init_db(engine)
    from .db.engine import get_session
    from .db.repo import get_active_subscriber_ids

    with get_session(engine) as session:
        ids = get_active_subscriber_ids(session)
    if not ids:
        typer.secho("⚠ 구독자가 없습니다. 봇에게 메시지를 보내 먼저 구독하세요.", fg="yellow")
        raise typer.Exit(code=0)
    log.info("토큰=%s 구독자 %d명에게 전송", mask_secret(settings.telegram_bot_token), len(ids))
    telegram.broadcast(notifier, engine, "🏠 <b>myhouse</b> 텔레그램 연결 테스트 — 정상 수신되면 설정 완료입니다.")
    notifier.close()
    typer.echo(f"✅ 전송 완료({len(ids)}명) — 텔레그램을 확인하세요.")


@app.command(name="setup-commands")
def setup_commands(config: str = typer.Option("config.yaml", help="설정 파일 경로")) -> None:
    """텔레그램 봇 명령 자동완성 메뉴를 등록한다 (setMyCommands)."""
    _, settings = _load(config)
    from .notify import telegram

    notifier = telegram.from_settings(settings)
    if notifier is None:
        typer.secho("❌ 텔레그램 미설정 — .env 에 TELEGRAM_BOT_TOKEN 을 넣으세요.", fg="red")
        raise typer.Exit(code=1)

    commands = [
        {"command": "join",     "description": "초대코드로 참여 — /join 초대코드"},
        {"command": "start",    "description": "알림 구독 시작 + 도움말"},
        {"command": "stop",     "description": "알림 구독 해제"},
        {"command": "list",     "description": "텔레그램으로 추가한 단지 목록"},
        {"command": "add",      "description": "단지 추가 — /add 1234 또는 /add 단지명"},
        {"command": "check",    "description": "매물 즉시 조회 — /check 1234 또는 /check 단지명"},
        {"command": "deals",    "description": "실거래 조회 — /deals 1234 또는 /deals 단지명"},
        {"command": "permits",  "description": "토지거래허가 조회 — /permits [단지명]"},
        {"command": "discover", "description": "지역 신규편입 단지 즉시 탐색"},
        {"command": "band",     "description": "관심 가격대(억) 설정 — /band 7 12 (보기: /band)"},
        {"command": "help",     "description": "명령어 도움말"},
    ]
    notifier.set_commands(commands)
    notifier.close()
    typer.echo(f"✅ {len(commands)}개 명령어 등록 완료 — 텔레그램에서 / 를 눌러 확인하세요.")


@app.command()
def probe(
    complex_no: str = typer.Argument(..., help="네이버 단지번호"),
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="브라우저 표시(디버그)"),
    limit: int = typer.Option(5, help="출력할 매물 수"),
) -> None:
    """단지 매물을 실제로 수집해 new.land 연동을 검증 (헤드리스 브라우저로 토큰 자동 발급)."""
    cfg, _ = _load(config)
    from .db.models import Complex
    from .naver.client import NaverLandClient

    target = next(
        (t for t in cfg.targets if t.kind == "complex" and t.complex_no == complex_no),
        None,
    )
    filt = cfg.effective_filter(target) if target else cfg.defaults
    cx = Complex(complex_no=complex_no)

    typer.echo("🌐 헤드리스 브라우저로 토큰 발급 + 수집 중…")
    with NaverLandClient(
        request_delay_seconds=cfg.app.request_delay_seconds, headless=headless
    ) as client:
        result = client.fetch_articles(cx, filt)

    typer.echo(
        f"수집 {result.raw_count}건 (파싱성공 {len(result.articles)}, 실패 {result.parse_failures}) · "
        f"페이지 {result.pages} · 완료={result.complete}"
    )
    for dto in result.articles[:limit]:
        typer.echo(dto.model_dump_json(indent=2))


@app.command(name="probe-deals")
def probe_deals(
    complex_no: str = typer.Argument(..., help="네이버 단지번호"),
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="브라우저 표시(디버그)"),
    year: int = typer.Option(3, help="실거래 조회 기간(년)"),
    limit: int = typer.Option(10, help="출력할 거래 수"),
) -> None:
    """단지 실거래를 실제로 수집해 new.land prices/real 연동을 검증."""
    cfg, _ = _load(config)
    from .constants import NAVER_TRADE_CODE
    from .core.deal_collector import select_pyeongs
    from .naver.client import NaverLandClient

    target = next(
        (t for t in cfg.targets if t.kind == "complex" and t.complex_no == complex_no), None
    )
    filt = cfg.effective_filter(target) if target else cfg.defaults
    trade_codes = [NAVER_TRADE_CODE[t] for t in cfg.deals.trade_types]

    typer.echo("🌐 헤드리스 브라우저로 토큰 발급 + 평형/실거래 수집 중…")
    with NaverLandClient(
        request_delay_seconds=cfg.app.request_delay_seconds, headless=headless
    ) as client:
        pyeongs = client.fetch_pyeongs(complex_no)
        selected = select_pyeongs(pyeongs, filt, cfg.deals.use_area_filter)
        typer.echo(
            f"평형 {len(pyeongs)}종 중 면적필터 통과 {len(selected)}종: "
            + ", ".join(
                f"{p.pyeong_name}({p.area_supply:g}㎡공급)" for p in selected if p.area_supply
            )
        )
        result = client.fetch_deals(complex_no, selected, trade_codes, year=year)

    typer.echo(f"수집 {result.raw_count}건 · 평형 {result.pyeongs}종 · 완료={result.complete}")
    for d in sorted(result.deals, key=lambda x: x.deal_date, reverse=True)[:limit]:
        flag = " [취소]" if d.cancelled else ""
        typer.echo(
            f"  {d.deal_date}  {d.pyeong_name or ''}({d.area_excl}㎡)  "
            f"{d.price_deal}만  {d.floor}층{flag}"
        )


@app.command(name="probe-permits")
def probe_permits(
    sgg: str = typer.Argument(..., help="자치구 코드(11680) 또는 이름(강남구)"),
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    days: int = typer.Option(60, help="조회 기간(일, 최대 62)"),
    limit: int = typer.Option(20, help="출력할 허가 건수"),
) -> None:
    """서울시 토지거래허가 내역을 직접 조회해 land.seoul.go.kr 연동을 검증(브라우저 불필요)."""
    import collections
    from datetime import timedelta

    from .constants import now_kst
    from .seoul.client import SeoulLandClient
    from .seoul.permit_parser import RESIDENTIAL

    _load(config)
    now = now_kst()
    end_s = now.strftime("%Y%m%d")
    begin_s = (now - timedelta(days=min(days, 62))).strftime("%Y%m%d")

    typer.echo("🌐 land.seoul.go.kr 조회 중…")
    with SeoulLandClient() as client:
        sgg_map = client.fetch_sgg_list()
        sgg_cd = sgg if sgg.isdigit() else next((k for k, v in sgg_map.items() if v == sgg), "")
        if not sgg_cd or sgg_cd not in sgg_map:
            typer.secho(f"자치구를 찾을 수 없습니다: {sgg}", fg="red")
            raise typer.Exit(code=1)
        permits = client.fetch_permits(sgg_cd, begin_s, end_s)

    res = [p for p in permits if p.use_purp == RESIDENTIAL]
    typer.echo(
        f"{sgg_map[sgg_cd]}({sgg_cd}) {begin_s}~{end_s}: 전체 {len(permits)}건 · 주거용 {len(res)}건"
    )
    dist = collections.Counter(p.job_gbn for p in permits)
    typer.echo("처리구분: " + ", ".join(f"{k} {v}" for k, v in dist.items()))
    for p in sorted(res, key=lambda x: x.permit_date or "", reverse=True)[:limit]:
        jb = f"{p.bonbun}-{p.bubun}" if p.bonbun else "?"
        typer.echo(f"  {p.permit_date}  {p.address}  [{jb}]  {p.job_gbn}")


@app.command(name="probe-permits-gc")
def probe_permits_gc(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    months: int = typer.Option(3, help="최신 월별 글 N개 조회"),
    limit: int = typer.Option(30, help="출력할 허가 건수"),
) -> None:
    """과천시 토지거래허가내역(gccity.go.kr 게시판 HWP)을 직접 조회해 연동을 검증(브라우저 불필요)."""
    import collections

    from .gyeonggi.client import GwacheonLandClient
    from .seoul.permit_parser import RESIDENTIAL

    _load(config)
    typer.echo("🌐 gccity.go.kr 토지거래허가내역 조회 중…")
    with GwacheonLandClient() as client:
        posts = client.list_posts()
        typer.echo(
            f"게시판 글 {len(posts)}건 · 최신: "
            + ", ".join(f"{y}.{m}" for _b, y, m in posts[:months])
        )
        permits = client.fetch_months(months)

    res = [p for p in permits if p.use_purp == RESIDENTIAL]
    typer.echo(f"최신 {months}개월: 전체 {len(permits)}건 · 주거용 {len(res)}건")
    dist = collections.Counter(p.use_purp for p in permits)
    typer.echo("이용목적: " + ", ".join(f"{k} {v}" for k, v in dist.items()))
    for p in sorted(res, key=lambda x: x.permit_date or "", reverse=True)[:limit]:
        jb = f"{p.bonbun}-{p.bubun}" if p.bonbun else "?"
        cortar = p.lawd_cd or "미매핑"
        typer.echo(f"  {p.permit_date}  {p.address}  [{jb}·{cortar}]  {p.job_gbn}")


@app.command(name="probe-auctions")
def probe_auctions(
    court: str = typer.Argument(..., help="법원코드(B000210) 또는 이름(서울중앙)"),
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    days: int = typer.Option(30, help="매각기일 윈도우(오늘~+N일)"),
    pages: int = typer.Option(2, help="조회 페이지 수(페이지당 40)"),
    apt_only: bool = typer.Option(True, "--apt-only/--all-usage", help="아파트만 출력"),
    limit: int = typer.Option(20, help="출력 건수"),
) -> None:
    """법원경매(courtauction.go.kr 신규시스템)를 직접 조회해 연동을 검증(브라우저 불필요)."""
    import collections
    from datetime import timedelta

    from .court.client import CourtAuctionClient

    _load(config)
    now = now_kst()
    begin_s = now.strftime("%Y%m%d")
    end_s = (now + timedelta(days=days)).strftime("%Y%m%d")

    typer.echo("🌐 courtauction.go.kr 조회 중…")
    with CourtAuctionClient() as client:
        court_map = client.fetch_courts()
        court_cd = (
            court.upper()
            if court.upper().startswith("B")
            else next((k for k, v in court_map.items() if court in v), "")
        )
        if not court_cd:
            hint = "" if court_map else " (법원목록 조회 실패 — 코드로 지정: 예 B000210)"
            typer.secho(f"법원을 찾을 수 없습니다: {court}{hint}", fg="red")
            raise typer.Exit(code=1)
        auctions = client.fetch_auctions(court_cd, begin_s, end_s, max_pages=pages)

    apt = [a for a in auctions if a.is_apartment]
    shown = apt if apt_only else auctions
    name = court_map.get(court_cd, court_cd)
    typer.echo(f"{name}({court_cd}) {begin_s}~{end_s}: 전체 {len(auctions)}건 · 아파트 {len(apt)}건")
    dist = collections.Counter(a.usage_name or "?" for a in auctions)
    typer.echo("용도: " + ", ".join(f"{k} {v}" for k, v in dist.most_common(8)))
    for a in sorted(shown, key=lambda x: x.sale_date or "")[:limit]:
        jb = f"{a.bonbun}-{a.bubun}" if a.bonbun else "?"
        bld = f" {a.building_name}" if a.building_name else ""
        typer.echo(
            f"  {a.sale_date}  {a.case_no}  {a.address}{bld}  "
            f"[{jb}·동{a.dong_code}]  감정 {a.appraisal_manwon}만 · "
            f"최저 {a.min_bid_manwon}만({a.min_bid_ratio}%) · 유찰 {a.fail_count}"
        )


@app.command(name="probe-auction1")
def probe_auction1(
    case_no: str = typer.Argument(..., help="사건번호 예: 2024타경6190"),
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    dump: bool = typer.Option(False, "--dump", help="파싱 실패 시 응답 HTML 일부 출력(구조 확인용)"),
) -> None:
    """옥션원 사건검색으로 product_id→직링크 해석 검증(.env AUCTION1_COOKIE 필요·본인 머신에서)."""
    from .court.auction1_resolver import (
        fetch_list_html,
        looks_logged_out,
        parse_case_no,
        resolve_view_url,
    )

    _, settings = _load(config)
    cookie = settings.auction1_cookie
    if not cookie:
        typer.secho("AUCTION1_COOKIE 가 .env 에 없습니다 (옥션원 세션 쿠키 설정 후 재시도).", fg="red")
        raise typer.Exit(code=1)
    if parse_case_no(case_no) is None:
        typer.secho(f"사건번호 형식을 못 읽었습니다: {case_no} (예: 2024타경6190)", fg="red")
        raise typer.Exit(code=1)

    typer.echo("🌐 옥션원 사건검색 중…")
    url = resolve_view_url(case_no, cookie)
    if url:
        typer.secho(f"✅ {case_no} → {url}", fg="green")
        return

    typer.secho(f"❌ product_id 미해석: {case_no}", fg="yellow")
    html = fetch_list_html(case_no, cookie)
    if html is None:
        typer.echo("   검색 요청 실패 — 쿠키/네트워크를 확인하세요.")
        raise typer.Exit(code=1)
    if looks_logged_out(html):
        typer.secho("   로그인 만료로 보입니다 — .env AUCTION1_COOKIE 갱신 필요.", fg="yellow")
    typer.echo(f"   응답 {len(html)}자 · product_id 패턴 미발견.")
    if dump:
        import re as _re

        calls = _re.findall(r"[A-Za-z_]\w*\(\s*\d{5,}\s*,[^)]{0,40}", html)
        typer.echo(f"숫자호출(행 클릭 핸들러) 후보 {len(calls)}개 — 상위 6:")
        for c in calls[:6]:
            typer.echo("   " + c)
        i = html.find("ck_pid")
        if i >= 0:
            typer.echo("\n----- ck_pid 주변 HTML -----")
            typer.echo(html[max(0, i - 150) : i + 250])
            typer.echo("----------------------------")
    else:
        typer.echo("   --dump 로 HTML 구조를 확인해 파서를 맞출 수 있습니다.")


@app.command(name="probe-search")
def probe_search(
    keyword: str = typer.Argument(..., help="검색어(단지명 또는 주소). 예: '방배 삼호1차'"),
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    seed: str = typer.Option("947", help="토큰 발급용 seed 단지번호"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="브라우저 표시(디버그)"),
) -> None:
    """단지명/주소 검색(주소→단지번호 역추적) new.land /api/search 연동을 검증."""
    cfg, _ = _load(config)
    from .naver.client import NaverLandClient

    typer.echo(f"🌐 '{keyword}' 검색 중… (seed={seed})")
    with NaverLandClient(
        request_delay_seconds=cfg.app.request_delay_seconds, headless=headless
    ) as client:
        hits = client.search_complexes(keyword, seed_complex_no=seed)

    typer.echo(f"검색 결과 {len(hits)}건")
    for h in hits:
        bits = [f"  {h.complex_no}  {h.name}"]
        if h.address:
            bits.append(h.address)
        if h.type_name:
            bits.append(h.type_name)
        if h.households:
            bits.append(f"{h.households}세대")
        typer.echo(" · ".join(bits))


@app.command(name="probe-markers")
def probe_markers(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    region: str = typer.Option("", help="특정 지역 라벨만(비우면 전체)"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="브라우저 표시(디버그)"),
    limit: int = typer.Option(8, help="지역별 출력할 단지 수"),
) -> None:
    """지역 single-markers 탐색을 실제로 수집해 연동 검증(지역별 밴드 편입 단지 카운트)."""
    cfg, _ = _load(config)
    from .naver.client import NaverLandClient

    disc = cfg.discover
    regions = [r for r in disc.regions if not region or r.name == region]
    if not regions:
        typer.secho(f"⚠ 탐색 지역이 없습니다(필터: '{region}').", fg="yellow")
        raise typer.Exit(code=0)
    seed = disc.seed_complex_no or next(
        (t.complex_no for t in cfg.targets if t.kind == "complex" and t.complex_no), "947"
    )

    typer.echo(
        f"🌐 헤드리스 브라우저로 토큰 발급(seed={seed}) + 마커 수집 중… "
        f"(매매 {disc.price_min_manwon:,}~{disc.price_max_manwon:,}만 · 세대수≥{disc.min_households})"
    )
    total: set[str] = set()
    with NaverLandClient(
        request_delay_seconds=cfg.app.request_delay_seconds, headless=headless
    ) as client:
        for r in regions:
            try:
                markers = client.fetch_markers(r, disc, seed_complex_no=seed)
            except Exception as e:  # noqa: BLE001
                typer.secho(f"  {r.name}: 실패 — {e}", fg="red")
                continue
            cap = "  ⚠️500캡" if len(markers) >= 500 else ""
            typer.echo(f"\n■ {r.name}: {len(markers)}개 편입{cap}")
            for dc in sorted(markers, key=lambda d: (d.min_deal_price or 0))[:limit]:
                total.add(dc.complex_no)
                typer.echo(
                    f"    {dc.complex_no} {dc.name} · {dc.min_deal_price:,}~{dc.max_deal_price:,}만 "
                    f"· {dc.total_households}세대 · {dc.min_area}~{dc.max_area}㎡ · {dc.real_estate_type}"
                )
            for dc in markers:
                total.add(dc.complex_no)
    typer.echo(f"\n전체 고유 편입 단지: {len(total)}개")


@app.command(name="bulk-import")
def bulk_import(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    region: str = typer.Option("", help="특정 지역 라벨만(비우면 전체 discover.regions)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="실제 쓰지 않고 추가될 목록만 출력"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="브라우저 표시(디버그)"),
) -> None:
    """discover.regions 마커를 수집해 config.yaml targets에 일괄 추가 (이미 있는 단지는 건너뜀)."""
    cfg, _ = _load(config)
    from .naver.client import NaverLandClient

    disc = cfg.discover
    regions = [r for r in disc.regions if not region or r.name == region]
    if not regions:
        typer.secho(f"⚠ 탐색 지역이 없습니다(필터: '{region}').", fg="yellow")
        raise typer.Exit(code=0)

    seed = disc.seed_complex_no or next(
        (t.complex_no for t in cfg.targets if t.kind == "complex" and t.complex_no), "947"
    )

    # 이미 config.yaml에 등록된 단지 번호 세트
    existing_nos: set[str] = {
        t.complex_no for t in cfg.targets if t.kind == "complex" and t.complex_no
    }

    typer.echo(
        f"🌐 헤드리스 브라우저로 토큰 발급(seed={seed}) + 마커 수집 중… "
        f"(매매 {disc.price_min_manwon:,}~{disc.price_max_manwon:,}만 · 세대수≥{disc.min_households})"
    )

    to_add: list[tuple[str, str, str]] = []  # (region_name, complex_no, label)
    with NaverLandClient(
        request_delay_seconds=cfg.app.request_delay_seconds, headless=headless
    ) as client:
        for r in regions:
            try:
                markers = client.fetch_markers(r, disc, seed_complex_no=seed)
            except Exception as e:  # noqa: BLE001
                typer.secho(f"  {r.name}: 실패 — {e}", fg="red")
                continue
            new_here = [m for m in markers if m.complex_no not in existing_nos]
            typer.echo(f"\n■ {r.name}: 전체 {len(markers)}개 · 신규 {len(new_here)}개")
            for m in sorted(new_here, key=lambda d: (d.min_deal_price or 0)):
                typer.echo(
                    f"    + {m.complex_no}  {m.name}"
                    f"  {m.min_deal_price:,}~{m.max_deal_price:,}만  {m.total_households}세대"
                )
                to_add.append((r.name, m.complex_no, m.name))
                existing_nos.add(m.complex_no)  # 지역 간 중복 방지

    if not to_add:
        typer.secho("\n✅ 추가할 신규 단지 없음 (모두 이미 등록됨)", fg="green")
        return

    typer.echo(f"\n총 {len(to_add)}개 단지를 추가합니다.")

    if dry_run:
        typer.secho("--dry-run: config.yaml에 쓰지 않습니다.", fg="yellow")
        return

    # config.yaml 끝에 append (기존 주석·포맷 보존)
    config_path = Path(config)
    lines: list[str] = []
    cur_region = ""
    for region_name, complex_no, label in to_add:
        if region_name != cur_region:
            lines.append(f"  # ── {region_name} (bulk-import) ──\n")
            cur_region = region_name
        lines.append(f"  - kind: complex\n    complex_no: \"{complex_no}\"\n    label: \"{label}\"\n")

    with config_path.open("a", encoding="utf-8") as f:
        f.write("\n")
        f.writelines(lines)

    typer.secho(f"\n✅ {len(to_add)}개 단지를 {config_path}에 추가 완료", fg="green")
    typer.echo("이후 'myhouse collect'를 실행하면 전체 수집이 시작됩니다.")


@app.command(name="fill-meta")
def fill_meta(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    limit: int = typer.Option(500, help="처리할 최대 단지 수"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="브라우저 표시(디버그)"),
) -> None:
    """메타 비거나 준공/입주일이 빈 단지에 세대수/동수/준공·입주/용적률/건폐율을 채운다 (Naver 단지 API 호출).

    분양권 단지는 예전 파서가 6자리 입주예정일(YYYYMM)을 버려 use_approve_ymd 만 비어있을 수
    있으므로 floor_area_ratio 뿐 아니라 use_approve_ymd 누락도 대상에 포함한다(부분 백필).
    """
    from sqlmodel import Session, select

    from .db import repo
    from .db.engine import make_engine
    from .db.models import Complex
    from .naver.client import NaverLandClient

    cfg, _ = _load(config)
    engine = make_engine(cfg.app.db_path)

    with Session(engine) as session:
        targets = session.exec(
            select(Complex)
            .where((Complex.floor_area_ratio == None) | (Complex.use_approve_ymd == None))  # noqa: E711
            .limit(limit)
        ).all()

    if not targets:
        typer.echo("✅ 메타 없는 단지가 없습니다.")
        return

    typer.echo(f"🌐 헤드리스 브라우저로 단지 메타 조회 시작 ({len(targets)}개 단지)")
    ok = fail = 0
    with NaverLandClient(headless=headless) as client:
        for cx in targets:
            meta = client.fetch_complex_meta(cx.complex_no)
            with Session(engine) as session:
                if meta and (meta.floor_area_ratio is not None or meta.use_approve_ymd is not None):
                    repo.upsert_complex(
                        session,
                        cx.complex_no,
                        lat=meta.lat,
                        lon=meta.lon,
                        total_households=meta.total_households,
                        total_dong_count=meta.total_dong_count,
                        use_approve_ymd=meta.use_approve_ymd,
                        floor_area_ratio=meta.floor_area_ratio,
                        building_coverage_ratio=meta.building_coverage_ratio,
                    )
                    typer.echo(
                        f"  ✅ {cx.complex_no} {cx.name}: "
                        f"{meta.total_households}세대({meta.total_dong_count}동) "
                        f"{meta.use_approve_ymd} 용적률{meta.floor_area_ratio}%"
                    )
                    ok += 1
                else:
                    typer.echo(f"  ⚠  {cx.complex_no} {cx.name}: 메타 없음")
                    fail += 1

    typer.echo(f"\n완료: 성공 {ok} / 실패 {fail}")


@app.command(name="fill-coords")
def fill_coords(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    limit: int = typer.Option(100, help="처리할 최대 단지 수"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="브라우저 표시(디버그)"),
) -> None:
    """좌표 미설정 단지에 lat/lon을 일괄 채운다 (Naver 단지 API 호출)."""
    from sqlmodel import Session, select

    from .db import repo
    from .db.engine import make_engine
    from .db.models import Complex
    from .naver.client import NaverLandClient

    cfg, _ = _load(config)
    engine = make_engine(cfg.app.db_path)

    with Session(engine) as session:
        targets = session.exec(
            select(Complex).where(Complex.lat == None).limit(limit)  # noqa: E711
        ).all()

    if not targets:
        typer.echo("✅ 좌표 없는 단지가 없습니다.")
        return

    typer.echo(f"🌐 헤드리스 브라우저로 좌표 조회 시작 ({len(targets)}개 단지)")
    ok = fail = 0
    with NaverLandClient(headless=headless) as client:
        for cx in targets:
            coords = client.fetch_complex_coords(cx.complex_no)
            with Session(engine) as session:
                if coords:
                    repo.upsert_complex(session, cx.complex_no, lat=coords[0], lon=coords[1])
                    typer.echo(f"  ✅ {cx.complex_no} {cx.name}: {coords}")
                    ok += 1
                else:
                    typer.echo(f"  ⚠  {cx.complex_no} {cx.name}: 좌표 없음")
                    fail += 1

    typer.echo(f"\n완료: 성공 {ok} / 실패 {fail}")


@app.command(name="fill-jibun")
def fill_jibun(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="브라우저 표시(디버그)"),
    only: str = typer.Option("", help="쉼표구분 단지번호(미지정=지번 없는 전 단지)"),
) -> None:
    """추적단지 대표지번 백필(토지거래허가 매칭용). 네이버 단지상세를 단지당 1회 조회."""
    from .core.permit_backfill import backfill_jibun
    from .db.engine import get_session

    cfg, _ = _load(config)
    cfg.app.headless = headless
    engine = make_engine(cfg.app.db_path)
    init_db(engine)
    nos = [s.strip() for s in only.split(",") if s.strip()] or None

    typer.echo("🌐 네이버 단지상세로 지번 백필 중…")
    with get_session(engine) as session:

        def _prog(no: str, name: str, ok: bool) -> None:
            typer.echo(f"  {'✅' if ok else '❌'} {no} {name}")

        filled = backfill_jibun(cfg, session, complex_nos=nos, progress=_prog)
    typer.echo(f"\n완료: {filled} 단지 지번 채움")


@app.command()
def serve(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765),
) -> None:
    """로컬 대시보드 서버 실행. create_app 팩토리가 엔진/DB 초기화를 담당한다."""
    import uvicorn

    _load(config)  # 설정 검증(없으면 명확한 에러)
    os.environ["MYHOUSE_CONFIG"] = config  # 팩토리가 읽을 config 경로 전달
    typer.echo(f"🌐 대시보드: http://{host}:{port}  (config={config})")
    uvicorn.run(
        "myhouse.web.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
    )


@app.command()
def bot(
    config: str = typer.Option("config.yaml", help="설정 파일 경로"),
    poll_timeout: int = typer.Option(50, help="롱폴링 타임아웃(초)"),
) -> None:
    """텔레그램 양방향 봇(롱폴링) 실행 — /add /check /deals 명령 처리. 상시 구동용."""
    from .bot import run_bot

    run_bot(config, poll_timeout=poll_timeout)


@app.command(name="backup-db")
def backup_db(config: str = typer.Option("config.yaml", help="설정 파일 경로")) -> None:
    """SQLite 파일을 타임스탬프 사본으로 백업."""
    cfg, _ = _load(config)
    src = Path(cfg.app.db_path)
    if not src.exists():
        typer.secho(f"❌ DB 파일 없음: {src}", fg="red")
        raise typer.Exit(code=1)
    stamp = now_kst().strftime("%Y%m%d-%H%M%S")
    dst = src.with_name(f"{src.stem}.{stamp}.bak{src.suffix}")
    shutil.copy2(src, dst)
    typer.echo(f"✅ 백업: {dst}")


@app.command(name="sync-push")
def sync_push(config: str = typer.Option("config.yaml", help="설정 파일 경로")) -> None:
    """현재 DB 의 일관 스냅샷을 R2 에 업로드(클라우드 읽기 전용 서버가 받아 서빙).

    각 수집기(collect*) 성공 직후에 호출하면 클라우드가 최신 데이터를 받는다.
    """
    from .cloud.sync import push_db, s3_from_settings

    cfg, settings = _load(config)
    if s3_from_settings(settings) is None:
        typer.secho(
            "❌ R2 설정 없음 — .env 에 R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET",
            fg="red",
        )
        raise typer.Exit(code=1)
    src = Path(cfg.app.db_path)
    if not src.exists():
        typer.secho(f"❌ DB 파일 없음: {src}", fg="red")
        raise typer.Exit(code=1)
    etag = push_db(settings, str(src))
    typer.echo(f"✅ 업로드: {settings.r2_bucket}/{settings.r2_db_key} (etag={etag})")


if __name__ == "__main__":
    app()
