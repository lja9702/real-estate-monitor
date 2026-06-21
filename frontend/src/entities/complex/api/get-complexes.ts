import { apiGet } from '@/shared/api/client'
import { apiPostForm } from '@/shared/api/client'
import type { TrackingRow } from '../model/types'

export const complexesKeys = {
  all: ['complexes'] as const,
}

export async function getComplexes(): Promise<{ rows: TrackingRow[] }> {
  return apiGet('/api/complexes')
}

export async function trackComplex(no: string): Promise<{ ok: boolean }> {
  return apiPostForm(`/complexes/${no}/track`)
}

export async function untrackComplex(no: string): Promise<{ ok: boolean }> {
  return apiPostForm(`/complexes/${no}/untrack`)
}
