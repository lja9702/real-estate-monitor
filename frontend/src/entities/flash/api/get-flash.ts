import { apiGet } from '@/shared/api/client'
import type { FlashFilters, FlashResponse } from '../model/types'

export const flashKeys = {
  list: (f: FlashFilters) => ['flash', f] as const,
}

export function flashFiltersToParams(f: FlashFilters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.trade_type) p.set('trade_type', f.trade_type)
  if (f.days) p.set('days', f.days)
  if (f.gu) p.set('gu', f.gu)
  if (f.dong) p.set('dong', f.dong)
  if (f.complex_no) p.set('complex_no', f.complex_no)
  if (f.trigger) p.set('trigger', f.trigger)
  if (f.include_inactive) p.set('include_inactive', 'true')
  if (f.sort && f.sort !== 'drop_pct_desc') p.set('sort', f.sort)
  return p
}

export async function getFlash(f: FlashFilters): Promise<FlashResponse> {
  const qs = flashFiltersToParams(f).toString()
  return apiGet<FlashResponse>(`/api/flash${qs ? `?${qs}` : ''}`)
}
