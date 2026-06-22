import { apiGet } from '@/shared/api/client'
import type { DealFilters, DealsResponse } from '../model/types'

export const dealKeys = {
  list: (f: DealFilters) => ['deals', f] as const,
}

export function dealFiltersToParams(f: DealFilters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.trade_type) p.set('trade_type', f.trade_type)
  if (f.months) p.set('months', f.months)
  if (f.gu) p.set('gu', f.gu)
  if (f.dong) p.set('dong', f.dong)
  if (f.complex_no) p.set('complex_no', f.complex_no)
  if (f.include_cancelled) p.set('include_cancelled', 'true')
  if (f.sort && f.sort !== 'date_desc') p.set('sort', f.sort)
  return p
}

export async function getDeals(f: DealFilters): Promise<DealsResponse> {
  const qs = dealFiltersToParams(f).toString()
  return apiGet<DealsResponse>(`/api/deals${qs ? `?${qs}` : ''}`)
}
