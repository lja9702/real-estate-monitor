"""DB 동기화 — 맥(push)이 일관 스냅샷을 R2 에 올리고, 클라우드(pull)가 최신본을 받아 교체한다.

- push: sqlite online backup 으로 WAL 포함 정합 단일 파일을 만들어 업로드(원본 무변경).
- pull: 조건부 GET(If-None-Match)으로 미변경이면 생략, 변경 시 temp→원자적 rename 으로 교체.
R2 설정이 없으면 모든 함수가 안전하게 no-op/None 이라 동기화 없이도 동작한다.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from ..settings import Settings
from .s3 import S3Client


def s3_from_settings(settings: Settings) -> S3Client | None:
    """R2 자격증명이 모두 있으면 클라이언트, 하나라도 없으면 None(동기화 비활성)."""
    if not (
        settings.r2_account_id
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
        and settings.r2_bucket
    ):
        return None
    return S3Client(
        account_id=settings.r2_account_id,
        access_key=settings.r2_access_key_id,
        secret_key=settings.r2_secret_access_key,
    )


def consistent_snapshot_bytes(db_path: str | Path) -> bytes:
    """sqlite online backup 으로 WAL 포함 정합 단일 파일을 만들어 바이트로 반환(원본 무변경)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".sync.db", delete=False).name
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return Path(tmp).read_bytes()
    finally:
        Path(tmp).unlink(missing_ok=True)


def push_db(settings: Settings, db_path: str | Path, *, client: S3Client | None = None) -> str | None:
    """현재 DB 의 일관 스냅샷을 R2 에 업로드하고 etag 반환."""
    client = client or s3_from_settings(settings)
    if client is None:
        raise RuntimeError("R2 설정이 없습니다(R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET)")
    data = consistent_snapshot_bytes(db_path)
    return client.put(settings.r2_bucket, settings.r2_db_key, data)


def pull_db(
    settings: Settings,
    dest_path: str | Path,
    *,
    client: S3Client | None = None,
    state: dict | None = None,
) -> bool:
    """최신본을 받아 dest_path 로 원자적 교체. 변경 없음/미설정이면 False.

    state: {'etag': ...} 딕트(선택) — 조건부 GET 으로 미변경 시 다운로드를 생략한다.
    """
    client = client or s3_from_settings(settings)
    if client is None:
        return False
    prev_etag = (state or {}).get("etag")
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    # 스트리밍 다운로드(전체를 메모리에 올리지 않음 — 큰 DB·작은 머신 OOM 방지).
    etag = client.get_to_file(settings.r2_bucket, settings.r2_db_key, tmp, if_none_match=prev_etag)
    if etag is None:
        tmp.unlink(missing_ok=True)  # 304(미변경)·404(미업로드) — 부분 파일 없게
        return False
    os.replace(tmp, dest)  # 같은 디렉터리 내 원자적 교체
    if state is not None:
        state["etag"] = etag
    return True
