import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  complexesKeys,
  getComplexes,
  trackComplex,
  untrackComplex,
} from '@/entities/complex/api/get-complexes'
import { useMe, canWrite } from '@/shared/api/session'
import type { TrackingRow } from '@/entities/complex/model/types'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

function ComplexTable({
  rows,
  onToggle,
  pendingNo,
  writable,
}: {
  rows: TrackingRow[]
  onToggle: (row: TrackingRow) => void
  pendingNo: string | null
  writable: boolean
}) {
  return (
    <>
    {/* 모바일: 카드 */}
    <div className="space-y-2 md:hidden">
      {rows.map((r) => (
        <div key={r.complex_no} className="rounded-lg border p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <Link to={`/complex/${r.complex_no}`} className="font-medium hover:underline">
                {r.name}
              </Link>
              {(r.address_short || r.meta_line) && (
                <div className="text-xs text-muted-foreground">
                  {[r.address_short, r.meta_line].filter(Boolean).join(' · ')}
                </div>
              )}
            </div>
            {writable && (
              <Button
                size="sm"
                variant={r.is_active ? 'outline' : 'default'}
                disabled={pendingNo === r.complex_no}
                onClick={() => onToggle(r)}
                className="h-7 shrink-0 text-xs"
              >
                {pendingNo === r.complex_no ? '…' : r.is_active ? '추적 중단' : '추적 재개'}
              </Button>
            )}
          </div>
          <div className="mt-2 flex items-center justify-between gap-2 text-sm text-muted-foreground">
            <span>{r.source_ko}</span>
            <span className="tabular-nums">활성 매물 {r.active_count}건</span>
          </div>
        </div>
      ))}
    </div>
    {/* 데스크탑: 테이블 */}
    <div className="hidden overflow-x-auto rounded-lg border md:block">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>단지</TableHead>
            <TableHead className="whitespace-nowrap">출처</TableHead>
            <TableHead className="text-right whitespace-nowrap">활성 매물</TableHead>
            <TableHead className="w-24" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.complex_no}>
              <TableCell>
                <Link to={`/complex/${r.complex_no}`} className="font-medium hover:underline">
                  {r.name}
                </Link>
                {(r.address_short || r.meta_line) && (
                  <div className="text-xs text-muted-foreground">
                    {[r.address_short, r.meta_line].filter(Boolean).join(' · ')}
                  </div>
                )}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">{r.source_ko}</TableCell>
              <TableCell className="text-right tabular-nums">{r.active_count}</TableCell>
              <TableCell>
                {writable && (
                  <Button
                    size="sm"
                    variant={r.is_active ? 'outline' : 'default'}
                    disabled={pendingNo === r.complex_no}
                    onClick={() => onToggle(r)}
                    className="h-7 text-xs"
                  >
                    {pendingNo === r.complex_no ? '…' : r.is_active ? '추적 중단' : '추적 재개'}
                  </Button>
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

export function ComplexesPage() {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: complexesKeys.all, queryFn: getComplexes })
  const me = useMe()
  const writable = canWrite(me.data) // 운영자/로컬에서만 추적 변경 가능

  const mutation = useMutation({
    mutationFn: (row: TrackingRow) =>
      row.is_active ? untrackComplex(row.complex_no) : trackComplex(row.complex_no),
    onSuccess: () => qc.invalidateQueries({ queryKey: complexesKeys.all }),
  })

  const pendingNo = mutation.isPending ? (mutation.variables?.complex_no ?? null) : null
  const rows = query.data?.rows ?? []
  const tracked = rows.filter((r) => r.is_active)
  const untracked = rows.filter((r) => !r.is_active)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">
          <Link to="/" className="hover:underline">
            ← 매물 목록
          </Link>
        </div>
        <h1 className="text-xl font-bold">추적 단지</h1>
        <div />
      </div>

      {!writable && (
        <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
          추적 중단은 텔레그램 봇에서{' '}
          <code className="rounded bg-muted px-1 text-foreground">/untrack 단지번호</code> 또는{' '}
          <code className="rounded bg-muted px-1 text-foreground">/untrack 단지명</code> 으로 할 수
          있어요. <code className="rounded bg-muted px-1 text-foreground">/list</code> 로 목록을
          확인하세요.
        </p>
      )}

      {query.isError ? (
        <p className="rounded-lg border border-destructive/50 p-8 text-center text-sm text-destructive">
          불러오기 실패: {String(query.error)}
        </p>
      ) : !query.data ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">불러오는 중…</p>
      ) : (
        <>
          <section>
            <h2 className="mb-2 text-base font-semibold">추적 중 ({tracked.length})</h2>
            {tracked.length === 0 ? (
              <p className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
                없음
              </p>
            ) : (
              <ComplexTable rows={tracked} onToggle={(r) => mutation.mutate(r)} pendingNo={pendingNo} writable={writable} />
            )}
          </section>

          {untracked.length > 0 && (
            <section>
              <h2 className="mb-2 text-base font-semibold text-muted-foreground">
                추적 중단 ({untracked.length})
              </h2>
              <ComplexTable rows={untracked} onToggle={(r) => mutation.mutate(r)} pendingNo={pendingNo} writable={writable} />
            </section>
          )}
        </>
      )}
    </div>
  )
}
