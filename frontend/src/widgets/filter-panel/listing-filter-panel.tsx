import { useEffect, useMemo, useState } from 'react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { RangeSlider, MinSlider } from '@/shared/ui/range-slider'
import { formatManwon, formatArea } from '@/shared/lib/format'
import { debounce } from '@/shared/lib/debounce'
import {
  SLIDER_STEP,
  SORT_OPTIONS,
  STATUS_OPTIONS,
  TRADE_TYPES,
} from '@/shared/config/constants'
import type {
  ComplexOption,
  FilterDomains,
  ListingFilters,
} from '@/entities/listing/model/types'

// radix Select 는 빈 문자열 value 를 허용하지 않으므로 '전체'에 센티넬을 쓴다.
const ALL = '__all__'

interface SelectOption {
  value: string
  label: string
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  disabled,
  className,
}: {
  label: string
  value: string
  options: readonly SelectOption[]
  onChange: (v: string) => void
  disabled?: boolean
  className?: string
}) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      <Select
        value={value || ALL}
        onValueChange={(v) => onChange(v === ALL ? '' : v)}
        disabled={disabled}
      >
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value || ALL} value={o.value || ALL}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

interface Props {
  domains: FilterDomains
  filters: ListingFilters
  setFilters: (patch: Partial<ListingFilters>) => void
  reset: () => void
  complexes: ComplexOption[]
  guDongMap: Record<string, string[]>
}

