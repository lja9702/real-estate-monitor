import { apiGet } from '@/shared/api/client'
import type { AuctionDetail } from '../model/types'

export const auctionDetailKey = (key: string) => ['auction-detail', key] as const

export async function getAuctionDetail(auctionKey: string): Promise<AuctionDetail> {
  return apiGet<AuctionDetail>(`/api/auction/${encodeURIComponent(auctionKey)}`)
}
