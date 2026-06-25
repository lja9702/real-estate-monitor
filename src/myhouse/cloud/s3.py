"""S3 호환 오브젝트 스토리지 최소 클라이언트 — 순수 httpx + SigV4 서명(boto3 미사용).

Cloudflare R2 기본 타깃(endpoint=<account>.r2.cloudflarestorage.com, region=auto, path-style).
DB 파일(수 MB) 단건 PUT/GET/HEAD 만 필요하므로 멀티파트 없이 단순 구현한다.
서명 정확성은 AWS 공식 SigV4 예제 벡터로 검증한다(tests/test_s3_sigv4.py).
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

_ALGORITHM = "AWS4-HMAC-SHA256"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    k_date = _hmac(("AWS4" + secret).encode("utf-8"), datestamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "aws4_request")


def _encode_path(path: str) -> str:
    """세그먼트별 URI 인코딩, '/' 보존(S3 는 경로를 한 번만 인코딩)."""
    return quote(path, safe="/~")


def sign_v4(
    *,
    method: str,
    host: str,
    path: str,
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str = "auto",
    service: str = "s3",
    amzdate: str | None = None,
    datestamp: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, str], str]:
    """SigV4 서명 헤더를 만들어 (headers, signature) 반환. 쿼리는 빈 문자열로 가정(단건 객체)."""
    amzdate = amzdate or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    datestamp = datestamp or amzdate[:8]
    payload_hash = _sha256_hex(body)

    headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amzdate}
    for k, v in (extra_headers or {}).items():
        headers[k.lower()] = v

    signed_names = sorted(headers)
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in signed_names)
    signed_headers = ";".join(signed_names)
    canonical_request = "\n".join(
        [method, _encode_path(path), "", canonical_headers, signed_headers, payload_hash]
    )

    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [_ALGORITHM, amzdate, scope, _sha256_hex(canonical_request.encode("utf-8"))]
    )
    signature = hmac.new(
        _signing_key(secret_key, datestamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        f"{_ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {**headers, "Authorization": authorization}, signature


class S3Client:
    """단건 객체 PUT/GET/HEAD 만 지원하는 최소 S3 호환 클라이언트(path-style)."""

    def __init__(
        self,
        *,
        access_key: str,
        secret_key: str,
        account_id: str | None = None,
        endpoint: str | None = None,
        region: str = "auto",
        timeout: float = 60.0,
    ) -> None:
        if endpoint is None:
            if not account_id:
                raise ValueError("account_id 또는 endpoint 가 필요합니다")
            endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        self.endpoint = endpoint.rstrip("/")
        self.host = httpx.URL(self.endpoint).host
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.timeout = timeout

    def _request(
        self, method: str, bucket: str, key: str, body: bytes = b"", extra_headers=None
    ) -> httpx.Response:
        path = f"/{bucket}/{key}"
        headers, _ = sign_v4(
            method=method,
            host=self.host,
            path=path,
            body=body,
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
            extra_headers=extra_headers,
        )
        url = f"{self.endpoint}{_encode_path(path)}"
        return httpx.request(method, url, headers=headers, content=body, timeout=self.timeout)

    def put(self, bucket: str, key: str, body: bytes, content_type="application/octet-stream") -> str | None:
        r = self._request("PUT", bucket, key, body, {"content-type": content_type})
        r.raise_for_status()
        return r.headers.get("etag")

    def head(self, bucket: str, key: str) -> str | None:
        r = self._request("HEAD", bucket, key)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.headers.get("etag")

    def get(self, bucket: str, key: str, if_none_match: str | None = None) -> tuple[bytes, str | None] | None:
        """객체 바이트와 etag. 변경 없음(304)·미존재(404)면 None."""
        extra = {"if-none-match": if_none_match} if if_none_match else None
        r = self._request("GET", bucket, key, extra_headers=extra)
        if r.status_code in (304, 404):
            return None
        r.raise_for_status()
        return r.content, r.headers.get("etag")
