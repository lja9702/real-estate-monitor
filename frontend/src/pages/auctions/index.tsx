import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { auctionKeys, getAuctions } from '@/entities/auction/api/get-auctions'
import { AUCTION_FILTER_DEFAULTS } from '@/entities/auction/model/types'
import type { AuctionFilters, AuctionRow } from '@/entities/auction/model/types'
import { AuctionDetailDialog } from '@/entities/auction/ui/auction-detail-dialog'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FilterBar } from '@/shared/ui/filter-bar'

const SORT_OPTIONS = [
  { value: 'date_asc', label: '매각임박순' },
  { value: 'date_desc', label: '매각늦은순' },
  { value: 'minbid_asc', label: '최저가낮은순' },
]

function eok(manwon: number | null): string {
  if (manwon == null) return '-'
  if (manwon >= 10000) return `${(manwon / 10000).toFixed(1).replace(/\.0$/, '')}억`
  return `${manwon.toLocaleString()}만`
}

function parseFilters(sp: URLSearchParams): AuctionFilters {
  return {
    gu: sp.get('gu') ?? AUCTION_FILTER_DEFAULTS.gu,
    complex_no: sp.get('complex_no') ?? AUCTION_FILTER_DEFAULTS.complex_no,
    sort: sp.get('sort') ?? AUCTION_FILTER_DEFAULTS.sort,
  }
}

// 모바일 카드 — 좁은 화면에선 가로 스크롤 대신 한 건씩 카드로. 탭하면 상세 다이얼로그.
function AuctionCard({ row: r, onOpen }: { row: AuctionRow; onOpen: () => void }) {
  return (
    <div onClick={onOpen} className="cursor-pointer rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-1.5">
            <Link
              to={`/complex/${r.complex_no}`}
              onClick={(e) => e.stopPropagation()}
              className="font-medium hover:underline"
            >
              {r.complex_name}
            </Link>
            {r.is_new && (
              <Badge variant="default" className="h-4 px-1 text-[10px]">신규</Badge>
            )}
          </div>
          {r.address_short && (
            <div className="text-xs text-muted-foreground">{r.address_short}</div>
          )}
        </div>
        <div className="shrink-0 text-right">
          <div className="text-xs tabular-nums text-muted-foreground">
            {r.sale_date?.replace(/-/g, '.') ?? '-'}
          </div>
          {r.outcome_label && (
            <Badge
              variant={r.outcome === 'sold' ? 'default' : 'secondary'}
              className="mt-0.5 h-4 px-1 text-[10px]"
            >
              {r.outcome === 'sold' && r.final_bid_manwon != null
                ? `매각 ${eok(r.final_bid_manwon)}`
                : r.outcome_label}
            </Badge>
          )}
        </div>
      </div>

      {r.flags.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1" title={r.remarks ?? undefined}>
          {r.flags.map((f) => (
            <Badge key={f} variant="destructive" className="h-4 px-1 text-[10px]">
              {f}
            </Badge>
          ))}
        </div>
      )}

      <div className="mt-2 flex items-baseline justify-between gap-2 text-sm">
        <span className="text-muted-foreground">감정 {eok(r.appraisal_manwon)}</span>
        <span className="font-semibold tabular-nums">
          최저 {eok(r.min_bid_manwon)}
          {r.min_bid_ratio != null && (
            <span
              className={`ml-1 text-xs font-normal ${r.min_bid_ratio < 100 ? 'text-destructive' : 'text-muted-foreground'}`}
            >
              {r.min_bid_ratio}%
            </span>
          )}
        </span>
      </div>

      <div className="mt-1 flex items-center justify-between gap-2 text-sm text-muted-foreground">
        <span>{r.fail_count > 0 ? `유찰 ${r.fail_count}회` : '신건'}</span>
        <span className="truncate">
          {r.court_url ? (
            <a
              href={r.court_url}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="hover:underline"
            >
              {r.case_no} ↗
            </a>
          ) : (
            r.case_no
          )}
          {r.court_name && ` · ${r.court_name}`}
        </span>
      </div>
    </div>
  )
}

