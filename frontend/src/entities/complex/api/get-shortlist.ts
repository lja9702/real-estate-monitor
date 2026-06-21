import { apiGet } from '@/shared/api/client'
import type { StarredComplexRow } from '../model/types'

export const shortlistKeys = {
  all: ['shortlist'] as const,
}

export async function getShortlist(): Promise<{ rows: StarredComplexRow[] }> {
  return apiGet('/api/shortlist')
}
