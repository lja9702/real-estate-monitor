export interface RunRow {
  id: number
  started_at: string
  finished_at: string | null
  trigger: string
  kind: string
  status: string // 'RUNNING' | 'SUCCESS' | 'PARTIAL' | 'FAILED'
  targets_count: number
  articles_fetched: number
  new_count: number
  removed_count: number
  price_changed_count: number
  http_errors: number
  error: string | null
}

export interface RunsResponse {
  runs: RunRow[]
}
