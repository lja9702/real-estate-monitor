import { Link } from 'react-router-dom'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { formatArea, formatManwon, formatPriceRange } from '@/shared/lib/format'
import { StarButton } from '@/features/star-complex/ui/star-button'
import { MemoInput } from '@/features/edit-memo/ui/memo-input'
import type { ListingRow } from '@/entities/listing/model/types'

function DealCell({ row }: { row: ListingRow }) {
  if (row.deal_price_min == null) {
    return <span className="text-muted-foreground">-</span>
  }
  // 최근 1개월 범위.
  if (row.deal_is_recent) {
    return (
      <span className="tabular-nums">
        {formatPriceRange(row.deal_price_min, row.deal_price_max)}
      </span>
    )
  }
  // 과거 최근 1건 — 가격 + YY-MM (원본 _area_group_table 의 deal_date[2:7]).
  return (
    <span className="tabular-nums">
      {formatManwon(row.deal_price_min)}
      {row.deal_date && (
        <span className="ml-1 text-xs text-muted-foreground">
          {row.deal_date.slice(2, 7)}
        </span>
      )}
    </span>
  )
}

// 모바일 카드 — 좁은 화면에선 가로 스크롤 대신 한 건씩 카드로 본다.
function ListingCard({ row: r }: { row: ListingRow }) {
  return (
    <div className={`rounded-lg border p-3 ${r.excluded ? 'opacity-50' : ''}`}>
      <div className="flex items-start gap-2">
        <StarButton complexNo={r.complex_no} starred={r.starred} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <Link
              to={`/complex/${r.complex_no}`}
              className="truncate font-medium hover:underline"
            >
              {r.complex_name}
            </Link>
            {r.is_new && (
              <Badge variant="default" className="h-5 shrink-0 px-1.5 text-[10px]">
                신규
              </Badge>
            )}
            {r.rep_article_url && (
              <a
                href={r.rep_article_url}
                target="_blank"
                rel="noreferrer"
                className="ml-auto shrink-0 text-xs text-muted-foreground hover:text-foreground hover:underline"
              >
                네이버↗
              </a>
            )}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {[r.address_short, r.meta_line].filter(Boolean).join(' · ')}
          </div>
        </div>
      </div>

      <div className="mt-2 flex items-baseline justify-between gap-2">
        <span className="text-sm text-muted-foreground">
          {r.trade_ko} · 전용 {formatArea(r.area_excl)}
          {r.rent_min != null && (
            <span className="ml-1">/{formatManwon(r.rent_min)}</span>
          )}
        </span>
        <span className="text-right font-semibold tabular-nums">
          {formatPriceRange(r.price_min, r.price_max)}
        </span>
      </div>

      <div className="mt-1 flex items-baseline justify-between gap-2 text-sm">
        <span className="text-muted-foreground">실거래</span>
        <DealCell row={r} />
      </div>

      <div className="mt-2">
        <MemoInput
          clusterKey={r.rep_cluster_key}
          complexNo={r.complex_no}
          memo={r.memo}
        />
      </div>
    </div>
  )
}

export function ListingTable({ rows }: { rows: ListingRow[] }) {
  return (
    <>
      {/* 모바일: 카드 목록 */}
      <div className="space-y-2 md:hidden">
        {rows.map((r) => (
          <ListingCard key={r.rep_cluster_key} row={r} />
        ))}
      </div>

      {/* 데스크탑: 전체폭 테이블 */}
      <div className="hidden overflow-x-auto rounded-lg border md:block">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8 text-center">★</TableHead>
            <TableHead>단지</TableHead>
            <TableHead className="whitespace-nowrap">전용</TableHead>
            <TableHead className="whitespace-nowrap">거래</TableHead>
            <TableHead className="text-right whitespace-nowrap">호가</TableHead>
            <TableHead className="text-right whitespace-nowrap">실거래</TableHead>
            <TableHead className="whitespace-nowrap">상태</TableHead>
            <TableHead className="whitespace-nowrap">메모</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.rep_cluster_key} className={r.excluded ? 'opacity-50' : ''}>
              <TableCell className="text-center">
                <StarButton complexNo={r.complex_no} starred={r.starred} />
              </TableCell>
              <TableCell>
                <div className="font-medium">
                  <Link to={`/complex/${r.complex_no}`} className="hover:underline">
                    {r.complex_name}
                  </Link>
                  {r.rep_article_url && (
                    <a
                      href={r.rep_article_url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-1.5 text-xs font-normal text-muted-foreground hover:text-foreground hover:underline"
                    >
                      네이버↗
                    </a>
                  )}
                </div>
                <div className="text-xs text-muted-foreground">
                  {[r.address_short, r.meta_line].filter(Boolean).join(' · ')}
                </div>
              </TableCell>
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
              <TableCell className="text-right whitespace-nowrap">
                <DealCell row={r} />
              </TableCell>
              <TableCell className="whitespace-nowrap">
                {r.is_new && (
                  <Badge variant="default" className="h-5 px-1.5 text-[10px]">
                    신규
                  </Badge>
                )}
              </TableCell>
              <TableCell>
                <MemoInput
                  clusterKey={r.rep_cluster_key}
                  complexNo={r.complex_no}
                  memo={r.memo}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      </div>
    </>
  )
}
