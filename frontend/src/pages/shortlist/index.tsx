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
        <div className="overflow-x-auto rounded-lg border">
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
      )}
    </div>
  )
}
