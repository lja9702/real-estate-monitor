"""[임시 probe] new.land 단지상세에 세대수/동수/사용승인일/용적률/건폐율이 오는지 확인.

단지 헤더에 '○○세대(○개동) · 1991년 준공 · 용적률 ○% · 건폐율 ○%' 를 붙이려면
네이버 단지상세에서 이 메타가 자동 확보 가능한지, 정확한 필드명이 무엇인지 검증한다.
"""

from __future__ import annotations

from myhouse.naver.client import NaverLandClient
from myhouse.naver.endpoints import build_complex_detail_url, complex_referer

TARGETS = ["947", "971"]  # 방배 삼호1차(재건축), 대치현대(일반아파트)
HINTS = (
    "household", "dong", "approve", "ratio", "batl", "btl", "vration", "vlrat", "far",
    "floor", "build", "complet", "year", "use", "construct", "permit", "cover", "total",
    "세대", "동", "준공", "용적", "건폐", "승인",
)


def dump(label: str, obj: dict) -> None:
    print(f"\n--- {label}: 힌트 매칭 필드 ---")
    for k in sorted(obj):
        v = obj[k]
        if isinstance(v, (str, int, float, bool)) and v != "" and any(h in k.lower() for h in HINTS):
            print(f"  {k} = {v!r}")


def main() -> None:
    with NaverLandClient(headless=True) as c:
        for cx in TARGETS:
            c._browser.ensure_token(cx)  # noqa: SLF001
            ref = complex_referer(cx)
            d = c._browser.fetch_json(build_complex_detail_url(cx), ref)  # noqa: SLF001
            detail = (d.get("complexDetail") if isinstance(d, dict) else None) or d
            print(f"\n========== 단지 {cx}: complexName={detail.get('complexName')!r} ==========")
            print("complexDetail 전체 스칼라 키:")
            scalars = sorted(k for k, v in detail.items() if isinstance(v, (str, int, float, bool)))
            print("  ", scalars)
            dump(f"{cx} complexDetail", detail)


if __name__ == "__main__":
    main()
