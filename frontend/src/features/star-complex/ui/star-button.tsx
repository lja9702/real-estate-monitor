import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toggleStar } from '../api/toggle-star'

// ★/☆ 토글 버튼 — 클릭 즉시 낙관적으로 뒤집고, 응답으로 확정. 실패 시 되돌린다.
// 전체 목록 refetch 없이 버튼만 갱신(기존 Jinja JS 동작과 동일).
export function StarButton({
  complexNo,
  starred,
}: {
  complexNo: string
  starred: boolean
}) {
  const [on, setOn] = useState(starred)
  useEffect(() => setOn(starred), [starred])

  const m = useMutation({
    mutationFn: () => toggleStar(complexNo),
    onSuccess: (res) => setOn(res.starred),
    onError: () => setOn((v) => !v), // 낙관적 변경 되돌리기
  })

  return (
    <button
      type="button"
      title="관심 단지"
      aria-pressed={on}
      disabled={m.isPending}
      className={
        'text-base leading-none transition-colors ' +
        (on ? 'text-amber-500' : 'text-muted-foreground/40 hover:text-amber-400')
      }
      onClick={() => {
        setOn((v) => !v)
        m.mutate()
      }}
    >
      {on ? '★' : '☆'}
    </button>
  )
}
