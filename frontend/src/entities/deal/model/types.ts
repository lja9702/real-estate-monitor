import type { DealRow } from '@/entities/complex/model/types'
import type { ComplexOption } from '@/entities/listing/model/types'

export type { DealRow }

export interface DealFilters {
  trade_type: string
  months: string
  gu: string
  dong: string
  complex_no: string
  include_cancelled: boolean
  sort: string
}

export const DEAL_FILTER_DEFAULTS: DealFilters = {
  trade_type: '',
  months: '12',
  gu: '',
  dong: '',
  complex_no: '',
  include_cancelled: false,
  sort: 'date_desc',
}

export interface DealsResponse {
  rows: DealRow[]
  total: number
  new_count: number
  complexes: ComplexOption[]
  gu_dong_map: Record<string, string[]>
}
