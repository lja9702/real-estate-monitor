import { apiGet } from '@/shared/api/client'
import type { PermitFilters, PermitsResponse } from '../model/types'

export const permitKeys = {
  list: (f: PermitFilters) => ['permits', f] as const,
}

export function permitFiltersToParams(f: PermitFilters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.gu) p.set('gu', f.gu)
  if (f.complex_no) p.set('complex_no', f.complex_no)
  if (f.months) p.set('months', f.months)
  if (f.job_gbn) p.set('job_gbn', f.job_gbn)
  if (f.sort && f.sort !== 'date_desc') p.set('sort', f.sort)
  return p
}

export async function getPermits(f: PermitFilters): Promise<PermitsResponse> {
  const qs = permitFiltersToParams(f).toString()
  return apiGet<PermitsResponse>(`/api/permits${qs ? `?${qs}` : ''}`)
}
