"""초대코드 게이트 — 비활성(역호환)/활성(401·로그인) 동작 점검."""

from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from myhouse.settings import Settings
from myhouse.web.app import create_app
from myhouse.web.auth import sign_token, verify_token


def _app(
    tmp_path,
    *,
    codes: str | None = None,
    join_code: str | None = None,
    local_bypass: bool = True,
):
    """최소 설정으로 앱 생성. codes/join_code 가 주어지면 게이트 활성(설정 주입)."""
    db = tmp_path / "gate.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "app": {"db_path": str(db)},
                "defaults": {"trade_types": ["SALE"]},
                "targets": [{"kind": "complex", "complex_no": "111", "label": "테스트단지"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    app = create_app(str(cfg_path))
    # 저장소 루트의 실제 .env 에 의존하지 않도록 항상 설정을 주입(codes=None → 게이트 off).
    app.state.settings = Settings(
        _env_file=None,
        web_invite_codes=codes,
        telegram_join_code=join_code,
        session_secret="testsecret",
        gate_local_bypass=local_bypass,
    )
    return app


def test_invite_codes_union_telegram_join_code():
    """웹 초대코드 = WEB_INVITE_CODES ∪ TELEGRAM_JOIN_CODE."""
    s = Settings(_env_file=None, web_invite_codes="a, b", telegram_join_code="우리집2026")
    assert s.web_invite_code_set == {"a", "b", "우리집2026"}
    assert s.web_gate_enabled
    # 텔레그램 JOIN 코드만 있어도 게이트가 켜진다.
    assert Settings(_env_file=None, telegram_join_code="x").web_gate_enabled
    # 둘 다 없으면 게이트 off(역호환).
    assert not Settings(_env_file=None).web_gate_enabled


def test_gate_accepts_telegram_join_code(tmp_path):
    """별도 WEB_INVITE_CODES 없이 TELEGRAM_JOIN_CODE 만으로 게이트가 켜지고 그 코드로 입장."""
    client = TestClient(_app(tmp_path, join_code="우리집2026"))
    assert client.get("/api/listings").status_code == 401  # 게이트 활성
    ok = client.post("/gate", data={"code": "우리집2026", "next": "/"}, follow_redirects=False)
    assert ok.status_code == 303
    assert client.get("/api/listings").status_code == 200


def test_token_roundtrip():
    tok = sign_token("s3cret")
    assert verify_token("s3cret", tok)["r"] == "member"
    assert verify_token("wrong", tok) is None  # 서명 불일치
    assert verify_token("s3cret", tok + "x") is None  # 변조
    assert verify_token("s3cret", None) is None
    assert verify_token("s3cret", tok, max_age=-1) is None  # 만료


def test_gate_disabled_allows_all(tmp_path):
    """초대코드 미설정 → 게이트 off, 기존처럼 전체 허용."""
    client = TestClient(_app(tmp_path))
    assert client.get("/").status_code == 200
    assert client.get("/api/listings").status_code == 200
    assert client.get("/api/me").json()["authenticated"] is True


def test_gate_blocks_without_cookie(tmp_path):
    client = TestClient(_app(tmp_path, codes="letmein"))

    # HTML 요청은 게이트 페이지(200, SPA 셸 아님)
    r = client.get("/deals")
    assert r.status_code == 200
    assert "초대코드" in r.text
    assert 'id="root"' not in r.text

    # API 는 401
    assert client.get("/api/listings").status_code == 401
    assert client.get("/api/me").status_code == 401


def test_gate_login_flow(tmp_path):
    client = TestClient(_app(tmp_path, codes="letmein,friend2"))

    # 틀린 코드 → 401, 쿠키 미발급
    bad = client.post("/gate", data={"code": "nope", "next": "/deals"}, follow_redirects=False)
    assert bad.status_code == 401
    assert client.get("/api/listings").status_code == 401

    # 맞는 코드 → 303 리다이렉트(next 유지) + 쿠키 발급
    ok = client.post("/gate", data={"code": "friend2", "next": "/deals"}, follow_redirects=False)
    assert ok.status_code == 303
    assert ok.headers["location"] == "/deals"

    # 쿠키가 붙은 뒤로는 API/HTML 모두 통과
    assert client.get("/api/listings").status_code == 200
    assert client.get("/api/me").json() == {"authenticated": True, "role": "member", "readonly": False}
    assert 'id="root"' in client.get("/").text


def test_local_bypass_allows_loopback(tmp_path):
    """localhost(루프백) 접속은 코드 없이 통과 — 운영자 로컬 편의."""
    app = _app(tmp_path, join_code="우리집2026")
    local = TestClient(app, client=("127.0.0.1", 5555))
    assert local.get("/api/listings").status_code == 200
    assert local.get("/api/me").json() == {"authenticated": True, "role": "local", "readonly": False}
    assert 'id="root"' in local.get("/").text


def test_local_bypass_does_not_leak_to_proxy(tmp_path):
    """프록시(클라우드/터널) 경유는 X-Forwarded-* 헤더 때문에 면제되지 않는다."""
    app = _app(tmp_path, join_code="우리집2026")
    proxied = TestClient(app, client=("127.0.0.1", 5555))
    # 루프백 소켓이지만 프록시 헤더가 있으면 게이트 적용
    assert proxied.get("/api/listings", headers={"x-forwarded-for": "1.2.3.4"}).status_code == 401


def test_local_bypass_can_be_disabled(tmp_path):
    """GATE_LOCAL_BYPASS=false 면 localhost 도 코드를 요구."""
    app = _app(tmp_path, join_code="우리집2026", local_bypass=False)
    local = TestClient(app, client=("127.0.0.1", 5555))
    assert local.get("/api/listings").status_code == 401


def test_gate_open_redirect_blocked(tmp_path):
    client = TestClient(_app(tmp_path, codes="letmein"))
    # 외부 URL·`//` 는 루트로 정규화(오픈 리다이렉트 방지)
    r = client.post(
        "/gate", data={"code": "letmein", "next": "https://evil.example/x"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
