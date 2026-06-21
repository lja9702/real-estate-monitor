"""추적단지의 대표지번 백필 — 토지거래허가 매칭 준비.

네이버 단지상세(detailAddress)에서 (법정동코드, 본번/부번)을 얻어 complex 행에 저장한다.
브라우저(NaverLandClient)가 필요하므로 httpx 기반 permit_collector 와 분리 — 지번은 변하지
않으니 단지당 평생 1회면 충분하다. CLI `fill-jibun` 으로 collect-permits 전에 돌린다.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from sqlmodel import Session

from ..db import repo
from ..naver.client import NaverLandClient
from ..seoul.permit_parser import normalize_jibun
from ..settings import Config

log = logging.getLogger(__name__)


def backfill_jibun(
    config: Config,
    session: Session,
    *,
    complex_nos: list[str] | None = None,
    client: NaverLandClient | None = None,
    progress: Callable[[str, str, bool], None] | None = None,
) -> int:
    """지번 미보유 단지(또는 지정 단지)의 cortar_no·본번·부번을 채운다. 채운 단지 수 반환.

    progress(complex_no, name, ok) 가 주어지면 단지마다 호출(CLI 진행 표시용).
    """
    if complex_nos:
        rows = [c for c in (repo.get_complex(session, no) for no in complex_nos) if c]
    else:
        rows = repo.list_complexes_missing_jibun(session)

    own_client = client is None
    if own_client:
        client = NaverLandClient(
            request_delay_seconds=config.app.request_delay_seconds, headless=config.app.headless
        )
        client.__enter__()

    filled = 0
    try:
        for i, cx in enumerate(rows):
            if i > 0:
                time.sleep(random.uniform(*config.app.request_delay_seconds))
            res = client.fetch_complex_jibun(cx.complex_no)
            ok = False
            if res is not None:
                cortar, jibun = res
                norm = normalize_jibun(jibun)
                fields: dict[str, str] = {}
                if cortar:
                    fields["cortar_no"] = cortar
                if norm is not None:
                    fields["bonbun"], fields["bubun"] = norm
                if "bonbun" in fields:
                    repo.upsert_complex(session, cx.complex_no, **fields)
                    filled += 1
                    ok = True
                elif fields:
                    repo.upsert_complex(session, cx.complex_no, **fields)
            if not ok:
                log.warning("단지 %s(%s) 지번 백필 실패 — 매칭 제외", cx.complex_no, cx.name)
            if progress is not None:
                progress(cx.complex_no, cx.name, ok)
    finally:
        if own_client:
            client.close()

    log.info("지번 백필 완료: %d/%d 단지", filled, len(rows))
    return filled
