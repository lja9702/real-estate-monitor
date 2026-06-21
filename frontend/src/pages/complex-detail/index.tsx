import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { complexKeys, getComplex } from '@/entities/complex/api/get-complex'
import type { ComplexRow, DealRow } from '@/entities/complex/model/types'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { StarButton } from '@/features/star-complex/ui/star-button'
import { MemoInput } from '@/features/edit-memo/ui/memo-input'
import { formatArea, formatAreaWithPyeong, formatManwon, formatPriceRange } from '@/shared/lib/format'

function RowStatusBadge({ row }: { row: ComplexRow }) {
  if (row.is_new)
    return (
      <Badge variant="default" className="h-5 px-1.5 text-[10px]">
        신규
      </Badge>
    )
  if (row.status === 'PENDING_REMOVAL')
    return (
      <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
        만료예정
      </Badge>
    )
  if (row.status === 'REMOVED')
    return (
      <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
        삭제됨
      </Badge>
    )
  return null
}

function ClusterTable({ rows }: { rows: ComplexRow[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="whitespace-nowrap">전용</TableHead>
            <TableHead className="whitespace-nowrap">거래</TableHead>
            <TableHead className="text-right whitespace-nowrap">호가</TableHead>
            <TableHead className="whitespace-nowrap">층/향</TableHead>
            <TableHead className="text-center whitespace-nowrap">중개수</TableHead>
            <TableHead className="whitespace-nowrap">상태</TableHead>
            <TableHead className="whitespace-nowrap">메모</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.cluster_key} className={r.excluded ? 'opacity-50' : ''}>
              <TableCell className="whitespace-nowrap">{formatArea(r.area_excl)}</TableCell>
              <TableCell className="whitespace-nowrap">
                {r.trade_ko}
                {r.rent_min != null && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    /{formatManwon(r.rent_min)}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-right whitespace-nowrap tabular-nums">
                {formatPriceRange(r.price_min, r.price_max)}
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                {[r.floor_info, r.direction].filter(Boolean).join(' · ')}
              </TableCell>
              <TableCell className="text-center tabular-nums">{r.realtor_count}</TableCell>
              <TableCell className="whitespace-nowrap">
                <RowStatusBadge row={r} />
              </TableCell>
              <TableCell>
                <MemoInput clusterKey={r.cluster_key} complexNo={r.complex_no} memo={r.memo} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function DealTable({ deals }: { deals: DealRow[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="whitespace-nowrap">날짜</TableHead>
            <TableHead className="whitespace-nowrap">거래</TableHead>
            <TableHead className="whitespace-nowrap">전용</TableHead>
            <TableHead className="whitespace-nowrap">층</TableHead>
            <TableHead className="text-right whitespace-nowrap">실거래가</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {deals.map((d) => (
            <TableRow key={d.deal_key} className={d.cancelled ? 'opacity-50 line-through' : ''}>
              <TableCell className="whitespace-nowrap tabular-nums">
                {d.deal_date.replace(/-/g, '.')}
              </TableCell>
              <TableCell className="whitespace-nowrap">{d.trade_ko}</TableCell>
              <TableCell className="whitespace-nowrap">{formatArea(d.area_excl)}</TableCell>
              <TableCell className="tabular-nums">{d.floor ?? '-'}</TableCell>
              <TableCell className="text-right whitespace-nowrap tabular-nums">
                {formatManwon(d.price_deal)}
                {d.price_rent != null && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    /{formatManwon(d.price_rent)}
                  </span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function AreaFilterBar({
  areas,
  selected,
  onChange,
}: {
  areas: number[]
  selected: number | null
  onChange: (a: number | null) => void
}) {
  if (areas.length <= 1) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      <button
        type="button"
        onClick={() => onChange(null)}
        className={`rounded border px-2 py-0.5 text-xs transition-colors ${
          selected === null
            ? 'bg-primary text-primary-foreground'
            : 'text-muted-foreground hover:bg-muted'
        }`}
      >
        전체
      </button>
      {areas.map((a) => (
        <button
          key={a}
          type="button"
          onClick={() => onChange(a)}
          className={`rounded border px-2 py-0.5 text-xs transition-colors ${
            selected === a
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted'
          }`}
        >
          {formatAreaWithPyeong(a)}
        </button>
      ))}
    </div>
  )
}

export function ComplexDetailPage() {
  const { no } = useParams<{ no: string }>()
  const [areaFilter, setAreaFilter] = useState<number | null>(null)

  const query = useQuery({
    queryKey: complexKeys.detail(no!),
    queryFn: () => getComplex(no!),
    enabled: !!no,
  })

  const rows = query.data?.rows ?? []
  const deals = query.data?.deals ?? []

  // 매물·실거래 전체에서 고유 전용면적 목록
  const uniqueAreas = useMemo(() => {
    const set = new Set<number>()
    rows.forEach(r => { if (r.area_excl != null) set.add(r.area_excl) })
    deals.forEach(d => { if (d.area_excl != null) set.add(d.area_excl) })
    return [...set].sort((a, b) => a - b)
  }, [rows, deals])

  if (query.isError) {
    return (
      <p className="rounded-lg border border-destructive/50 p-8 text-center text-sm text-destructive">
        불러오기 실패: {String(query.error)}
      </p>
    )
  }

  if (!query.data) {
    return (
      <p className="rounded-lg border p-8 text-center text-muted-foreground">불러오는 중…</p>
    )
  }

  const { stat } = query.data
  const filteredRows = areaFilter === null ? rows : rows.filter(r => r.area_excl === areaFilter)
  const filteredDeals = areaFilter === null ? deals : deals.filter(d => d.area_excl === areaFilter)

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div>
        <div className="mb-1 text-sm text-muted-foreground">
          <Link to="/" className="hover:underline">
            ← 매물 목록
          </Link>
        </div>
        <div className="flex items-center gap-2">
          <StarButton complexNo={stat.complex_no} starred={stat.starred} />
          <h1 className="text-xl font-bold">{stat.name}</h1>
          <a
            href={`https://new.land.naver.com/complexes/${stat.complex_no}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            네이버 ↗
          </a>
        </div>
        {stat.meta_line && (
          <p className="mt-1 text-sm text-muted-foreground">{stat.meta_line}</p>
        )}
      </div>

      {/* 통계 요약 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span>
          거래중 <b>{stat.active_count}</b>건
        </span>
        {Object.entries(stat.by_trade).map(([k, v]) => (
          <span key={k} className="text-muted-foreground">
            · {k} {v}건
          </span>
        ))}
        {(stat.price_min != null || stat.price_max != null) && (
          <span className="text-muted-foreground">
            · {formatPriceRange(stat.price_min, stat.price_max)}
          </span>
        )}
      </div>

      {/* 평수 필터 */}
      <AreaFilterBar areas={uniqueAreas} selected={areaFilter} onChange={setAreaFilter} />

      {/* 매물 목록 */}
      <section>
        <h2 className="mb-2 text-base font-semibold">
          매물 ({filteredRows.length}건{areaFilter !== null ? ` / 전체 ${rows.length}건` : ''})
        </h2>
        {filteredRows.length === 0 ? (
          <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
            매물 없음
          </p>
        ) : (
          <ClusterTable rows={filteredRows} />
        )}
      </section>

      {/* 실거래 목록 */}
      <section>
        <h2 className="mb-2 text-base font-semibold">
          실거래 최근 2년 ({filteredDeals.length}건{areaFilter !== null ? ` / 전체 ${deals.length}건` : ''})
        </h2>
        {filteredDeals.length === 0 ? (
          <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
            실거래 내역 없음
          </p>
        ) : (
          <DealTable deals={filteredDeals} />
        )}
      </section>
    </div>
  )
}
