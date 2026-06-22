import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { permitKeys, getPermits } from '@/entities/permit/api/get-permits'
import { PERMIT_FILTER_DEFAULTS } from '@/entities/permit/model/types'
import type { PermitFilters } from '@/entities/permit/model/types'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const MONTHS_OPTIONS = [
  { value: '1', label: '1개월' },
  { value: '3', label: '3개월' },
  { value: '6', label: '6개월' },
  { value: '12', label: '12개월' },
]

const JOB_GBN_OPTIONS = [
  { value: '', label: '전체' },
  { value: '허가', label: '허가' },
  { value: '불허가', label: '불허가' },
  { value: '취하', label: '취하' },
]

const PERMIT_SORT_OPTIONS = [
  { value: 'date_desc', label: '최신순' },
  { value: 'date_asc', label: '오래된순' },
]

function parseFilters(sp: URLSearchParams): PermitFilters {
  return {
    gu: sp.get('gu') ?? PERMIT_FILTER_DEFAULTS.gu,
    complex_no: sp.get('complex_no') ?? PERMIT_FILTER_DEFAULTS.complex_no,
    months: sp.get('months') ?? PERMIT_FILTER_DEFAULTS.months,
    job_gbn: sp.get('job_gbn') ?? PERMIT_FILTER_DEFAULTS.job_gbn,
    sort: sp.get('sort') ?? PERMIT_FILTER_DEFAULTS.sort,
  }
}

export function PermitsPage() {
  const [sp, setSp] = useSearchParams()
  const filters = parseFilters(sp)

  function set(key: keyof PermitFilters, value: string) {
    const next = new URLSearchParams(sp)
    const def = PERMIT_FILTER_DEFAULTS[key]
    if (value === def || value === '') {
      next.delete(key)
    } else {
      next.set(key, value)
    }
    setSp(next)
  }

  function reset() {
    setSp(new URLSearchParams())
  }

  const query = useQuery({
    queryKey: permitKeys.list(filters),
    queryFn: () => getPermits(filters),
    placeholderData: keepPreviousData,
  })

  const data = query.data

  return (
    <div className="space-y-4">
      {/* 상단 고정 필터 바 */}
      <div className="sticky top-14 z-20 -mx-4 border-b bg-background/95 px-4 pt-3 pb-2 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        <div className="flex flex-wrap items-end gap-2">
          {/* 구 */}
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
          {/* 단지 */}
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
          {/* 기간 */}
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            기간
            <select
              value={filters.months}
              onChange={(e) => set('months', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              {MONTHS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          {/* 업종 */}
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            업종
            <select
              value={filters.job_gbn}
              onChange={(e) => set('job_gbn', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              {JOB_GBN_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          {/* 정렬 */}
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            정렬
            <select
              value={filters.sort}
              onChange={(e) => set('sort', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              {PERMIT_SORT_OPTIONS.map((o) => (
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
        <p className="rounded-lg border p-8 text-center text-muted-foreground">조건에 맞는 허가 내역이 없습니다.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="whitespace-nowrap">날짜</TableHead>
                <TableHead>단지</TableHead>
                <TableHead className="whitespace-nowrap">업종</TableHead>
                <TableHead className="whitespace-nowrap">용도</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.map((r) => (
                <TableRow key={r.permit_key}>
                  <TableCell className="whitespace-nowrap tabular-nums text-sm">
                    {r.permit_date?.replace(/-/g, '.') ?? '-'}
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
                  <TableCell className="whitespace-nowrap">
                    <Badge
                      variant={r.job_gbn === '허가' ? 'default' : r.job_gbn === '불허가' ? 'destructive' : 'secondary'}
                      className="h-5 px-1.5 text-[10px]"
                    >
                      {r.job_gbn ?? '-'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{r.use_purp ?? '-'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
