import type { ComplexOption } from '@/entities/listing/model/types'

// 백엔드 FlashRow(queries.py) 직렬화 결과와 1:1 대응.
export interface FlashRow {
  article_no: string
  complex_no: string
  complex_name: string
  address_short: string | null
  meta_line: string | null
  trade_type: string
  trade_ko: string
  area_excl: number | null
  floor_info: string | null
  price_deal: number // 급매 발생 당시 가격(만원)
  prior_floor: number // 직전 같은 평수 하한가(만원)
  drop_amount: number
  drop_pct: number
  trigger: string // "new" | "price_drop"
  trigger_ko: string // "신규" | "인하"
  detected_at: string // ISO datetime
  status: string // ACTIVE / PENDING_REMOVAL / REMOVED / GONE
  article_url: string | null
  is_new: boolean
  dup_count: number // 같은 단지·평형·거래·가격의 동일매물 수(대표 1건만 표시)
  total_households: number | null
  use_approve_ymd: string | null
}

// 급매 필터 — 백엔드 get_flash_filters 쿼리파라미터와 대응.
export interface FlashFilters {
  trade_type: string
  days: string
  gu: string
  dong: string
  complex_no: string
  trigger: string
  include_inactive: boolean
  sort: string
}

export const FLASH_FILTER_DEFAULTS: FlashFilters = {
  trade_type: '',
  days: '30',
  gu: '',
  dong: '',
  complex_no: '',
  trigger: '',
  include_inactive: false,
  sort: 'drop_pct_desc',
}

// GET /api/flash 응답.
export interface FlashResponse {
  rows: FlashRow[]
  total: number
  new_count: number
  complexes: ComplexOption[]
  gu_dong_map: Record<string, string[]>
}