export function ListingFilterPanel({
  domains,
  filters,
  setFilters,
  reset,
  complexes,
  guDongMap,
}: Props) {
  // 면적 도메인은 실수라 슬라이더(step 1)용으로 정수 경계로 변환.
  const areaMin = Math.floor(domains.area_min)
  const areaMax = Math.max(areaMin + 1, Math.ceil(domains.area_max))

  const guOptions: SelectOption[] = useMemo(
    () => [
      { value: '', label: '전체' },
      ...Object.keys(guDongMap).map((g) => ({ value: g, label: g })),
    ],
    [guDongMap],
  )
  const dongOptions: SelectOption[] = useMemo(
    () => [
      { value: '', label: '전체' },
      ...(guDongMap[filters.gu] ?? []).map((d) => ({ value: d, label: d })),
    ],
    [guDongMap, filters.gu],
  )
  const complexOptions: SelectOption[] = useMemo(
    () => [
      { value: '', label: '전체 단지' },
      ...complexes.map((c) => ({ value: c.complex_no, label: c.name })),
    ],
    [complexes],
  )

  // 검색어는 디바운스로 URL 갱신(타이핑마다 refetch 방지). 로컬 입력 상태 유지.
  const [q, setQ] = useState(filters.q)
  useEffect(() => setQ(filters.q), [filters.q])
  const commitQ = useMemo(
    () => debounce((v: string) => setFilters({ q: v }), 350),
    [setFilters],
  )

  // 슬라이더 값: 필터가 null 이면 도메인 경계(=무제한)로 표시.
  const priceValue: [number, number] = [
    filters.price_min ?? domains.price_min,
    filters.price_max ?? domains.price_max,
  ]
  const areaValue: [number, number] = [
    filters.area_min ?? areaMin,
    filters.area_max ?? areaMax,
  ]
  const householdsValue: [number, number] = [
    filters.households_min ?? domains.households_min,
    filters.households_max ?? domains.households_max,
  ]
  const yearValue: [number, number] = [
    filters.year_min ?? domains.year_min,
    filters.year_max ?? domains.year_max,
  ]

  return (
    <div className="space-y-3">
      {/* 컴팩트 컨트롤 — 셀렉트·검색·정렬·토글·초기화 (좁으면 자동 줄바꿈) */}
      <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
        <FilterSelect
          label="거래유형"
          value={filters.trade_type}
          options={TRADE_TYPES}
          onChange={(v) => setFilters({ trade_type: v })}
          className="w-24"
        />
        <FilterSelect
          label="상태"
          value={filters.status}
          options={STATUS_OPTIONS}
          onChange={(v) => setFilters({ status: v })}
          className="w-24"
        />
        <FilterSelect
          label="구"
          value={filters.gu}
          options={guOptions}
          onChange={(v) => setFilters({ gu: v, dong: '' })}
          className="w-28"
        />
        <FilterSelect
          label="동"
          value={filters.dong}
          options={dongOptions}
          onChange={(v) => setFilters({ dong: v })}
          disabled={!filters.gu}
          className="w-28"
        />
        <FilterSelect
          label="단지"
          value={filters.complex_no}
          options={complexOptions}
          onChange={(v) => setFilters({ complex_no: v })}
          className="w-44"
        />
        <div className="w-52 space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">검색</label>
          <Input
            placeholder="단지명·향·특징…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              commitQ(e.target.value)
            }}
          />
        </div>
        <FilterSelect
          label="정렬"
          value={filters.sort}
          options={SORT_OPTIONS}
          onChange={(v) => setFilters({ sort: v })}
          className="w-28"
        />
        <div className="flex items-center gap-3 pb-2">
          <label className="flex items-center gap-1.5 text-sm whitespace-nowrap">
            <Checkbox
              checked={filters.starred_only}
              onCheckedChange={(c) => setFilters({ starred_only: c === true })}
            />
            관심만
          </label>
          <label className="flex items-center gap-1.5 text-sm whitespace-nowrap">
            <Checkbox
              checked={filters.show_excluded}
              onCheckedChange={(c) => setFilters({ show_excluded: c === true })}
            />
            제외 포함
          </label>
        </div>
        <Button variant="outline" size="sm" className="mb-0.5" onClick={reset}>
          초기화
        </Button>
      </div>

      {/* 슬라이더 — 가격·전용·세대수·준공·층 (넓으면 한 줄, 좁으면 줄바꿈) */}
      <div className="grid grid-cols-1 gap-x-6 gap-y-3 border-t pt-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <RangeSlider
          label="가격"
          min={domains.price_min}
          max={domains.price_max}
          step={SLIDER_STEP.price}
          value={priceValue}
          format={formatManwon}
          onCommit={([lo, hi]) =>
            setFilters({
              price_min: lo <= domains.price_min ? null : lo,
              price_max: hi >= domains.price_max ? null : hi,
            })
          }
        />
        <RangeSlider
          label="전용면적"
          min={areaMin}
          max={areaMax}
          step={SLIDER_STEP.area}
          value={areaValue}
          format={formatArea}
          onCommit={([lo, hi]) =>
            setFilters({
              area_min: lo <= areaMin ? null : lo,
              area_max: hi >= areaMax ? null : hi,
            })
          }
        />
        <RangeSlider
          label="세대수"
          min={domains.households_min}
          max={domains.households_max}
          step={SLIDER_STEP.households}
          value={householdsValue}
          format={(n) => `${n.toLocaleString('ko-KR')}세대`}
          onCommit={([lo, hi]) =>
            setFilters({
              households_min: lo <= domains.households_min ? null : lo,
              households_max: hi >= domains.households_max ? null : hi,
            })
          }
        />
        <RangeSlider
          label="준공연도"
          min={domains.year_min}
          max={domains.year_max}
          step={SLIDER_STEP.year}
          value={yearValue}
          format={(n) => `${n}년`}
          onCommit={([lo, hi]) =>
            setFilters({
              year_min: lo <= domains.year_min ? null : lo,
              year_max: hi >= domains.year_max ? null : hi,
            })
          }
        />
        <MinSlider
          label="최소 층"
          min={1}
          max={Math.max(2, domains.floor_max)}
          step={SLIDER_STEP.floor}
          value={filters.floor_min ?? 1}
          format={(n) => `${n}층`}
          onCommit={(v) => setFilters({ floor_min: v <= 1 ? null : v })}
        />
      </div>
    </div>
  )
}
