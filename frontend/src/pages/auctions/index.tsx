import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { auctionKeys, getAuctions } from '@/entities/auction/api/get-auctions'
import { AUCTION_FILTER_DEFAULTS } from '@/entities/auction/model/types'
import type { AuctionFilters } from '@/entities/auction/model/types'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

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

export function AuctionsPage() {
  const [sp, setSp] = useSearchParams()
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
      {/* 상단 고정 필터 바 */}
      <div className="sticky top-14 z-20 -mx-4 border-b bg-background/95 px-4 pt-3 pb-2 backdrop-blur supports-[backdrop-filter]:bg-background/75">
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
        <div className="mt-2 flex items-center gap-3 border-t pt-2 text-sm text-muted-foreground">
          <Link to="/" className="hover:underline">← 매물</Link>
          <span>총 <b className="text-foreground">{data?.total ?? 0}</b>건</span>
          {!!data?.new_count && <span>· 신규 {data.new_count}건</span>}
          {query.isFetching && <span>· 불러오는 중…</span>}
        </div>
      </div>

      {/* 테이블 */}
      {query.isError ? (
        <p className="rounded-lg border border-destructive/50 p-8 text-center text-sm text-destructive">
          불러오기 실패: {String(query.error)}
        </p>
      ) : !data ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">불러오는 중…</p>
      ) : data.rows.length === 0 ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">조건에 맞는 경매 물건이 없습니다.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
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
                <TableRow key={r.auction_key}>
                  <TableCell className="whitespace-nowrap tabular-nums text-sm">
                    {r.sale_date?.replace(/-/g, '.') ?? '-'}
                  </TableCell>
                  <TableCell>
                    <Link to={`/complex/${r.complex_no}`} className="font-medium hover:underline">
                      {r.complex_name}
                    </Link>
                    {r.is_new && (
                      <Badge variant="default" className="ml-1.5 h-4 px-1 text-[10px]">신규</Badge>
                    )}
                    {r.address_short && (
                      <div className="text-xs text-muted-foreground">{r.address_short}</div>
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
      )}
    </div>
  )
}
