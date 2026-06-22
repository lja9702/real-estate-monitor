"""공용 포맷·파싱 헬퍼 (외부 의존성 없음)."""

from __future__ import annotations


def format_manwon(value: int | None) -> str:
    """만원 단위 정수를 한국식 억/만 표기로. 예: 158000 → '15억8,000', 90000 → '9억', 5000 → '5,000'."""
    if value is None:
        return "-"
    if value < 0:
        return "-" + format_manwon(-value)
    eok, rem = divmod(value, 10000)
    if eok and rem:
        return f"{eok}억{rem:,}"
    if eok:
        return f"{eok}억"
    return f"{value:,}"


def format_price(
    trade_type_ko: str,
    price_deal: int | None,
    price_rent: int | None,
) -> str:
    """거래유형에 맞춘 가격 문자열. 월세는 '보증금/월세' 형태."""
    if price_rent:
        return f"{format_manwon(price_deal)}/{format_manwon(price_rent)}"
    return format_manwon(price_deal)


def parse_float(value: object) -> float | None:
    """'59.82' / 59.82 / '' / None → float | None (실패 시 None)."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_floor(flr_info: str | None) -> tuple[str | None, int | None]:
    """네이버 flrInfo('12/15', '고/15', '저/3') → (원문, 숫자층 or None).

    현재층이 숫자면 floor_num 으로 파싱, '고/중/저' 면 None.
    """
    if not flr_info:
        return None, None
    raw = str(flr_info).strip()
    cur = raw.split("/", 1)[0].strip()
    try:
        return raw, int(cur)
    except ValueError:
        return raw, None


# 저/중/고 → 총층을 3등분한 0-based 구간 인덱스(하위·중간·상위 1/3)
_FLOOR_BAND_IDX = {"저": 0, "중": 1, "고": 2}


def estimate_floor_from_band(floor_info: str | None) -> int | None:
    """'저/중/고' 매물의 추정 층 — 총층을 3등분한 해당 구간의 중앙층.

    네이버는 일부 매물의 현재층을 숫자 대신 '저/중/고' 로만 준다(floor_num=None). 이때
    floor_info 의 총층('고/15' 의 15)을 3등분해 그 구간의 중앙을 대표 층으로 추정한다
    (저=하위 1/3·중=중간 1/3·고=상위 1/3). '최소 층' 필터에서 밴드 매물을 노출시키는 용도다.
    숫자층('12/15')이거나 밴드/총층을 못 읽으면 None(추정 불가).
    """
    if not floor_info:
        return None
    band, _, total_s = str(floor_info).partition("/")
    idx = _FLOOR_BAND_IDX.get(band.strip())
    if idx is None:
        return None
    try:
        total = int(total_s.strip())
    except ValueError:
        return None
    if total < 1:
        return None
    lo = total * idx // 3 + 1       # 구간 하한층 (1-based)
    hi = total * (idx + 1) // 3     # 구간 상한층
    return max(1, min(total, (lo + hi) // 2))


def parse_confirm_date(value: str | None) -> str | None:
    """확인일자 'YY.MM.DD.' / 'YYYY.MM.DD' / 'YYYYMMDD' → ISO date 'YYYY-MM-DD' (실패 시 None)."""
    if not value:
        return None
    raw = str(value).strip()
    if raw.isdigit() and len(raw) == 8:  # new.land 'YYYYMMDD'
        y, m, d = int(raw[:4]), int(raw[4:6]), int(raw[6:8])
        try:
            return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            return None
    parts = [p for p in raw.replace("-", ".").split(".") if p.strip()]
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
    except ValueError:
        return None
    if y < 100:
        y += 2000
    try:
        return f"{y:04d}-{m:02d}-{d:02d}"
    except ValueError:
        return None


def format_use_approve(use_approve_ymd: str | None) -> str | None:
    """사용승인일/입주예정일 → '1975.11 준공' / '2025.12 입주예정'. 실패 시 None.

    8자리(YYYYMMDD)는 준공(사용승인 완료), 6자리(YYYYMM)는 신규 분양권/입주권 단지의
    입주예정으로 본다(네이버가 준공 전 단지엔 사용승인일 대신 입주예정월만 6자리로 주기
    때문). 월이 없거나 '00' 이면 'YYYY년 …'.
    """
    if not use_approve_ymd or len(use_approve_ymd) < 4 or not use_approve_ymd[:4].isdigit():
        return None
    label = "입주예정" if len(use_approve_ymd) == 6 else "준공"
    y = use_approve_ymd[:4]
    m = use_approve_ymd[4:6] if len(use_approve_ymd) >= 6 else ""
    if m.isdigit() and m != "00":
        return f"{y}.{m} {label}"
    return f"{y}년 {label}"


def format_complex_meta(
    *,
    households: int | None = None,
    dong_count: int | None = None,
    use_approve_ymd: str | None = None,
    floor_area_ratio: int | None = None,
    building_coverage_ratio: int | None = None,
) -> str | None:
    """단지 메타를 한 줄 요약으로. 값이 있는 항목만 ' · ' 로 잇는다(전부 없으면 None).

    예: '419세대(3개동) · 1975.11 준공 · 용적률 238% · 건폐율 23%'.
    """
    bits: list[str] = []
    if households:
        h = f"{households:,}세대"
        if dong_count:
            h += f"({dong_count}개동)"
        bits.append(h)
    elif dong_count:
        bits.append(f"{dong_count}개동")
    approve = format_use_approve(use_approve_ymd)
    if approve:
        bits.append(approve)
    if floor_area_ratio:
        bits.append(f"용적률 {floor_area_ratio}%")
    if building_coverage_ratio:
        bits.append(f"건폐율 {building_coverage_ratio}%")
    return " · ".join(bits) if bits else None


def area_match_key(area: float | None) -> int:
    """전용면적 → 평형 매칭 키(정수). 매물·실거래·급매를 잇는 단일 기준.

    네이버 매물은 전용면적을 '버림(floor)'으로 정수화해 저장하고(84.97㎡→84), 국토부 실거래는
    정밀 소수(84.97)로 들어온다. 양쪽 모두 버림 정수로 키를 만들어야 같은 평형으로 매칭된다
    (round 를 쓰면 X.9x 평형이 +1 되어 어긋남). 면적이 없거나 0 이면 -1(매칭 불가).
    """
    return int(area) if area else -1
