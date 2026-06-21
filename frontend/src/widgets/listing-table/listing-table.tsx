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
import type { ListingRow } from '@/entities/listing/model/types'

function DealCell({ row }: { row: ListingRow }) {
  if (row.deal_price_min == null) return <span className="text-muted-foreground">-</span>
  return (
    <span className="tabular-nums">
      {formatPriceRange(row.deal_price_min, row.deal_price_max)}
      {!row.deal_is_recent && (
        <span className="ml-1 text-xs text-muted-foreground">(과거)</span>
      )}
    </span>
  )
}

export function ListingTable({ rows }: { rows: ListingRow[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>단지</TableHead>
            <TableHead className="whitespace-nowrap">전용</TableHead>
            <TableHead className="whitespace-nowrap">거래</TableHead>
            <TableHead className="text-right whitespace-nowrap">호가</TableHead>
            <TableHead className="text-right whitespace-nowrap">실거래</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.rep_cluster_key} className={r.excluded ? 'opacity-50' : ''}>
              <TableCell>
                <div className="flex items-center gap-1.5">
                  {r.starred && <span className="text-amber-500">★</span>}
                  {r.rep_article_url ? (
                    <a
                      href={r.rep_article_url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium hover:underline"
                    >
                      {r.complex_name}
                    </a>
                  ) : (
                    <span className="font-medium">{r.complex_name}</span>
                  )}
                  {r.is_new && (
                    <Badge variant="default" className="h-5 px-1.5 text-[10px]">
                      신규
                    </Badge>
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
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
