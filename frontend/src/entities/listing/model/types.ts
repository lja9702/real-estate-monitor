// 백엔드 AreaGroupRow(queries.py) 직렬화 결과와 1:1 대응.
export interface ListingRow {
  rep_cluster_key: string
  complex_no: string
  complex_name: string
  address_short: string | null
  meta_line: string | null
  trade_type: string // "SALE" | "JEONSE" | "WOLSE"
  trade_ko: string
  area_excl: number | null
  price_min: number | null
  price_max: number | null
  rent_min: number | null
  rent_max: number | null
  is_new: boolean
  rep_article_url: string | null
  starred: boolean
  excluded: boolean
  memo: string | null
  deal_price_min: number | null
  deal_price_max: number | null
  deal_date: string | null
  deal_is_recent: boolean
}

export interface ComplexOption {
  complex_no: string
  name: string
}

// GET /api/listings 응답.
export interface ListingsResponse {
  rows: ListingRow[]
  total: number
  new_count: number
  complexes: ComplexOption[]
  gu_dong_map: Record<string, string[]>
}

// GET /api/filter-domains 응답 — 슬라이더 min/max 도메인.
export interface FilterDomains {
  price_min: number
  price_max: number
  area_min: number
  area_max: number
  households_min: number
  households_max: number
  year_min: number
  year_max: number
  floor_max: number
}

// 매물 필터 — 백엔드 get_filters 쿼리파라미터와 대응. URL ↔ 상태 동기화의 단일 출처.
export interface ListingFilters {
  trade_type: string
  status: string
  q: string
  price_min: number | null
  price_max: number | null
  area_min: number | null
  area_max: number | null
  floor_min: number | null
  gu: string
  dong: string
  complex_no: string
  households_min: number | null
  households_max: number | null
  year_min: number | null
  year_max: number | null
  starred_only: boolean
  show_excluded: boolean
  sort: string
}
