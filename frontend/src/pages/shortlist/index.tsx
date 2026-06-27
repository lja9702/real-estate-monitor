import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { shortlistKeys, getShortlist } from '@/entities/complex/api/get-shortlist'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatPriceRange } from '@/shared/lib/format'
import type { StarredComplexRow } from '@/entities/complex/model/types'

// 모바일 카드 — 좁은 화면에선 가로 스크롤 대신 한 건씩 카드로.
function ShortlistCard({ row: r }: { row: StarredComplexRow }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-1.5">
            <Link to={`/complex/${r.complex_no}`} className="font-medium hover:underline">
              {r.name}
            </Link>
            {!r.is_active && (
              <Badge variant="secondary" className="h-4 px-1 text-[10px]">추적중단</Badge>
            )}
          </div>
          {(r.address_short || r.meta_line) && (
            <div className="text-xs text-muted-foreground">
              {[r.address_short, r.meta_line].filter(Boolean).join(' · ')}
            </div>
          )}
        </div>
        {r.new_count > 0 && (
          <Badge variant="default" className="h-5 shrink-0 px-1.5 text-[10px]">
            신규 +{r.new_count}
          </Badge>
        )}
      </div>
      <div className="mt-2 flex items-baseline justify-between gap-2 text-sm">
        <span className="text-muted-foreground">활성 매물 {r.active_count}건</span>
        <span className="font-semibold tabular-nums">
          {formatPriceRange(r.sale_min, r.sale_max)}
        </span>
      </div>
    </div>
  )
}

export function ShortlistPage() {
  const query = useQuery({ queryKey: shortlistKeys.all, queryFn: getShortlist })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">
          <Link to="/" className="hover:underline">
            ← 매물 목록
          </Link>
        </div>
        <h1 className="text-xl font-bold">관심 단지</h1>
        <div />
      </div>

      {query.isError ? (
        <p className="rounded-lg border border-destructive/50 p-8 text-center text-sm text-destructive">
          불러오기 실패: {String(query.error)}
        </p>
      ) : !query.data ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">불러오는 중…</p>
      ) : query.data.rows.length === 0 ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">
          관심 단지가 없습니다. 매물 목록에서 ★를 눌러 추가하세요.
        </p>
      ) : (
        <>
        {/* 모바일: 카드 */}
        <div className="space-y-2 md:hidden">
          {query.data.rows.map((r) => (
            <ShortlistCard key={r.complex_no} row={r} />
          ))}
        </div>
        {/* 데스크탑: 테이블 */}
        <div className="hidden overflow-x-auto rounded-lg border md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>단지</TableHead>
                <TableHead className="text-right whitespace-nowrap">활성 매물</TableHead>
                <TableHead className="text-right whitespace-nowrap">신규</TableHead>
                <TableHead className="text-right whitespace-nowrap">매매 호가</TableHead>
                <TableHead className="whitespace-nowrap">상태</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.rows.map((r) => (
                <TableRow key={r.complex_no}>
                  <TableCell>
                    <Link
                      to={`/complex/${r.complex_no}`}
                      className="font-medium hover:underline"
                    >
                      {r.name}
                    </Link>
                    {(r.address_short || r.meta_line) && (
                      <div className="text-xs text-muted-foreground">
                        {[r.address_short, r.meta_line].filter(Boolean).join(' · ')}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{r.active_count}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {r.new_count > 0 ? (
                      <Badge variant="default" className="h-5 px-1.5 text-[10px]">
                        +{r.new_count}
                      </Badge>
                    ) : (
                      '-'
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatPriceRange(r.sale_min, r.sale_max)}
                  </TableCell>
                  <TableCell>
                    {!r.is_active && (
                      <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                        추적중단
                      </Badge>
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
