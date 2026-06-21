// 최소 fetch 래퍼 — SPA(/app)와 API(/api)는 동일 오리진이라 절대경로로 호출한다.
// dev(5173)에서는 vite proxy 가 /api 를 FastAPI(8765)로 넘긴다.
export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText} — ${path}`)
  }
  return (await res.json()) as T
}
