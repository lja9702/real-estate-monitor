import { apiGet } from '@/shared/api/client'
import type { FilterDomains, ListingFilters, ListingsResponse } from '../model/types'
import { filtersToSearchParams } from '../lib/filters'

// TanStack Query 키 — 직렬화된 쿼리스트링을 키에 넣어 필터별 캐시를 분리한다.
export const listingKeys = {
  all: ['listings'] as const,
  list: (f: ListingFilters) =>
    ['listings', filtersToSearchParams(f).toString()] as const,
}

export const filterDomainKeys = {
  all: ['filter-domains'] as const,
}

export async function getListings(f: ListingFilters): Promise<ListingsResponse> {
  const qs = filtersToSearchParams(f).toString()
  return apiGet<ListingsResponse>(`/api/listings${qs ? `?${qs}` : ''}`)
}

export async function getFilterDomains(): Promise<FilterDomains> {
  return apiGet<FilterDomains>('/api/filter-domains')
}
