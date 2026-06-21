import { Button } from '@/components/ui/button'

// 단계 1 플레이스홀더 — 매물 필터(듀얼 슬라이더)·테이블은 단계 3 에서 구현한다.
export function ListingsPage() {
  return (
    <div className="space-y-4">
      <p className="text-muted-foreground">
        React SPA 셸이 동작합니다. 매물 필터·테이블은 단계 3 에서 구현됩니다.
      </p>
      <Button>shadcn 버튼 (Tailwind v4 스타일 확인)</Button>
    </div>
  )
}
