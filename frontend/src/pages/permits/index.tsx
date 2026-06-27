import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { permitKeys, getPermits } from '@/entities/permit/api/get-permits'
import { PERMIT_FILTER_DEFAULTS } from '@/entities/permit/model/types'
import type { PermitFilters, PermitRow } from '@/entities/permit/model/types'
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

function jobVariant(job: string | null) {
  return job === '허가' ? 'default' : job === '불허가' ? 'destructive' : 'secondary'
}

// 모바일 카드 — 좁은 화면에선 가로 스크롤 대신 한 건씩 카드로.
function PermitCard({ row: r }: { row: PermitRow }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-1.5">
            <Link to={`/complex/${r.complex_no}`} className="font-medium hover:underline">
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
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {r.permit_date?.replace(/-/g, '.') ?? '-'}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-2 text-sm">
        <Badge variant={jobVariant(r.job_gbn)} className="h-5 px-1.5 text-[10px]">
          {r.job_gbn ?? '-'}
        </Badge>
        <span className="text-muted-foreground">{r.use_purp ?? '-'}</span>
      </div>
    </div>
  )
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
      </FilterBar>

      {/* 테이블(데스크탑) / 카드(모바일) */}
      {query.isError ? (
        <p className="rounded-lg border border-destructive/50 p-8 text-center text-sm text-destructive">
          불러오기 실패: {String(query.error)}
        </p>
      ) : !data ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">불러오는 중…</p>
      ) : data.rows.length === 0 ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">조건에 맞는 허가 내역이 없습니다.</p>
      ) : (
        <>
        {/* 모바일: 카드 */}
        <div className="space-y-2 md:hidden">
          {data.rows.map((r) => (
            <PermitCard key={r.permit_key} row={r} />
          ))}
        </div>
        {/* 데스크탑: 테이블 */}
        <div className="hidden overflow-x-auto rounded-lg border md:block">
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
        </>
      )}
    </div>
  )
}