export function AuctionsPage() {
  const [sp, setSp] = useSearchParams()
  const [detailKey, setDetailKey] = useState<string | null>(null)
  const filters = parseFilters(sp)

  function set(key: keyof AuctionFilters, value: string) {
    const next = new URLSearchParams(sp)
    const def = AUCTION_FILTER_DEFAULTS[key]
    if (value === def || value === '') next.delete(key)
    else next.set(key, value)
    setSp(next)
  }

  function reset() {
    setSp(new URLSearchParams())
  }

  const query = useQuery({
    queryKey: auctionKeys.list(filters),
    queryFn: () => getAuctions(filters),
    placeholderData: keepPreviousData,
  })

  const data = query.data

  return (
    <div className="space-y-4">
      {/* 상단 고정 필터 바 — 모바일에선 접힘 */}
      <FilterBar
        count={
          <>
            총 <b className="text-foreground">{data?.total ?? 0}</b>건
            {!!data?.new_count && <> · 신규 {data.new_count}건</>}
            {query.isFetching && <> · …</>}
          </>
        }
      >
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            구
            <select
              value={filters.gu}
              onChange={(e) => set('gu', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              <option value="">전체</option>
              {(data?.gu_list ?? []).map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            단지
            <select
              value={filters.complex_no}
              onChange={(e) => set('complex_no', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              <option value="">전체 단지</option>
              {(data?.complexes ?? []).map((c) => (
                <option key={c.complex_no} value={c.complex_no}>{c.name}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            정렬
            <select
              value={filters.sort}
              onChange={(e) => set('sort', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={reset}
            className="h-8 rounded border px-3 text-sm text-muted-foreground hover:bg-muted"
          >
            초기화
          </button>
        </div>
      </FilterBar>

      {/* 테이블(데스크탑) / 카드(모바일) */}
      {query.isError ? (
        <p className="rounded-lg border border-destructive/50 p-8 text-center text-sm text-destructive">
          불러오기 실패: {String(query.error)}
        </p>
      ) : !data ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">불러오는 중…</p>
      ) : data.rows.length === 0 ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">조건에 맞는 경매 물건이 없습니다.</p>
      ) : (
        <>
        {/* 모바일: 카드 */}
        <div className="space-y-2 md:hidden">
          {data.rows.map((r) => (
            <AuctionCard key={r.auction_key} row={r} onOpen={() => setDetailKey(r.auction_key)} />
          ))}
        </div>
        {/* 데스크탑: 테이블 */}
        <div className="hidden overflow-x-auto rounded-lg border md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="whitespace-nowrap">매각기일</TableHead>
                <TableHead>단지</TableHead>
                <TableHead className="whitespace-nowrap text-right">감정가</TableHead>
                <TableHead className="whitespace-nowrap text-right">최저가</TableHead>
                <TableHead className="whitespace-nowrap">유찰</TableHead>
                <TableHead className="whitespace-nowrap">사건 / 법원</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.map((r) => (
                <TableRow
                  key={r.auction_key}
                  onClick={() => setDetailKey(r.auction_key)}
                  className="cursor-pointer"
                >
                  <TableCell className="whitespace-nowrap tabular-nums text-sm">
                    {r.sale_date?.replace(/-/g, '.') ?? '-'}
                    {r.outcome_label && (
                      <Badge
                        variant={r.outcome === 'sold' ? 'default' : 'secondary'}
                        className="ml-1.5 h-4 px-1 text-[10px]"
                      >
                        {r.outcome === 'sold' && r.final_bid_manwon != null
                          ? `매각 ${eok(r.final_bid_manwon)}`
                          : r.outcome_label}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <Link
                      to={`/complex/${r.complex_no}`}
                      onClick={(e) => e.stopPropagation()}
                      className="font-medium hover:underline"
                    >
                      {r.complex_name}
                    </Link>
                    {r.is_new && (
                      <Badge variant="default" className="ml-1.5 h-4 px-1 text-[10px]">신규</Badge>
                    )}
                    {r.address_short && (
                      <div className="text-xs text-muted-foreground">{r.address_short}</div>
                    )}
                    {r.flags.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1" title={r.remarks ?? undefined}>
                        {r.flags.map((f) => (
                          <Badge key={f} variant="destructive" className="h-4 px-1 text-[10px]">
                            {f}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right tabular-nums text-sm">
                    {eok(r.appraisal_manwon)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right tabular-nums text-sm">
                    {eok(r.min_bid_manwon)}
                    {r.min_bid_ratio != null && (
                      <span
                        className={`ml-1 text-xs ${r.min_bid_ratio < 100 ? 'text-destructive' : 'text-muted-foreground'}`}
                      >
                        {r.min_bid_ratio}%
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm">
                    {r.fail_count > 0 ? `${r.fail_count}회` : '신건'}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm">
                    {r.court_url ? (
                      <a
                        href={r.court_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-muted-foreground hover:underline"
                      >
                        {r.case_no} ↗
                      </a>
                    ) : (
                      r.case_no
                    )}
                    {r.court_name && (
                      <div className="text-xs text-muted-foreground">{r.court_name}</div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        </>
      )}
      <AuctionDetailDialog auctionKey={detailKey} onClose={() => setDetailKey(null)} />
    </div>
  )
}
