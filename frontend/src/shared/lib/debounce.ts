// 간단한 디바운스 — 검색어 입력 등 잦은 이벤트를 늦춰 URL/쿼리 갱신을 줄인다.
export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): (...args: A) => void {
  let t: ReturnType<typeof setTimeout> | undefined
  return (...args: A) => {
    if (t) clearTimeout(t)
    t = setTimeout(() => fn(...args), ms)
  }
}
