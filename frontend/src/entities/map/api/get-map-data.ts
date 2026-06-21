import { apiGet } from '@/shared/api/client'
import type { MapComplexRow, MapConfig } from '../model/types'

export const mapKeys = {
  data: () => ['map', 'data'] as const,
  config: () => ['map', 'config'] as const,
}

export function getMapData(): Promise<MapComplexRow[]> {
  return apiGet('/api/map-data')
}

export function getMapConfig(): Promise<MapConfig> {
  return apiGet('/api/config')
}
