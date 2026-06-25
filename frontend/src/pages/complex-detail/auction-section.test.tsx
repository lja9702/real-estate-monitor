import type { ReactElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuctionSection } from './index'
import type { AuctionRow } from '@/entities/auction/model/types'

// AuctionSection 은 상세 다이얼로그(useQuery)를 품으므로 QueryClient 컨텍스트가 필요하다.
function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function auction(over: Partial<AuctionRow>): AuctionRow {
  return {
    auction_key: 'k',
    complex_no: '122025',
    complex_name: '테스트단지',
    address_short: null,
    address: '하남시 감이동 500',
    case_no: '2024타경71157',
    court_name: '성남지원',
    appraisal_manwon: 131000,
    min_bid_manwon: 64190,
    min_bid_ratio: 49,
    fail_count: 2,
    sale_date: '2026-09-01',
    status_code: '01',
    in_progress: true,
    court_url: 'https://www.courtauction.go.kr/case',
    remarks: null,
    flags: [],
    outcome: null,
    outcome_label: null,
    final_bid_manwon: null,
    outcome_date: null,
    is_new: false,
    starred: false,
    ...over,
  }
}

describe('AuctionSection', () => {
  // todayLocal() 이 new Date() 를 쓰므로 기준일을 2026-06-22 로 고정.
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 5, 22))
  })
  afterEach(() => vi.useRealTimers())

  it('경매가 없으면 빈 상태를 보여준다', () => {
    renderWithClient(<AuctionSection auctions={[]} />)
    expect(screen.getByText('경매 (0건)')).toBeInTheDocument()
    expect(screen.getByText('경매 내역 없음')).toBeInTheDocument()
  })

  it('매각기일 기준으로 진행중/지난 경매를 나눠 렌더한다', () => {
    const future = auction({ auction_key: 'F', case_no: '2024타경100', sale_date: '2026-09-01', is_new: true })
    const past = auction({ auction_key: 'P', case_no: '2024타경200', sale_date: '2026-03-01', is_new: false })
    renderWithClient(<AuctionSection auctions={[future, past]} />)

    expect(screen.getByText('경매 (2건)')).toBeInTheDocument()
    expect(screen.getByText('진행중 (1건)')).toBeInTheDocument()
    // '지난 경매' 헤더는 보관기간 표기를 포함한다.
    expect(screen.getByText(/지난 경매 \(1건/)).toBeInTheDocument()

    // 진행중 행에는 사건번호 100·신규 배지, 지난 행에는 사건번호 200.
    expect(screen.getByText(/2024타경100/)).toBeInTheDocument()
    expect(screen.getByText('신규')).toBeInTheDocument()
    expect(screen.getByText(/2024타경200/)).toBeInTheDocument()

    // 사건 링크는 법원경매 공식 URL.
    const link = screen.getByText(/2024타경200/).closest('a')
    expect(link).toHaveAttribute('href', 'https://www.courtauction.go.kr/case')
  })

  it('매각기일이 없는 물건은 진행중으로 분류한다', () => {
    const nodate = auction({ auction_key: 'N', sale_date: null })
    renderWithClient(<AuctionSection auctions={[nodate]} />)
    const ongoing = screen.getByText('진행중 (1건)').closest('div')!
    expect(within(ongoing).getByText(/2024타경71157/)).toBeInTheDocument()
    expect(screen.queryByText(/지난 경매/)).not.toBeInTheDocument()
  })

  it('물건비고 위험 플래그(지분매각 등)를 배지로 보여준다', () => {
    const risky = auction({
      auction_key: 'R', flags: ['지분매각', '위반건축물'], remarks: '지분 매각임...',
    })
    renderWithClient(<AuctionSection auctions={[risky]} />)
    expect(screen.getByText('지분매각')).toBeInTheDocument()
    expect(screen.getByText('위반건축물')).toBeInTheDocument()
  })

  it('매각된 지난 경매는 낙찰가 배지를 보여준다', () => {
    const sold = auction({
      auction_key: 'S', case_no: '2025타경1678', sale_date: '2026-05-19',
      outcome: 'sold', outcome_label: '매각', final_bid_manwon: 223652,
    })
    renderWithClient(<AuctionSection auctions={[sold]} />)
    expect(screen.getByText(/지난 경매 \(1건/)).toBeInTheDocument()
    expect(screen.getByText(/매각 22/)).toBeInTheDocument() // 낙찰가 배지(22.4억 등)
  })
})
