import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { runKeys, getRuns } from '@/entities/run/api/get-runs'
import type { RunRow } from '@/entities/run/model/types'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  SUCCESS: 'default',
  PARTIAL: 'outline',
  RUNNING: 'secondary',
  FAILED: 'destructive',
}

const STATUS_KO: Record<string, string> = {
  SUCCESS: '완료',
  PARTIAL: '일부',
  RUNNING: '실행중',
  FAILED: '실패',
}

const KIND_KO: Record<string, string> = {
  listings: '매물',
  deals: '실거래',
  permits: '허가',
  discover: '탐색',
}

function formatDt(iso: string | null) {
  if (!iso) return '-'
  return iso.slice(0, 16).replace('T', ' ')
}

function duration(row: RunRow) {
  if (!row.finished_at) return '-'
  const s = Math.round(
    (new Date(row.finished_at).getTime() - new Date(row.started_at).getTime()) / 1000,
  )
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`
}

// 모바일 카드 — 11열 테이블은 좁은 화면에서 못 보므로 핵심만 카드로.
function RunCard({ row: r }: { row: RunRow }) {
  return (
    <div className={`rounded-lg border p-3 ${r.error ? 'bg-destructive/5' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-1.5">
          <span className="font-medium">{KIND_KO[r.kind] ?? r.kind}</span>
          <Badge variant={STATUS_VARIANT[r.status] ?? 'outline'} className="h-4 px-1 text-[10px]">
            {STATUS_KO[r.status] ?? r.status}
          </Badge>
          <span className="text-xs text-muted-foreground">
            #{r.id} · {r.trigger}
          </span>
        </div>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{duration(r)}</span>
      </div>
      <div className="mt-0.5 text-xs tabular-nums text-muted-foreground">
        {formatDt(r.started_at)}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-sm tabular-nums">
        <span className="text-muted-foreground">대상 <b className="text-foreground">{r.targets_count}</b></span>
        <span className="text-muted-foreground">수집 <b className="text-foreground">{r.articles_fetched}</b></span>
        <span className="text-muted-foreground">신규 <b className="text-foreground">{r.new_count}</b></span>
        <span className="text-muted-foreground">삭제 <b className="text-foreground">{r.removed_count}</b></span>
        <span className="text-muted-foreground">
          오류{' '}
          <b className={r.http_errors > 0 ? 'text-destructive' : 'text-foreground'}>
            {r.http_errors}
          </b>
        </span>
      </div>
    </div>
  )
}

export function RunsPage() {
  const query = useQuery({ queryKey: runKeys.all, queryFn: getRuns })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">
          <Link to="/" className="hover:underline">
            ← 매물 목록
          </Link>
        </div>
        <h1 className="text-xl font-bold">수집 이력</h1>
        <div />
      </div>

      {query.isError ? (
        <p className="rounded-lg border border-destructive/50 p-8 text-center text-sm text-destructive">
          불러오기 실패: {String(query.error)}
        </p>
      ) : !query.data ? (
        <p className="rounded-lg border p-8 text-center text-muted-foreground">불러오는 중…</p>
      ) : (
        <>
        {/* 모바일: 카드 */}
        <div className="space-y-2 md:hidden">
          {query.data.runs.map((r) => (
            <RunCard key={r.id} row={r} />
          ))}
        </div>
        {/* 데스크탑: 테이블 */}
        <div className="hidden overflow-x-auto rounded-lg border md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="whitespace-nowrap">ID</TableHead>
                <TableHead className="whitespace-nowrap">시작</TableHead>
                <TableHead className="whitespace-nowrap">소요</TableHead>
                <TableHead className="whitespace-nowrap">종류</TableHead>
                <TableHead className="whitespace-nowrap">트리거</TableHead>
                <TableHead className="whitespace-nowrap">상태</TableHead>
                <TableHead className="text-right whitespace-nowrap">대상</TableHead>
                <TableHead className="text-right whitespace-nowrap">수집</TableHead>
                <TableHead className="text-right whitespace-nowrap">신규</TableHead>
                <TableHead className="text-right whitespace-nowrap">삭제</TableHead>
                <TableHead className="text-right whitespace-nowrap">오류</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.runs.map((r) => (
                <TableRow key={r.id} className={r.error ? 'bg-destructive/5' : ''}>
                  <TableCell className="tabular-nums text-muted-foreground">{r.id}</TableCell>
                  <TableCell className="whitespace-nowrap tabular-nums text-sm">
                    {formatDt(r.started_at)}
                  </TableCell>
                  <TableCell className="tabular-nums text-sm text-muted-foreground">
                    {duration(r)}
                  </TableCell>
                  <TableCell>{KIND_KO[r.kind] ?? r.kind}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{r.trigger}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[r.status] ?? 'outline'} className="h-5 px-1.5 text-[10px]">
                      {STATUS_KO[r.status] ?? r.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{r.targets_count}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.articles_fetched}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.new_count}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.removed_count}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {r.http_errors > 0 ? (
                      <span className="text-destructive">{r.http_errors}</span>
                    ) : (
                      r.http_errors
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
