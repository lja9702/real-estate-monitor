import { createBrowserRouter } from 'react-router-dom'
import { RootLayout } from './layouts/root-layout'
import { ListingsPage } from '@/pages/listings'
import { ComplexDetailPage } from '@/pages/complex-detail'
import { RunsPage } from '@/pages/runs'
import { ShortlistPage } from '@/pages/shortlist'
import { ComplexesPage } from '@/pages/complexes'
import { DealsPage } from '@/pages/deals'
import { PermitsPage } from '@/pages/permits'
import { AuctionsPage } from '@/pages/auctions'
import { FlashPage } from '@/pages/flash'
import { MapPage } from '@/pages/map'

// SPA 는 루트(/)에 마운트된다(단계 6 완료: /app→/ 승격) — basename 기본값('/').
export const router = createBrowserRouter([
  {
    path: '/',
    element: <RootLayout />,
    children: [
      { index: true, element: <ListingsPage /> },
      { path: 'complex/:no', element: <ComplexDetailPage /> },
      { path: 'runs', element: <RunsPage /> },
      { path: 'shortlist', element: <ShortlistPage /> },
      { path: 'complexes', element: <ComplexesPage /> },
      { path: 'deals', element: <DealsPage /> },
      { path: 'permits', element: <PermitsPage /> },
      { path: 'auctions', element: <AuctionsPage /> },
      { path: 'flash', element: <FlashPage /> },
      { path: 'map', element: <MapPage /> },
    ],
  },
])
