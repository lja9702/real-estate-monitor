import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { flashKeys, getFlash } from '@/entities/flash/api/get-flash'
import { FLASH_FILTER_DEFAULTS } from '@/entities/flash/model/types'
import type { FlashFilters } from '@/entities/flash/model/types'
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
import { TRADE_TYPES } from '@/shared/config/constants'

const DAYS_OPTIONS = [
  { value: '7', label: '7일' },
  { value: '14', label: '14일' },
  { value: '30', label: '30일' },
  { value: '60', label: '60일' },
  { value: '90', label: '90일' },
]

const TRIGGER_OPTIONS = [
  { value: '', label: '전체' },
  { value: 'new', label: '신규' },
  { value: 'price_drop', label: '가격인하' },
]

const FLASH_SORT_OPTIONS = [
  { value: 'drop_pct_desc', label: '하락률 높은순' },
  { value: 'drop_amount_desc', label: '하락액 큰순' },
  { value: 'detected_desc', label: '최신순' },
  { value: 'price_asc', label: '가격 낮은순' },
]

function parseFilters(sp: URLSearchParams): FlashFilters {
  return {
    trade_type: sp.get('trade_type') ?? FLASH_FILTER_DEFAULTS.trade_type,
    days: sp.get('days') ?? FLASH_FILTER_DEFAULTS.days,
    gu: sp.get('gu') ?? FLASH_FILTER_DEFAULTS.gu,
    dong: sp.get('dong') ?? FLASH_FILTER_DEFAULTS.dong,
    complex_no: sp.get('complex_no') ?? FLASH_FILTER_DEFAULTS.complex_no,
    trigger: sp.get('trigger') ?? FLASH_FILTER_DEFAULTS.trigger,
    include_inactive: sp.get('include_inactive') === 'true',
    sort: sp.get('sort') ?? FLASH_FILTER_DEFAULTS.sort,
  }
}

export function FlashPage() {
  const [sp, setSp] = useSearchParams()
  const filters = parseFilters(sp)

  function set(key: keyof FlashFilters, value: string | boolean) {
    const next = new URLSearchParams(sp)
    const def = FLASH_FILTER_DEFAULTS[key]
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
    queryKey: flashKeys.list(filters),
    queryFn: () => getFlash(filters),
    placeholderData: keepPreviousData,
  })

  const data = query.data
  const guDongMap = data?.gu_dong_map ?? {}
  const dongList = filters.gu ? (guDongMap[filters.gu] ?? []) : []

  return (
    <div className="space-y-4">
      {/* 상단 고정 필터 바 */}
      <div className="sticky top-14 z-20 -mx-4 border-b bg-background/95 px-4 pt-3 pb-2 backdrop-blur supports-[backdrop-filter]:bg-background/75">
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
            발생기간
            <select
              value={filters.days}
              onChange={(e) => set('days', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              {DAYS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          {/* 트리거 */}
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            유형
            <select
              value={filters.trigger}
              onChange={(e) => set('trigger', e.target.value)}
              className="h-8 rounded border bg-background px-2 text-sm"
            >
              {TRIGGER_OPTIONS.map((o) => (
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
              {FLASH_SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          {/* 빠진 급매 포함 */}
          <label className="flex h-8 items-center gap-1.5 text-sm">
            <input
              type="checkbox"
              checked={filters.include_inactive}
              onChange={(e) => set('include_inactive', e.target.checked)}
            />
            빠진 매물 포함
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
        <p className="rounded-lg border p-8 text-center text-muted-foreground">
          조건에 맞는 급매가 없습니다. (매물 수집이 누적되면 채워집니다)
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="whitespace-nowrap">발생일</TableHead>
                <TableHead>단지</TableHead>
                <TableHead className="whitespace-nowrap">거래</TableHead>
                <TableHead className="whitespace-nowrap">전용</TableHead>
                <TableHead className="whitespace-nowrap">층</TableHead>
                <TableHead className="text-right whitespace-nowrap">급매가</TableHead>
                <TableHead className="text-right whitespace-nowrap">직전 하한</TableHead>
                <TableHead className="text-right whitespace-nowrap">하락</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.map((r) => {
                const gone = r.status !== 'ACTIVE'
                return (
                  <TableRow key={r.article_no} className={gone ? 'opacity-50' : ''}>
                    <TableCell className="whitespace-nowrap tabular-nums text-sm">
                      {r.detected_at.slice(0, 10).replace(/-/g, '.')}
                    </TableCell>
                    <TableCell>
                      <span className="font-medium">
                        <Link to={`/complex/${r.complex_no}`} className="hover:underline">
                          {r.complex_name}
                        </Link>
                        {r.article_url && (
                          <a
                            href={r.article_url}
                            target="_blank"
                            rel="noreferrer"
                            className="ml-1.5 text-xs font-normal text-muted-foreground hover:text-foreground hover:underline"
                          >
                            네이버↗
                          </a>
                        )}
                      </span>
                      {r.dup_count > 1 && (
                        <Badge variant="outline" className="ml-1.5 h-4 px-1 text-[10px]">
                          외 {r.dup_count - 1}건
                        </Badge>
                      )}
                      {r.is_new && (
                        <Badge variant="default" className="ml-1.5 h-4 px-1 text-[10px]">신규감지</Badge>
                      )}
                      <Badge
                        variant={r.trigger === 'price_drop' ? 'secondary' : 'outline'}
                        className="ml-1.5 h-4 px-1 text-[10px]"
                      >
                        {r.trigger_ko}
                      </Badge>
                      {gone && (
                        <Badge variant="outline" className="ml-1.5 h-4 px-1 text-[10px]">빠짐</Badge>
                      )}
                      {r.address_short && (
                        <div className="text-xs text-muted-foreground">{r.address_short}</div>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{r.trade_ko}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatArea(r.area_excl)}</TableCell>
                    <TableCell className="tabular-nums">
                      {r.floor_info ? r.floor_info.split('/')[0] : '-'}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap font-medium tabular-nums">
                      {formatManwon(r.price_deal)}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums text-muted-foreground">
                      {formatManwon(r.prior_floor)}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums font-semibold text-destructive">
                      ▼{formatManwon(r.drop_amount)}
                      <span className="ml-1 text-xs">(-{r.drop_pct}%)</span>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
