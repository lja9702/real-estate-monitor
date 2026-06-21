import { Outlet } from 'react-router-dom'

export function RootLayout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* 스크롤해도 늘 보이도록 sticky. 필터 바(top-14)가 이 헤더 바로 아래에 붙는다. */}
      <header className="sticky top-0 z-30 flex h-14 items-center border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        <div className="mx-auto w-full max-w-7xl px-4">
          <h1 className="text-lg font-semibold">myhouse — 매물 모니터</h1>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
