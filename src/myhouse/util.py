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
    """사용승인일 'YYYYMMDD' → '1975.11 준공'. 월이 없거나 '00' 이면 '1975년 준공'. 실패 시 None."""
    if not use_approve_ymd or len(use_approve_ymd) < 4 or not use_approve_ymd[:4].isdigit():
        return None
    y = use_approve_ymd[:4]
    m = use_approve_ymd[4:6] if len(use_approve_ymd) >= 6 else ""
    if m.isdigit() and m != "00":
        return f"{y}.{m} 준공"
    return f"{y}년 준공"


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
