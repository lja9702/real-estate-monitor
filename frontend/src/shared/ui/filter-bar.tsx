import { useState, type ReactNode } from 'react'
import { ChevronDownIcon, SlidersHorizontalIcon } from 'lucide-react'

/**
 * 헤더(h-14) 아래에 sticky 고정되는 필터 바.
 * - 데스크탑(md+): 필터를 항상 펼쳐 보여주고, 하단에 결과 수 표시.
 * - 모바일: 기본 접힘. '필터' 토글 버튼 + 결과 수만 항상 보이고, 탭하면 펼친다.
 *
 * `count` 는 결과 수 등 요약 노드(양쪽 뷰에서 공유), `children` 은 필터 컨트롤.
 */
export function FilterBar({
  count,
  children,
}: {
  count: ReactNode
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="sticky top-14 z-20 -mx-4 border-b bg-background/95 px-4 pt-3 pb-2 backdrop-blur supports-[backdrop-filter]:bg-background/75">
      {/* 모바일 토글 바 — 항상 보임 */}
      <div className="flex items-center justify-between gap-3 md:hidden">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium"
        >
          <SlidersHorizontalIcon className="size-4" />
          필터
          <ChevronDownIcon
            className={`size-4 transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </button>
        <div className="min-w-0 truncate text-sm text-muted-foreground">{count}</div>
      </div>

      {/* 필터 컨트롤 — 모바일은 토글, 데스크탑은 항상 표시 */}
      <div className={open ? 'mt-3 md:mt-0' : 'hidden md:block'}>{children}</div>

      {/* 결과 수 — 데스크탑에서만(모바일은 토글 바에 표시) */}
      <div className="mt-2 hidden items-center gap-3 border-t pt-2 text-sm text-muted-foreground md:flex">
        {count}
      </div>
    </div>
  )
}
