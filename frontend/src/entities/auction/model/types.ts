import type { ComplexOption } from '@/entities/listing/model/types'

export interface AuctionRow {
  auction_key: string
  complex_no: string
  complex_name: string
  address_short: string | null
  address: string
  case_no: string
  court_name: string | null
  appraisal_manwon: number | null
  min_bid_manwon: number | null
  min_bid_ratio: number | null
  fail_count: number
  sale_date: string | null
  status_code: string | null
  in_progress: boolean
  court_url: string | null
  is_new: boolean
  starred: boolean
}

export interface AuctionFilters {
  gu: string
  complex_no: string
  sort: string
}

export const AUCTION_FILTER_DEFAULTS: AuctionFilters = {
  gu: '',
  complex_no: '',
  sort: 'date_asc',
}

export interface AuctionsResponse {
  rows: AuctionRow[]
  total: number
  new_count: number
  complexes: ComplexOption[]
  gu_list: string[]
}
