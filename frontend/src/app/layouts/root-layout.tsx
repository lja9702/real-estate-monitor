import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { apiGet, apiPostForm } from '@/shared/api/client'

type Me = { authenticated: boolean; role: string; readonly: boolean }

const NAV_LINKS: Array<{ to: string; label: string; end?: true }> = [
  { to: '/', label: '매물', end: true },
  { to: '/flash', label: '🔥 급매' },
  { to: '/deals', label: '실거래가' },
  { to: '/permits', label: '토지거래허가' },
  { to: '/auctions', label: '🔨 경매' },
  { to: '/shortlist', label: '★ 관심단지' },
  { to: '/map', label: '지도' },
  { to: '/complexes', label: '추적단지' },
  { to: '/runs', label: '실행로그' },
]

type RunRow = { status: string; kind: string; complexes_done: number; targets_count: number }

function RunButton({ label, endpoint, kind }: { label: string; endpoint: string; kind: string }) {
  const navigate = useNavigate()
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<{ fetched: number; total: number } | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPoll() {
    if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null }
  }

  function startPoll() {
    stopPoll()
    pollTimer.current = setInterval(() => {
      fetch('/api/runs')
        .then(r => r.json())
        .then((data: { runs: RunRow[] }) => {
          const active = data.runs.find(r => r.status === 'RUNNING' && r.kind === kind)
          if (active) {
            setProgress({ fetched: active.complexes_done, total: active.targets_count })
          } else {
            setRunning(false)
            setProgress(null)
            stopPoll()
          }
        })
        .catch(() => {})
    }, 2000)
  }

  useEffect(() => {
    fetch('/api/runs')
      .then(r => r.json())
      .then((data: { runs: RunRow[] }) => {
        const active = data.runs.find(r => r.status === 'RUNNING' && r.kind === kind)
        if (active) {
          setRunning(true)
          setProgress({ fetched: active.complexes_done, total: active.targets_count })
          startPoll()
        }
      })
      .catch(() => {})
    return stopPoll
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind])

  async function trigger() {
    if (running) return
    setRunning(true)
    setProgress(null)
    try {
      await apiPostForm(endpoint)
      startPoll()
      timer.current = setTimeout(() => { void navigate('/runs') }, 1800)
    } catch {
      setRunning(false)
      stopPoll()
    }
  }

  async function cancel() {
    if (timer.current) { clearTimeout(timer.current); timer.current = null }
    stopPoll()
    try {
      await apiPostForm('/run-cancel')
    } catch { /* 취소 오류는 무시 */ }
    setRunning(false)
    setProgress(null)
  }

  const progressLabel =
    progress && progress.total > 0
      ? `단지 ${progress.fetched} / ${progress.total}`
      : '시작됨…'

  return (
    <span className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => { void trigger() }}
        disabled={running}
        className="h-7 rounded border px-2.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
      >
        {running ? progressLabel : label}
      </button>
      {running && (
        <button
          type="button"
          onClick={() => { void cancel() }}
          className="h-7 rounded border border-destructive/40 px-2 text-xs text-destructive hover:bg-destructive/10"
        >
          취소
        </button>
      )}
    </span>
  )
}

export function RootLayout() {
  const me = useQuery({ queryKey: ['me'], queryFn: () => apiGet<Me>('/api/me') })
  // 수집 버튼은 쓰기 가능한 서버(readonly 아님) + 운영자(admin)/로컬에서만 노출.
  // 클라우드(읽기전용)에선 전원 숨김, 지인(member)에게도 숨김.
  const canCollect =
    !!me.data && !me.data.readonly && (me.data.role === 'admin' || me.data.role === 'local')

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-3 px-4">
          {/* 브랜드 — 클릭하면 매물(인덱스) 페이지로 */}
          <Link
            to="/"
            className="shrink-0 text-sm font-semibold transition-opacity hover:opacity-70"
          >
            myhouse
          </Link>

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

          {/* 수집 버튼 — 운영자(admin)/로컬 + 쓰기 가능 서버에서만 노출 */}
          {canCollect && (
            <div className="ml-auto flex shrink-0 items-center gap-1.5">
              <RunButton label="지금 수집" endpoint="/run" kind="listings" />
              <RunButton label="실거래 수집" endpoint="/run-deals" kind="deals" />
              <RunButton label="허가 수집" endpoint="/run-permits" kind="permits" />
              <RunButton label="경매 수집" endpoint="/run-auctions" kind="auctions" />
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
