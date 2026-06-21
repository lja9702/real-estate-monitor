// GET /api/complex/{no} 응답 타입 — 백엔드 ComplexStat/ClusterRow/DealRow 와 1:1 대응.

export interface ComplexStat {
  complex_no: string
  name: string
  active_count: number
  by_trade: Record<string, number>
  price_min: number | null
  price_max: number | null
  new_30d: number
  starred: boolean
  meta_line: string | null
}

export interface ComplexRow {
  cluster_key: string
  complex_no: string
  complex_name: string
  trade_type: string
  trade_ko: string
  area_excl: number | null
  floor_info: string | null
  floor_num: number | null
  direction: string | null
  dong: string | null
  price_min: number | null
  price_max: number | null
  rent_min: number | null
  rent_max: number | null
  realtor_count: number
  status: string
  confirm_date: string | null
  feature_desc: string | null
  article_url: string | null
  address_short: string | null
  meta_line: string | null
  total_households: number | null
  use_approve_ymd: string | null
  is_new: boolean
  starred: boolean
  excluded: boolean
  memo: string | null
}

export interface DealRow {
  deal_key: string
  complex_no: string
  complex_name: string
  trade_type: string
  trade_ko: string
  deal_date: string // 'YYYY-MM-DD'
  price_deal: number
  price_rent: number | null
  floor: number | null
  pyeong_name: string | null
  area_excl: number | null
  cancelled: boolean
  address_short: string | null
  meta_line: string | null
  total_households: number | null
  use_approve_ymd: string | null
  is_new: boolean
}

export interface ComplexDetailResponse {
  stat: ComplexStat
  rows: ComplexRow[]
  deals: DealRow[]
}
