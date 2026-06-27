import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { complexKeys, getComplex } from '@/entities/complex/api/get-complex'
import type { ComplexRow, DealRow } from '@/entities/complex/model/types'
import type { AuctionRow } from '@/entities/auction/model/types'
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

function ClusterCard({ row: r }: { row: ComplexRow }) {
  return (
    <div className={`rounded-lg border p-3 ${r.excluded ? 'opacity-50' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-1.5">
            <span className="font-medium">{formatArea(r.area_excl)}</span>
            <span className="text-sm text-muted-foreground">
              {r.trade_ko}
              {r.rent_min != null && ` /${formatManwon(r.rent_min)}`}
            </span>
            <RowStatusBadge row={r} />
          </div>
          <div className="text-xs text-muted-foreground">
            {[r.floor_info, r.direction].filter(Boolean).join(' · ')}
            {` · 중개 ${r.realtor_count}곳`}
          </div>
        </div>
        <span className="shrink-0 font-semibold tabular-nums">
          {formatPriceRange(r.price_min, r.price_max)}
        </span>
      </div>
      <div className="mt-2">
        <MemoInput clusterKey={r.cluster_key} complexNo={r.complex_no} memo={r.memo} />
      </div>
    </div>
  )
}

function ClusterTable({ rows }: { rows: ComplexRow[] }) {
  return (
    <>
    {/* 모바일: 카드 */}
    <div className="space-y-2 md:hidden">
      {rows.map((r) => (
        <ClusterCard key={r.cluster_key} row={r} />
      ))}
    </div>
    {/* 데스크탑: 테이블 */}
    <div className="hidden overflow-x-auto rounded-lg border md:block">
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
    </>
  )
}

function DealTable({ deals }: { deals: DealRow[] }) {
  return (
    <>
    {/* 모바일: 카드 */}
    <div className="space-y-2 md:hidden">
      {deals.map((d) => (
        <div
          key={d.deal_key}
          className={`flex items-baseline justify-between gap-2 rounded-lg border p-3 ${
            d.cancelled ? 'opacity-50 line-through' : ''
          }`}
        >
          <span className="text-sm text-muted-foreground">
            {d.deal_date.replace(/-/g, '.')} · {d.trade_ko} · 전용 {formatArea(d.area_excl)}
            {d.floor != null && ` · ${d.floor}층`}
          </span>
          <span className="shrink-0 font-semibold tabular-nums">
            {formatManwon(d.price_deal)}
            {d.price_rent != null && (
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                /{formatManwon(d.price_rent)}
              </span>
            )}
          </span>
        </div>
      ))}
    </div>
    {/* 데스크탑: 테이블 */}
    <div className="hidden overflow-x-auto rounded-lg border md:block">
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
    </>
  )
}

function AuctionCard({
  row: a,
  past,
  onOpen,
}: {
  row: AuctionRow
  past?: boolean
  onOpen: (key: string) => void
}) {
  return (
    <div
      onClick={() => onOpen(a.auction_key)}
      className={`cursor-pointer rounded-lg border p-3 ${past ? 'opacity-60' : ''}`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm tabular-nums">
            {a.sale_date?.replace(/-/g, '.') ?? '-'}
          </span>
          {a.is_new && !past && (
            <Badge variant="default" className="h-4 px-1 text-[10px]">신규</Badge>
          )}
          {a.outcome_label && (
            <Badge
              variant={a.outcome === 'sold' ? 'default' : 'secondary'}
              className="h-4 px-1 text-[10px]"
            >
              {a.outcome === 'sold' && a.final_bid_manwon != null
                ? `매각 ${formatManwon(a.final_bid_manwon)}`
                : a.outcome_label}
            </Badge>
          )}
        </div>
        <span className="shrink-0 text-sm text-muted-foreground">
          {a.fail_count > 0 ? `유찰 ${a.fail_count}회` : '신건'}
        </span>
      </div>
      {a.flags.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1" title={a.remarks ?? undefined}>
          {a.flags.map((f) => (
            <Badge key={f} variant="destructive" className="h-4 px-1 text-[10px]">
              {f}
            </Badge>
          ))}
        </div>
      )}
      <div className="mt-2 flex items-baseline justify-between gap-2 text-sm">
        <span className="text-muted-foreground">감정 {formatManwon(a.appraisal_manwon)}</span>
        <span className="font-semibold tabular-nums">
          최저 {formatManwon(a.min_bid_manwon)}
          {a.min_bid_ratio != null && (
            <span
              className={`ml-1 text-xs font-normal ${a.min_bid_ratio < 100 ? 'text-destructive' : 'text-muted-foreground'}`}
            >
              {a.min_bid_ratio}%
            </span>
          )}
        </span>
      </div>
      <div className="mt-1 truncate text-xs text-muted-foreground">
        {a.court_url ? (
          <a
            href={a.court_url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="hover:underline"
          >
            {a.case_no} ↗
          </a>
        ) : (
          a.case_no
        )}
        {a.court_name && ` · ${a.court_name}`}
      </div>
    </div>
  )
}

function AuctionTable({
  auctions,
  past,
  onOpen,
}: {
  auctions: AuctionRow[]
  past?: boolean
  onOpen: (key: string) => void
}) {
  return (
    <>
    {/* 모바일: 카드 */}
    <div className="space-y-2 md:hidden">
      {auctions.map((a) => (
        <AuctionCard key={a.auction_key} row={a} past={past} onOpen={onOpen} />
      ))}
    </div>
    {/* 데스크탑: 테이블 */}
    <div className="hidden overflow-x-auto rounded-lg border md:block">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="whitespace-nowrap">매각기일</TableHead>
            <TableHead className="text-right whitespace-nowrap">감정가</TableHead>
            <TableHead className="text-right whitespace-nowrap">최저가</TableHead>
            <TableHead className="whitespace-nowrap">유찰</TableHead>
            <TableHead className="whitespace-nowrap">비고</TableHead>
            <TableHead className="whitespace-nowrap">사건 / 법원</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {auctions.map((a) => (
            <TableRow
              key={a.auction_key}
              onClick={() => onOpen(a.auction_key)}
              className={`cursor-pointer ${past ? 'opacity-60' : ''}`}
            >
              <TableCell className="whitespace-nowrap tabular-nums">
                {a.sale_date?.replace(/-/g, '.') ?? '-'}
                {a.is_new && !past && (
                  <Badge variant="default" className="ml-1.5 h-4 px-1 text-[10px]">
                    신규
                  </Badge>
                )}
                {a.outcome_label && (
                  <Badge
                    variant={a.outcome === 'sold' ? 'default' : 'secondary'}
                    className="ml-1.5 h-4 px-1 text-[10px]"
                  >
                    {a.outcome === 'sold' && a.final_bid_manwon != null
                      ? `매각 ${formatManwon(a.final_bid_manwon)}`
                      : a.outcome_label}
                  </Badge>
                )}
              </TableCell>
              <TableCell className="text-right whitespace-nowrap tabular-nums">
                {formatManwon(a.appraisal_manwon)}
              </TableCell>
              <TableCell className="text-right whitespace-nowrap tabular-nums">
                {formatManwon(a.min_bid_manwon)}
                {a.min_bid_ratio != null && (
                  <span
                    className={`ml-1 text-xs ${a.min_bid_ratio < 100 ? 'text-destructive' : 'text-muted-foreground'}`}
                  >
                    {a.min_bid_ratio}%
                  </span>
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm">
                {a.fail_count > 0 ? `${a.fail_count}회` : '신건'}
              </TableCell>
              <TableCell className="max-w-[16rem] text-sm" title={a.remarks ?? undefined}>
                {a.flags.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {a.flags.map((f) => (
                      <Badge key={f} variant="destructive" className="h-4 px-1 text-[10px]">
                        {f}
                      </Badge>
                    ))}
                  </div>
                ) : a.remarks ? (
                  <span className="line-clamp-1 text-xs text-muted-foreground">{a.remarks}</span>
                ) : (
                  <span className="text-muted-foreground">-</span>
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm">
                {a.court_url ? (
                  <a
                    href={a.court_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="text-muted-foreground hover:underline"
                  >
                    {a.case_no} ↗
                  </a>
                ) : (
                  a.case_no
                )}
                {a.court_name && (
                  <div className="text-xs text-muted-foreground">{a.court_name}</div>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
    </>
  )
}

// 브라우저 로컬 기준 오늘(YYYY-MM-DD) — 매각기일(sale_date)과 문자열 비교해 진행중/지난을 가른다.
function todayLocal(): string {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

export function AuctionSection({ auctions }: { auctions: AuctionRow[] }) {
  const today = todayLocal()
  const [detailKey, setDetailKey] = useState<string | null>(null)
  // 진행중 = 매각기일 미래/미정, 지난 = 매각기일이 오늘 이전(보관기간 내 = 최근 3개월).
  const ongoing = auctions
    .filter((a) => !a.sale_date || a.sale_date >= today)
    .sort((a, b) => (a.sale_date ?? '9999-99-99').localeCompare(b.sale_date ?? '9999-99-99'))
  const past = auctions
    .filter((a) => a.sale_date && a.sale_date < today)
    .sort((a, b) => (b.sale_date ?? '').localeCompare(a.sale_date ?? ''))

  return (
    <section>
      <h2 className="mb-2 text-base font-semibold">경매 ({auctions.length}건)</h2>
      {auctions.length === 0 ? (
        <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
          경매 내역 없음
        </p>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-muted-foreground">행을 누르면 기일내역·물건비고 상세를 봅니다.</p>
          <div>
            <h3 className="mb-1.5 text-sm font-medium text-muted-foreground">
              진행중 ({ongoing.length}건)
            </h3>
            {ongoing.length === 0 ? (
              <p className="rounded-lg border p-4 text-center text-xs text-muted-foreground">
                진행중인 경매 없음
              </p>
            ) : (
              <AuctionTable auctions={ongoing} onOpen={setDetailKey} />
            )}
          </div>
          {past.length > 0 && (
            <div>
              <h3 className="mb-1.5 text-sm font-medium text-muted-foreground">
                지난 경매 ({past.length}건 · 최근 3개월)
              </h3>
              <AuctionTable auctions={past} past onOpen={setDetailKey} />
            </div>
          )}
        </div>
      )}
      <AuctionDetailDialog auctionKey={detailKey} onClose={() => setDetailKey(null)} />
    </section>
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
  const auctions = query.data?.auctions ?? []

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

      {/* 경매 목록 (진행중 / 지난 — 최근 3개월 보관) */}
      <AuctionSection auctions={auctions} />
    </div>
  )
}
