import type { ListingFilters } from '../model/types'

// 필터 기본값 — URL 에 없으면 이 값. status=active, sort=new 가 백엔드 기본과 일치.
export const DEFAULT_FILTERS: ListingFilters = {
  trade_type: '',
  status: 'active',
  q: '',
  price_min: null,
  price_max: null,
  area_min: null,
  area_max: null,
  floor_min: null,
  gu: '',
  dong: '',
  complex_no: '',
  households_min: null,
  households_max: null,
  year_min: null,
  year_max: null,
  starred_only: false,
  show_excluded: false,
  sort: 'new',
}

const NUM_KEYS = [
  'price_min', 'price_max', 'area_min', 'area_max', 'floor_min',
  'households_min', 'households_max', 'year_min', 'year_max',
] as const

const STR_KEYS = ['trade_type', 'status', 'q', 'gu', 'dong', 'complex_no', 'sort'] as const

// URLSearchParams → ListingFilters (없는 키는 기본값).
export function searchParamsToFilters(p: URLSearchParams): ListingFilters {
  const f: ListingFilters = { ...DEFAULT_FILTERS }
  for (const k of STR_KEYS) {
    const v = p.get(k)
    if (v != null && v !== '') f[k] = v
  }
  for (const k of NUM_KEYS) {
    const v = p.get(k)
    if (v != null && v !== '') {
      const n = Number(v)
      if (!Number.isNaN(n)) f[k] = n
    }
  }
  f.starred_only = ['on', 'true', '1'].includes(p.get('starred_only') ?? '')
  f.show_excluded = ['on', 'true', '1'].includes(p.get('show_excluded') ?? '')
  return f
}

// ListingFilters → URLSearchParams (기본값과 같은 항목은 생략해 URL 을 짧게 유지).
export function filtersToSearchParams(f: ListingFilters): URLSearchParams {
  const p = new URLSearchParams()
  for (const k of STR_KEYS) {
    if (f[k] && f[k] !== DEFAULT_FILTERS[k]) p.set(k, f[k])
  }
  for (const k of NUM_KEYS) {
    const v = f[k]
    if (v != null) p.set(k, String(v))
  }
  if (f.starred_only) p.set('starred_only', 'on')
  if (f.show_excluded) p.set('show_excluded', 'on')
  return p
}
