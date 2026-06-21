import { apiGet } from '@/shared/api/client'
import type { RunsResponse } from '../model/types'

export const runKeys = {
  all: ['runs'] as const,
}

export async function getRuns(): Promise<RunsResponse> {
  return apiGet<RunsResponse>('/api/runs')
}
