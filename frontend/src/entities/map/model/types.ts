export interface MapComplexRow {
  complex_no: string
  name: string
  lat: number
  lon: number
  active_count: number
  new_count: number
  min_price: number | null
  max_price: number | null
  trade_types: string[]
  meta_line: string | null
}

export interface MapConfig {
  naver_map_client_id: string | null
}
