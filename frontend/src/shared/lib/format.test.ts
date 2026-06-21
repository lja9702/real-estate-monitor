import { describe, expect, it } from 'vitest'
import { approveYear, formatArea, formatManwon, formatPriceRange } from './format'

describe('formatManwon', () => {
  it('억+만원 혼합', () => {
    expect(formatManwon(158000)).toBe('15억8,000')
  })
  it('억 단위 딱 떨어짐', () => {
    expect(formatManwon(90000)).toBe('9억')
  })
  it('억 미만', () => {
    expect(formatManwon(5000)).toBe('5,000')
  })
  it('null/undefined 은 대시', () => {
    expect(formatManwon(null)).toBe('-')
    expect(formatManwon(undefined)).toBe('-')
  })
  it('음수', () => {
    expect(formatManwon(-90000)).toBe('-9억')
  })
})

describe('formatPriceRange', () => {
  it('동일 값은 단일 표기', () => {
    expect(formatPriceRange(90000, 90000)).toBe('9억')
  })
  it('범위 표기', () => {
    expect(formatPriceRange(90000, 158000)).toBe('9억 ~ 15억8,000')
  })
  it('한쪽만 있으면 그 값', () => {
    expect(formatPriceRange(90000, null)).toBe('9억')
    expect(formatPriceRange(null, null)).toBe('-')
  })
})

describe('formatArea', () => {
  it('정수면 정수 ㎡', () => {
    expect(formatArea(84)).toBe('84㎡')
  })
  it('소수는 1자리', () => {
    expect(formatArea(84.97)).toBe('85.0㎡')
  })
  it('null 은 대시', () => {
    expect(formatArea(null)).toBe('-')
  })
})

describe('approveYear', () => {
  it('YYYYMMDD → 연도', () => {
    expect(approveYear('19751128')).toBe(1975)
  })
  it('빈값은 null', () => {
    expect(approveYear(null)).toBe(null)
    expect(approveYear('')).toBe(null)
  })
})
