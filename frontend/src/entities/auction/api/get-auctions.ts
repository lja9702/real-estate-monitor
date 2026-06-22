import { apiGet } from '@/shared/api/client'
import type { AuctionFilters, AuctionsResponse } from '../model/types'

export const auctionKeys = {
  list: (f: AuctionFilters) => ['auctions', f] as const,
}

export function auctionFiltersToParams(f: AuctionFilters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.gu) p.set('gu', f.gu)
  if (f.complex_no) p.set('complex_no', f.complex_no)
  if (f.sort && f.sort !== 'date_asc') p.set('sort', f.sort)
  return p
}

export async function getAuctions(f: AuctionFilters): Promise<AuctionsResponse> {
  const qs = auctionFiltersToParams(f).toString()
  return apiGet<AuctionsResponse>(`/api/auctions${qs ? `?${qs}` : ''}`)
}
