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
    <div className="grid gap-6 lg:grid-cols-[320px_1fr] lg:items-start">
      {/* 좌측 필터 — 스크롤 시 따라오도록 sticky. 패널이 뷰포트보다 길면 내부 스크롤. */}
      <div className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto">
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
          <div className="rounded-lg border p-4 text-sm text-muted-foreground">
            필터 로딩 중…
          </div>
        )}
      </div>

      {/* min-w-0: 1fr 트랙이 넓은 테이블 내용폭으로 부풀어 grid 가 가로 오버플로되는 것 방지.
          넘치면 테이블 내부(overflow-x-auto)에서 스크롤. */}
      <div className="space-y-3 min-w-0">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <span>
            총 <b className="text-foreground">{data?.total ?? 0}</b>건
          </span>
          {!!data?.new_count && <span>· 신규 {data.new_count}건</span>}
          {listingsQuery.isFetching && <span>· 불러오는 중…</span>}
        </div>

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
