import { apiGet } from '@/shared/api/client'
import type { ComplexDetailResponse } from '../model/types'

export const complexKeys = {
  detail: (no: string) => ['complex', no] as const,
}

export async function getComplex(no: string): Promise<ComplexDetailResponse> {
  return apiGet<ComplexDetailResponse>(`/api/complex/${no}`)
}
