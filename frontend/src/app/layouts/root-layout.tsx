import { Outlet } from 'react-router-dom'

export function RootLayout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto max-w-7xl px-4 py-3">
          <h1 className="text-lg font-semibold">myhouse — 매물 모니터</h1>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
