import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Input } from '@/components/ui/input'
import { saveMemo } from '../api/save-memo'

// 메모 인라인 편집 — blur 시점에 마지막 저장값과 다르면 저장(기존 Jinja onblur 동작).
// 저장 후 목록을 refetch 하지 않으므로 비교 기준은 prop(memo) 이 아니라 'saved' state 다.
// (그렇지 않으면 저장 → 같은 세션에서 비우기 시 stale prop 과 비교돼 빈 저장이 누락된다.)
export function MemoInput({
  clusterKey,
  complexNo,
  memo,
}: {
  clusterKey: string
  complexNo: string
  memo: string | null
}) {
  const [value, setValue] = useState(memo ?? '')
  const [saved, setSaved] = useState(memo ?? '')
  useEffect(() => {
    setValue(memo ?? '')
    setSaved(memo ?? '')
  }, [memo])

  const m = useMutation({
    mutationFn: (v: string) => saveMemo(clusterKey, v, complexNo),
    onSuccess: (_res, v) => setSaved(v),
  })

  return (
    <Input
      className="h-8 min-w-32"
      placeholder="메모…"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => {
        if (value !== saved) m.mutate(value)
      }}
    />
  )
}
