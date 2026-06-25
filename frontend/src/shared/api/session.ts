import { useQuery } from '@tanstack/react-query'
import { apiGet } from './client'

// /api/me — 현재 세션 역할(admin·local·member)과 서버 읽기전용 여부.
export type Me = { authenticated: boolean; role: string; readonly: boolean }

export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: () => apiGet<Me>('/api/me') })
}

// 쓰기(수집·추적 변경 등) 가능 여부 — 읽기전용이 아니고 운영자/로컬일 때만.
// 클라우드(readonly) 지인(member)에겐 false → 수집/추적중단 컨트롤을 숨긴다.
export function canWrite(me: Me | undefined): boolean {
  return !!me && !me.readonly && (me.role === 'admin' || me.role === 'local')
}
