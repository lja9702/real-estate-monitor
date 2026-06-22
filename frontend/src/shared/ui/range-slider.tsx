import { useEffect, useState } from 'react'
import { Slider } from '@/components/ui/slider'

interface RangeSliderProps {
  label: string
  min: number
  max: number
  step: number
  value: [number, number]
  onCommit: (value: [number, number]) => void
  format?: (n: number) => string
}

// 듀얼핸들 슬라이더 — 드래그 중에는 로컬 state 로 라벨을 즉시 갱신하고,
// 핸들을 놓을 때(onValueCommit) 한 번만 상위로 커밋한다(→ URL → 쿼리 refetch).
export function RangeSlider({
  label, min, max, step, value, onCommit, format,
}: RangeSliderProps) {
  const [local, setLocal] = useState<[number, number]>(value)

  // 외부 value(도메인 로드·리셋)가 실제로 바뀌면 로컬 동기화. 드래그 중엔 value 가
  // 안 바뀌므로(커밋은 릴리즈 시점) 드래그 상태를 덮어쓰지 않는다.
  useEffect(() => {
    setLocal(value)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value[0], value[1]])

  const fmt = format ?? ((n: number) => String(n))

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground tabular-nums">
          {fmt(local[0])} ~ {fmt(local[1])}
        </span>
      </div>
      <Slider
        min={min}
        max={max}
        step={step}
        value={local}
        onValueChange={(v) => setLocal([v[0], v[1]])}
        onValueCommit={(v) => onCommit([v[0], v[1]])}
      />
    </div>
  )
}

interface MinSliderProps {
  label: string
  min: number
  max: number
  step: number
  value: number
  onCommit: (value: number) => void
  format?: (n: number) => string
}

// 하한 단일 슬라이더 — 층(floor_min)처럼 '이상' 조건만 거는 필터용.
export function MinSlider({
  label, min, max, step, value, onCommit, format,
}: MinSliderProps) {
  const [local, setLocal] = useState<number>(value)

  useEffect(() => {
    setLocal(value)
  }, [value])

  const fmt = format ?? ((n: number) => String(n))

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground tabular-nums">{fmt(local)} 이상</span>
      </div>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[local]}
        onValueChange={(v) => setLocal(v[0])}
        onValueCommit={(v) => onCommit(v[0])}
      />
    </div>
  )
}
