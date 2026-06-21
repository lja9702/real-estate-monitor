import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { ListingFilters } from '@/entities/listing/model/types'
import {
  filtersToSearchParams,
  searchParamsToFilters,
} from '@/entities/listing/lib/filters'

// 필터 상태를 URL 쿼리스트링에 동기화하는 단일 출처 훅.
// URL 이 곧 상태라 새로고침·공유·뒤로가기가 그대로 동작한다.
export function useListingFilters() {
  const [searchParams, setSearchParams] = useSearchParams()

  const filters = useMemo(
    () => searchParamsToFilters(searchParams),
    [searchParams],
  )

  // 부분 패치를 현재 필터에 병합해 URL 에 기록. searchParams 에서 다시 파싱해
  // 항상 최신 값을 기준으로 병합한다(stale closure 방지).
  const setFilters = useCallback(
    (patch: Partial<ListingFilters>) => {
      const next = { ...searchParamsToFilters(searchParams), ...patch }
      setSearchParams(filtersToSearchParams(next))
    },
    [searchParams, setSearchParams],
  )

  const reset = useCallback(
    () => setSearchParams(new URLSearchParams()),
    [setSearchParams],
  )

  return { filters, setFilters, reset }
}
