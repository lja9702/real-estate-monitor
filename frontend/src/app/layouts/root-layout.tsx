import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { apiPostForm } from '@/shared/api/client'

const NAV_LINKS: Array<{ to: string; label: string; end?: true }> = [
  { to: '/', label: '매물', end: true },
  { to: '/deals', label: '실거래가' },
  { to: '/permits', label: '토지거래허가' },
  { to: '/shortlist', label: '★ 관심단지' },
  { to: '/map', label: '지도' },
  { to: '/complexes', label: '추적단지' },
  { to: '/runs', label: '실행로그' },
]

function RunButton({ label, endpoint }: { label: string; endpoint: string }) {
  const navigate = useNavigate()
  const [running, setRunning] = useState(false)

  async function trigger() {
    if (running) return
    setRunning(true)
    try {
      await apiPostForm(endpoint)
      setTimeout(() => { void navigate('/runs') }, 1800)
    } catch {
      setRunning(false)
    }
  }

  return (
    <button
      type="button"
      onClick={() => { void trigger() }}
      disabled={running}
      className="h-7 rounded border px-2.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
    >
      {running ? '시작됨…' : label}
    </button>
  )
}

export function RootLayout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-3 px-4">
          {/* 브랜드 */}
          <span className="shrink-0 text-sm font-semibold">myhouse</span>

          {/* 페이지 네비 */}
          <nav className="flex min-w-0 items-center gap-0.5 overflow-x-auto">
            {NAV_LINKS.map(({ to, label, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded px-2.5 py-1 text-sm transition-colors ${
                    isActive
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>

          {/* 수집 버튼 */}
          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            <RunButton label="지금 수집" endpoint="/run" />
            <RunButton label="실거래 수집" endpoint="/run-deals" />
            <RunButton label="허가 수집" endpoint="/run-permits" />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
