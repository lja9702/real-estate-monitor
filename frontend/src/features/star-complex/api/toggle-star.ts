import { apiPostForm } from '@/shared/api/client'

export interface StarResult {
  ok: boolean
  complex_no: string
  starred: boolean
}

// 관심(별표) 토글 — 단지 단위. 백엔드가 현재값을 뒤집어 새 상태를 돌려준다.
export function toggleStar(complexNo: string): Promise<StarResult> {
  return apiPostForm<StarResult>(`/complexes/${complexNo}/star`)
}
