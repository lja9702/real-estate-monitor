import { apiPostForm } from '@/shared/api/client'

export interface MemoResult {
  cluster_key: string
  memo: string
}

// 메모 저장 — cluster_key 기준 큐레이션. complex_no 는 새 큐레이션 행 생성 시 소유 표시용.
export function saveMemo(
  clusterKey: string,
  memo: string,
  complexNo?: string,
): Promise<MemoResult> {
  const data: Record<string, string> = { memo }
  if (complexNo) data.complex_no = complexNo
  return apiPostForm<MemoResult>(`/curation/${clusterKey}/memo`, data)
}
