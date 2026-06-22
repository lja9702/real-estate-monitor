import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useListingFilters } from '@/features/filter-listings/model/use-listing-filters'
import {
  filterDomainKeys,
  getFilterDomains,
  getListings,
  listingKeys,
} from '@/entities/listing/api/get-listings'
import { ListingFilterPanel } from '@/widgets/filter-panel/listing-filter-panel'
import { ListingTable } from '@/widgets/listing-table/listing-table'

export function ListingsPage() {
  const { filters, setFilters, reset } = useListingFilters()

  // 슬라이더 도메인 — 거의 안 변하므로 무한 staleTime.
  const domainsQuery = useQuery({
    queryKey: filterDomainKeys.all,
    queryFn: getFilterDomains,
    staleTime: Infinity,
  })

  // 매물 목록 — 필터별 캐시. 새 필터 로딩 중엔 이전 결과를 유지(깜빡임 방지).
  const listingsQuery = useQuery({
    queryKey: listingKeys.list(filters),
    queryFn: () => getListings(filters),
    placeholderData: keepPreviousData,
  })

  const data = listingsQuery.data

  return (
    <div className="space-y-4">
      {/* 상단 고정 필터 바 — 헤더(h-14) 바로 아래에 sticky 고정. -mx-4 로 컨테이너
          패딩까지 덮어 바처럼 보이게 하고, 반투명 배경으로 아래 내용이 비쳐 보이게. */}
      <div className="sticky top-14 z-20 -mx-4 border-b bg-background/95 px-4 pt-3 pb-2 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        {domainsQuery.data ? (
          <ListingFilterPanel
            domains={domainsQuery.data}
            filters={filters}
            setFilters={setFilters}
            reset={reset}
            complexes={data?.complexes ?? []}
            guDongMap={data?.gu_dong_map ?? {}}
          />
        ) : (
          <div className="text-sm text-muted-foreground">필터 로딩 중…</div>
        )}
        <div className="mt-2 flex items-center gap-3 border-t pt-2 text-sm text-muted-foreground">
          <span>
            총 <b className="text-foreground">{data?.total ?? 0}</b>건
          </span>
          {!!data?.new_count && <span>· 신규 {data.new_count}건</span>}
          {listingsQuery.isFetching && <span>· 불러오는 중…</span>}
        </div>
      </div>

      {/* 전체폭 테이블 */}
      <div className="min-w-0">
        {listingsQuery.isError ? (
          <p className="rounded-lg border border-destructive/50 p-8 text-center text-sm text-destructive">
            불러오기 실패: {String(listingsQuery.error)}
          </p>
        ) : data && data.rows.length === 0 ? (
          <p className="rounded-lg border p-8 text-center text-muted-foreground">
            조건에 맞는 매물이 없습니다.
          </p>
        ) : data ? (
          <ListingTable rows={data.rows} />
        ) : (
          <p className="rounded-lg border p-8 text-center text-muted-foreground">
            불러오는 중…
          </p>
        )}
      </div>
    </div>
  )
}
