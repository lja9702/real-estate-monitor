import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoInput } from './memo-input'
import { saveMemo } from '../api/save-memo'

vi.mock('../api/save-memo', () => ({
  saveMemo: vi.fn(() => Promise.resolve({ cluster_key: 'ck', memo: '' })),
}))

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('MemoInput', () => {
  beforeEach(() => vi.clearAllMocks())

  it('변경 후 blur 시 저장한다', async () => {
    const user = userEvent.setup()
    renderWithClient(<MemoInput clusterKey="ck1" complexNo="111" memo={null} />)
    const input = screen.getByPlaceholderText('메모…')
    await user.type(input, '남향 좋음')
    await user.tab()
    expect(saveMemo).toHaveBeenCalledWith('ck1', '남향 좋음', '111')
  })

  it('변경이 없으면 저장하지 않는다', async () => {
    const user = userEvent.setup()
    renderWithClient(<MemoInput clusterKey="ck1" complexNo="111" memo="기존" />)
    const input = screen.getByPlaceholderText('메모…')
    await user.click(input)
    await user.tab()
    expect(saveMemo).not.toHaveBeenCalled()
  })

  it('저장 후 같은 세션에서 비우면 빈 메모를 저장한다 (stale prop 회귀)', async () => {
    const user = userEvent.setup()
    renderWithClient(<MemoInput clusterKey="ck1" complexNo="111" memo={null} />)
    const input = screen.getByPlaceholderText('메모…')

    await user.type(input, 'A')
    await user.tab()
    await waitFor(() => expect(saveMemo).toHaveBeenLastCalledWith('ck1', 'A', '111'))

    await user.click(input)
    await user.clear(input)
    await user.tab()
    await waitFor(() => expect(saveMemo).toHaveBeenLastCalledWith('ck1', '', '111'))
  })
})
