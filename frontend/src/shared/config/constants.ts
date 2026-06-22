// 슬라이더 step — HANDOFF 기준.
export const SLIDER_STEP = {
  price: 1000, // 만원 단위 (= 천만원)
  area: 1, // ㎡
  households: 50, // 세대
  year: 1, // 년
  floor: 1, // 층 (하한 단일 슬라이더)
} as const

// 거래유형 옵션 (백엔드 TradeType enum 값).
export const TRADE_TYPES = [
  { value: '', label: '전체' },
  { value: 'SALE', label: '매매' },
  { value: 'JEONSE', label: '전세' },
  { value: 'WOLSE', label: '월세' },
] as const

// 정렬 옵션 (백엔드 _sort_area_rows 지원값).
export const SORT_OPTIONS = [
  { value: 'new', label: '신규순' },
  { value: 'price_asc', label: '가격 낮은순' },
  { value: 'price_desc', label: '가격 높은순' },
  { value: 'area_desc', label: '면적 넓은순' },
] as const

// 상태 필터 옵션 (백엔드 Filters.status).
export const STATUS_OPTIONS = [
  { value: 'active', label: '활성' },
  { value: 'new', label: '신규' },
  { value: 'removed', label: '거래완료' },
  { value: 'all', label: '전체' },
] as const
