"""SigV4 서명 검증 — AWS 공식 문서의 'GET Object' 예제 벡터로 정확성 확인.

https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html
이 벡터가 통과하면 서명 알고리즘(canonical request·string-to-sign·signing key)이 정확하다.
"""

from __future__ import annotations

from myhouse.cloud.s3 import sign_v4

# AWS 공식 예제 자격증명(문서에 공개된 테스트 키)
_ACCESS = "AKIAIOSFODNN7EXAMPLE"
_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_aws_get_object_example_signature():
    headers, signature = sign_v4(
        method="GET",
        host="examplebucket.s3.amazonaws.com",
        path="/test.txt",
        body=b"",
        access_key=_ACCESS,
        secret_key=_SECRET,
        region="us-east-1",
        service="s3",
        amzdate="20130524T000000Z",
        extra_headers={"range": "bytes=0-9"},
    )
    assert signature == "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    assert headers["x-amz-content-sha256"] == _EMPTY_SHA256
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in headers["Authorization"]
    assert headers["Authorization"].startswith(f"AWS4-HMAC-SHA256 Credential={_ACCESS}/20130524/us-east-1/s3/aws4_request")
