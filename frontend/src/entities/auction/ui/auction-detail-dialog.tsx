import { useQuery } from '@tanstack/react-query'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { formatManwon } from '@/shared/lib/format'
import { auctionDetailKey, getAuctionDetail } from '../api/get-auction-detail'
import type { AuctionDateEvent } from '../model/types'

function dot(iso: string | null): string {
  return iso && iso.length >= 10 ? iso.replace(/-/g, '.').slice(2) : '-'
}

// 기일 결과 색: 매각/낙찰=초록, 유찰/미납/불허=빨강, 그 외(변경 등)=회색.
function resultClass(result: string): string {
  if (!result) return 'text-muted-foreground'
  if (/불허|유찰|미납/.test(result)) return 'text-destructive font-medium'
  if (/매각|낙찰|허가/.test(result)) return 'text-green-600 dark:text-green-500 font-medium'
  return 'text-foreground'
}

function EventRow({ e }: { e: AuctionDateEvent }) {
  return (
    <div className="flex items-baseline gap-2 border-b py-1.5 text-sm last:border-0">
      <span className="w-16 shrink-0 tabular-nums text-muted-foreground">{dot(e.date)}</span>
      <span className="w-24 shrink-0 text-xs text-muted-foreground">{e.kind}</span>
      <span className={`flex-1 ${resultClass(e.result)}`}>{e.result || '예정'}</span>
      {e.low_price_manwon != null && (
        <span className="shrink-0 tabular-nums text-xs text-muted-foreground">
          {formatManwon(e.low_price_manwon)}
        </span>
      )}
    </div>
  )
}

export function AuctionDetailDialog({
  auctionKey,
  onClose,
}: {
  auctionKey: string | null
  onClose: () => void
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: auctionDetailKey(auctionKey ?? ''),
    queryFn: () => getAuctionDetail(auctionKey as string),
    enabled: !!auctionKey,
  })

  return (
    <Dialog open={!!auctionKey} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{data?.complex_name ?? '경매 물건 상세'}</DialogTitle>
          <DialogDescription>
            {data ? `${data.case_no}${data.court_name ? ` · ${data.court_name}` : ''}` : ''}
            {data?.address ? <span className="mt-0.5 block">{data.address}</span> : null}
          </DialogDescription>
        </DialogHeader>

        {isLoading && <p className="py-6 text-center text-sm text-muted-foreground">불러오는 중…</p>}
        {isError && (
          <p className="py-6 text-center text-sm text-destructive">상세를 불러오지 못했습니다.</p>
        )}

        {data && (
          <div className="space-y-4">
            {/* 요약 */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              {data.area_excl != null && (
                <span className="text-muted-foreground">전용 {Math.round(data.area_excl)}㎡</span>
              )}
              <span>감정 {formatManwon(data.appraisal_manwon)}</span>
              <span>
                최저 {formatManwon(data.min_bid_manwon)}
                {data.min_bid_ratio != null && (
                  <span className="ml-1 text-xs text-muted-foreground">({data.min_bid_ratio}%)</span>
                )}
              </span>
              <span className="text-muted-foreground">
                {data.fail_count > 0 ? `${data.fail_count}회 유찰` : '신건'}
              </span>
              {data.outcome_label && (
                <Badge variant={data.outcome === 'sold' ? 'default' : 'secondary'} className="h-5">
                  {data.outcome === 'sold' && data.final_bid_manwon != null
                    ? `매각 ${formatManwon(data.final_bid_manwon)}`
                    : data.outcome_label}
                </Badge>
              )}
            </div>

            {/* 물건비고 */}
            {(data.flags.length > 0 || data.remarks) && (
              <div>
                <h3 className="mb-1 text-xs font-medium text-muted-foreground">물건비고</h3>
                {data.flags.length > 0 && (
                  <div className="mb-1 flex flex-wrap gap-1">
                    {data.flags.map((f) => (
                      <Badge key={f} variant="destructive" className="h-5 px-1.5 text-[11px]">
                        {f}
                      </Badge>
                    ))}
                  </div>
                )}
                {data.remarks && (
                  <p className="whitespace-pre-line text-sm text-muted-foreground">{data.remarks}</p>
                )}
              </div>
            )}

            {/* 기일내역 */}
            <div>
              <h3 className="mb-1 text-xs font-medium text-muted-foreground">기일내역</h3>
              {data.events.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  기일내역을 불러올 수 없습니다(법원 조회 실패 또는 동기화 전).
                </p>
              ) : (
                <div className="rounded-lg border px-3 py-1">
                  {data.events.map((e, i) => (
                    <EventRow key={`${e.date}-${e.kind}-${i}`} e={e} />
                  ))}
                </div>
              )}
            </div>

            {data.court_url && (
              <a
                href={data.court_url}
                target="_blank"
                rel="noreferrer"
                className="inline-block text-sm text-muted-foreground hover:underline"
              >
                법원경매정보에서 사건 검색 ↗ <code className="text-xs">{data.case_no}</code>
              </a>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
