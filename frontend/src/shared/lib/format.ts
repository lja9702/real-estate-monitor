// 만원 단위 정수 → 한국식 '억/만원' 표기. 백엔드 util.format_manwon 의 TS 포팅.
// 예) 158000 → "15억8,000", 90000 → "9억", 5000 → "5,000"
export function formatManwon(v: number | null | undefined): string {
  if (v == null) return '-'
  if (v < 0) return '-' + formatManwon(-v)
  const eok = Math.floor(v / 10000)
  const rem = v % 10000
  if (eok && rem) return `${eok}억${rem.toLocaleString('ko-KR')}`
  if (eok) return `${eok}억`
  return v.toLocaleString('ko-KR')
}

// 가격 범위 → "15억 ~ 16억" (동일하면 단일 값). null 은 '-'.
export function formatPriceRange(
  lo: number | null | undefined,
  hi: number | null | undefined,
): string {
  if (lo == null && hi == null) return '-'
  if (lo == null) return formatManwon(hi)
  if (hi == null) return formatManwon(lo)
  if (lo === hi) return formatManwon(lo)
  return `${formatManwon(lo)} ~ ${formatManwon(hi)}`
}

// 전용면적 ㎡ — 소수 1자리까지, 정수면 정수로.
export function formatArea(m2: number | null | undefined): string {
  if (m2 == null) return '-'
  return Number.isInteger(m2) ? `${m2}㎡` : `${m2.toFixed(1)}㎡`
}

// 'YYYYMMDD' → 연도 정수. 준공연도 표시용.
export function approveYear(ymd: string | null | undefined): number | null {
  if (!ymd || ymd.length < 4) return null
  const y = Number(ymd.slice(0, 4))
  return Number.isNaN(y) ? null : y
}
