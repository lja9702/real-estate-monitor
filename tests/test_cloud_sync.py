"""DB 동기화 push/pull — 가짜 S3(딕트 백엔드)로 라운드트립·조건부 생략·원자성 검증."""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from myhouse.cloud.sync import pull_db, push_db, s3_from_settings
from myhouse.settings import Settings


class FakeS3:
    """put/get(If-None-Match)/head 만 흉내내는 인메모리 S3."""

    def __init__(self):
        self.store: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.get_calls = 0

    def put(self, bucket, key, body, content_type="application/octet-stream"):
        etag = '"' + hashlib.md5(body).hexdigest() + '"'  # noqa: S324 (etag 용도)
        self.store[(bucket, key)] = (body, etag)
        return etag

    def head(self, bucket, key):
        v = self.store.get((bucket, key))
        return v[1] if v else None

    def get(self, bucket, key, if_none_match=None):
        self.get_calls += 1
        v = self.store.get((bucket, key))
        if v is None:
            return None
        body, etag = v
        if if_none_match and if_none_match == etag:
            return None  # 304 미변경
        return body, etag


def _make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t(x INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    con.commit()
    con.close()


def _count(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT count(*) FROM t").fetchone()[0]
    finally:
        con.close()


def test_push_pull_roundtrip(tmp_path):
    src = tmp_path / "src.db"
    _make_db(src, [10, 20, 30])
    settings = Settings(_env_file=None, r2_bucket="b")
    fake = FakeS3()

    etag = push_db(settings, src, client=fake)
    assert etag

    dest = tmp_path / "sub" / "dest.db"  # 없는 디렉터리도 생성돼야 함
    state: dict = {}
    assert pull_db(settings, dest, client=fake, state=state) is True
    assert state["etag"] == etag
    assert _count(dest) == 3  # 스냅샷 내용 동일

    # 재pull — 미변경이면 다운로드 생략(False)
    assert pull_db(settings, dest, client=fake, state=state) is False

    # 원본 갱신 후 다시 push → pull 이 새 데이터 반영
    _make_db_append = sqlite3.connect(src)
    _make_db_append.execute("INSERT INTO t VALUES (40)")
    _make_db_append.commit()
    _make_db_append.close()
    push_db(settings, src, client=fake)
    assert pull_db(settings, dest, client=fake, state=state) is True
    assert _count(dest) == 4


def test_pull_missing_object_is_false(tmp_path):
    """아직 업로드 전이면(404) pull 은 False, 대상 파일도 안 만든다."""
    settings = Settings(_env_file=None, r2_bucket="b")
    dest = tmp_path / "dest.db"
    assert pull_db(settings, dest, client=FakeS3()) is False
    assert not dest.exists()


def test_s3_from_settings_gating():
    assert s3_from_settings(Settings(_env_file=None)) is None  # 미설정 → 비활성
    c = s3_from_settings(
        Settings(
            _env_file=None,
            r2_account_id="acc",
            r2_access_key_id="k",
            r2_secret_access_key="s",
            r2_bucket="b",
        )
    )
    assert c is not None
    assert "acc.r2.cloudflarestorage.com" in c.endpoint


def test_push_requires_config():
    with pytest.raises(RuntimeError):
        push_db(Settings(_env_file=None), "x.db")  # 클라이언트도 설정도 없음
