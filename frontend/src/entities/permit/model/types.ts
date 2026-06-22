import type { ComplexOption } from '@/entities/listing/model/types'

export interface PermitRow {
  permit_key: string
  complex_no: string
  complex_name: string
  address_short: string | null
  meta_line: string | null
  address: string
  permit_date: string | null
  job_gbn: string | null
  use_purp: string | null
  is_new: boolean
  starred: boolean
}

export interface PermitFilters {
  gu: string
  complex_no: string
  months: string
  job_gbn: string
  sort: string
}

export const PERMIT_FILTER_DEFAULTS: PermitFilters = {
  gu: '',
  complex_no: '',
  months: '3',
  job_gbn: '',
  sort: 'date_desc',
}

export interface PermitsResponse {
  rows: PermitRow[]
  total: number
  new_count: number
  complexes: ComplexOption[]
  gu_list: string[]
}
