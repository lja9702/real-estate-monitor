import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { dealKeys, getDeals } from '@/entities/deal/api/get-deals'
import { DEAL_FILTER_DEFAULTS } from '@/entities/deal/model/types'
import type { DealFilters, DealRow } from '@/entities/deal/model/types'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatArea, formatManwon } from '@/shared/lib/format'
import { FilterBar } from '@/shared/ui/filter-bar'
import { TRADE_TYPES } from '@/shared/config/constants'

const MONTHS_OPTIONS = [
  { value: '1', label: '1개월' },
  { value: '3', label: '3개월' },
  { value: '6', label: '6개월' },
  { value: '12', label: '12개월' },
  { value: '24', label: '24개월' },
  { value: '36', label: '36개월' },
]

const DEAL_SORT_OPTIONS = [
  { value: 'date_desc', label: '최신순' },
  { value: 'price_desc', label: '가격 높은순' },
  { value: 'price_asc', label: '가격 낮은순' },
]

function parseFilters(sp: URLSearchParams): DealFilters {
  return {
    trade_type: sp.get('trade_type') ?? DEAL_FILTER_DEFAULTS.trade_type,
    months: sp.get('months') ?? DEAL_FILTER_DEFAULTS.months,
    gu: sp.get('gu') ?? DEAL_FILTER_DEFAULTS.gu,
    dong: sp.get('dong') ?? DEAL_FILTER_DEFAULTS.dong,
    complex_no: sp.get('complex_no') ?? DEAL_FILTER_DEFAULTS.complex_no,
    include_cancelled: sp.get('include_cancelled') === 'true',
    sort: sp.get('sort') ?? DEAL_FILTER_DEFAULTS.sort,
  }
}

// 모바일 카드 — 좁은 화면에선 가로 스크롤 대신 한 건씩 카드로.
function DealCard({ row: r }: { row: DealRow }) {
  return (
    <div className={`rounded-lg border p-3 ${r.cancelled ? 'opacity-50' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-1.5">
            <Link to={`/complex/${r.complex_no}`} className="font-medium hover:underline">
              {r.complex_name}
            </Link>
            {r.is_new && (
              <Badge variant="default" className="h-4 px-1 text-[10px]">신규</Badge>
            )}
            {r.cancelled && (
              <Badge variant="destructive" className="h-4 px-1 text-[10px]">취소</Badge>
            )}
          </div>
          {r.address_short && (
            <div className="text-xs text-muted-foreground">{r.address_short}</div>
          )}
        </div>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {r.deal_date.replace(/-/g, '.')}
        </span>
      </div>
      <div className="mt-2 flex items-baseline justify-between gap-2">
        <span className="text-sm text-muted-foreground">
          {r.trade_ko} · 전용 {formatArea(r.area_excl)}
          {r.floor != null && ` · ${r.floor}층`}
        </span>
        <span className="font-semibold tabular-nums">
          {formatManwon(r.price_deal)}
          {r.price_rent != null && (
            <span className="ml-1 text-xs font-normal text-muted-foreground">
              /{formatManwon(r.price_rent)}
            </span>
          )}
        </span>
      </div>
    </div>
  )
}

export function DealsPage() {
  const [sp, setSp] = useSearchParams()
  const filters = parseFilters(sp)

  function set(key: keyof DealFilters, value: string | boolean) {
    const next = new URLSearchParams(sp)
    const def = DEAL_FILTER_DEFAULTS[key]
    if (value === def || value === '') {
      next.delete(key)
    } else {
      next.set(key, String(value))
    }
    if (key === 'gu') next.delete('dong')
    setSp(next)
  }

  function reset() {
    setSp(new URLSearchParams())
  }

  const query = useQuery({
    queryKey: dealKeys.list(filters),
    queryFn: () => getDeals(filters),
    placeholderData: keepPreviousData,
  })

  const data = query.data
  const guDongMap = data?.gu_dong_map ?? {}
  const dongList = filters.gu ? (guDongMap[filters.gu] ?? []) : []

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
          {/* 거래유형 */}
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            거래유형
            <select
              value={filters.trade_type}
              onChange={(e) => set('trade_type', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              {TRADE_TYPES.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
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
          {/* 구 */}
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            구
            <select
              value={filters.gu}
              onChange={(e) => set('gu', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              <option value="">전체</option>
              {Object.keys(guDongMap).sort().map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </label>
          {/* 동 */}
          {dongList.length > 0 && (
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              동
              <select
                value={filters.dong}
                onChange={(e) => set('dong', e.target.value)}
                className="h-8 rounded border bg-background px-2 text-sm"
              >
                <option value="">전체</option>
                {dongList.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </label>
          )}
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
          {/* 정렬 */}
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            정렬
            <select
              value={filters.sort}
              onChange={(e) => set('sort', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              {DEAL_SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          {/* 취소 포함 */}
          <label className="flex h-8 items-center gap-1.5 text-sm">
            <input
              type="checkbox"
              checked={filters.include_cancelled}
              onChange={(e) => set('include_cancelled', e.target.checked)}
            />
            취소 포함
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
        <p className="rounded-lg border p-8 text-center text-muted-foreground">조건에 맞는 실거래가 없습니다.</p>
      ) : (
        <>
        {/* 모바일: 카드 */}
        <div className="space-y-2 md:hidden">
          {data.rows.map((r) => (
            <DealCard key={r.deal_key} row={r} />
          ))}
        </div>
        {/* 데스크탑: 테이블 */}
        <div className="hidden overflow-x-auto rounded-lg border md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="whitespace-nowrap">날짜</TableHead>
                <TableHead>단지</TableHead>
                <TableHead className="whitespace-nowrap">거래</TableHead>
                <TableHead className="whitespace-nowrap">전용</TableHead>
                <TableHead className="whitespace-nowrap">층</TableHead>
                <TableHead className="text-right whitespace-nowrap">실거래가</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.map((r) => (
                <TableRow key={r.deal_key} className={r.cancelled ? 'opacity-50' : ''}>
                  <TableCell className="whitespace-nowrap tabular-nums text-sm">
                    {r.deal_date.replace(/-/g, '.')}
                  </TableCell>
                  <TableCell>
                    <Link to={`/complex/${r.complex_no}`} className="font-medium hover:underline">
                      {r.complex_name}
                    </Link>
                    {r.is_new && (
                      <Badge variant="default" className="ml-1.5 h-4 px-1 text-[10px]">신규</Badge>
                    )}
                    {r.cancelled && (
                      <Badge variant="destructive" className="ml-1.5 h-4 px-1 text-[10px]">취소</Badge>
                    )}
                    {r.address_short && (
                      <div className="text-xs text-muted-foreground">{r.address_short}</div>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{r.trade_ko}</TableCell>
                  <TableCell className="whitespace-nowrap">{formatArea(r.area_excl)}</TableCell>
                  <TableCell className="tabular-nums">{r.floor ?? '-'}</TableCell>
                  <TableCell className="text-right whitespace-nowrap tabular-nums">
                    {formatManwon(r.price_deal)}
                    {r.price_rent != null && (
                      <span className="ml-1 text-xs text-muted-foreground">
                        /{formatManwon(r.price_rent)}
                      </span>
                    )}
                  </TableCell>
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
