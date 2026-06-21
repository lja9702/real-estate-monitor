import { createBrowserRouter } from 'react-router-dom'
import { RootLayout } from './layouts/root-layout'
import { ListingsPage } from '@/pages/listings'

// SPA 는 /app/ 에 마운트되므로 basename 으로 라우터 베이스를 맞춘다(vite base 와 동일).
export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <RootLayout />,
      children: [{ index: true, element: <ListingsPage /> }],
    },
  ],
  { basename: '/app' },
)
