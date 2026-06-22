// 최소 fetch 래퍼 — SPA(/app)와 API(/api)는 동일 오리진이라 절대경로로 호출한다.
// dev(5173)에서는 vite proxy 가 /api·/curation·/complexes 를 FastAPI(8765)로 넘긴다.
export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText} — ${path}`)
  }
  return (await res.json()) as T
}

// 큐레이션 mutation(별표/메모/제외)은 FastAPI 가 Form 으로 받으므로
// application/x-www-form-urlencoded 로 보낸다(URLSearchParams 가 헤더 자동 설정).
export async function apiPostForm<T>(
  path: string,
  data?: Record<string, string>,
): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body: data ? new URLSearchParams(data) : undefined,
  })
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText} — ${path}`)
  }
  return (await res.json()) as T
}
