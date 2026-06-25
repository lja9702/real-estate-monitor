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
  remarks: string | null // 물건비고 원문
  flags: string[] // 비고서 추출한 위험 플래그(지분매각·위반건축물 등)
  outcome: string | null // sold/failed/withdrawn (null=진행중)
  outcome_label: string | null // "매각"·"유찰"·"취하" 등
  final_bid_manwon: number | null // 낙찰가(매각 시)
  outcome_date: string | null
  is_new: boolean
  starred: boolean
}

export interface AuctionDateEvent {
  date: string | null
  kind: string // 매각기일 / 매각결정기일 / 대금지급기한 등
  result: string // 매각 / 유찰 / 미납 / 변경 …(빈 문자열=예정)
  low_price_manwon: number | null
}

export interface AuctionDetail {
  auction_key: string
  complex_no: string
  complex_name: string
  case_no: string
  court_name: string | null
  court_url: string | null
  address: string
  building_name: string | null
  area_excl: number | null
  appraisal_manwon: number | null
  min_bid_manwon: number | null
  min_bid_ratio: number | null
  fail_count: number
  sale_date: string | null
  in_progress: boolean
  outcome: string | null
  outcome_label: string | null
  final_bid_manwon: number | null
  outcome_date: string | null
  next_sale_date: string | null
  remarks: string | null
  flags: string[]
  events: AuctionDateEvent[]
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
