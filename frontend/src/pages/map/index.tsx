import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { mapKeys, getMapData, getMapConfig } from '@/entities/map/api/get-map-data'
import { formatPriceRange } from '@/shared/lib/format'

// 모듈 레벨 싱글턴 — 컴포넌트 언마운트 후 재마운트 시 SDK를 재로드하지 않는다.
let _sdkLoad: Promise<void> | null = null

function loadNaverSDK(clientId: string): Promise<void> {
  if (_sdkLoad) return _sdkLoad
  _sdkLoad = new Promise((resolve, reject) => {
    if (window.naver?.maps) { resolve(); return }
    const s = document.createElement('script')
    s.src = `https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=${encodeURIComponent(clientId)}`
    s.onload = () => resolve()
    s.onerror = () => { _sdkLoad = null; reject(new Error('Naver Maps SDK 로드 실패')) }
    document.head.appendChild(s)
  })
  return _sdkLoad
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function markerColor(count: number): string {
  if (count === 0) return '#aaa'
  if (count <= 2) return '#4fa3e0'
  return '#2ecc71'
}

const TRADE_TYPES = ['매매', '전세', '월세'] as const
type TradeType = (typeof TRADE_TYPES)[number]

// 지도 페이지 — 레이아웃 패딩을 벗어나 뷰포트를 꽉 채운다.
// header height = h-14 = 3.5rem, main의 py-6(-mt-6)을 상쇄한다.
export function MapPage() {
  const configQuery = useQuery({ queryKey: mapKeys.config(), queryFn: getMapConfig })
  const dataQuery = useQuery({ queryKey: mapKeys.data(), queryFn: getMapData })

  const mapEl = useRef<HTMLDivElement>(null)
  const mapObj = useRef<object | null>(null)
  const markersRef = useRef<NaverMarker[]>([])
  const iwRef = useRef<NaverInfoWindow | null>(null)

  const [sdkReady, setSdkReady] = useState(false)
  const [sdkError, setSdkError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Set<TradeType>>(new Set(TRADE_TYPES))
  const [visibleCount, setVisibleCount] = useState(0)

  const clientId = configQuery.data?.naver_map_client_id ?? null

  // SDK 로드 — clientId 확정 후 1회
  useEffect(() => {
    if (!clientId) return
    loadNaverSDK(clientId)
      .then(() => setSdkReady(true))
      .catch((e: unknown) => setSdkError(String(e)))
  }, [clientId])

  // 지도 + 마커 초기화
  useEffect(() => {
    const data = dataQuery.data
    if (!sdkReady || !data || !mapEl.current) return

    const nm = window.naver!.maps

    if (!data.length) {
      setVisibleCount(0)
      return
    }

    const centerLat = data.reduce((s, d) => s + d.lat, 0) / data.length
    const centerLon = data.reduce((s, d) => s + d.lon, 0) / data.length

    const map = new nm.Map(mapEl.current, {
      zoom: 12,
      center: new nm.LatLng(centerLat, centerLon),
    })
    mapObj.current = map

    const iw = new nm.InfoWindow({ anchorSkew: true })
    iwRef.current = iw

    nm.Event.addListener(map, 'click', () => iw.close())
    window.__mapClose = () => iw.close()

    markersRef.current = data.map(d => {
      const color = markerColor(d.active_count)
      const m = new nm.Marker({
        position: new nm.LatLng(d.lat, d.lon),
        map,
        icon: {
          content: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`,
          anchor: new nm.Point(7, 7),
        },
        title: d.name,
      })

      nm.Event.addListener(m as unknown as object, 'click', () => {
        const trades = d.trade_types.join(', ') || '—'
        const newBadge = d.new_count
          ? ` <span style="color:#e74c3c;font-size:.8em">(신규 ${d.new_count})</span>`
          : ''
        const priceStr = formatPriceRange(d.min_price, d.max_price)

        iw.setContent(`
          <div style="position:relative;padding:12px 30px 10px 14px;min-width:170px;font-size:.9em;line-height:1.6">
            <a href="javascript:void(0)" onclick="window.__mapClose&&window.__mapClose()"
               style="position:absolute;top:6px;right:8px;color:#bbb;font-size:1.15em;font-weight:bold;text-decoration:none;line-height:1">✕</a>
            <a href="https://new.land.naver.com/complexes/${esc(d.complex_no)}" target="_blank" rel="noopener"
               style="font-weight:bold;color:#03c75a;text-decoration:none">${esc(d.name)} ↗</a><br>
            ${d.meta_line ? `<span style="color:#aaa;font-size:.8em">${esc(d.meta_line)}</span><br>` : ''}
            <span style="color:#888">${esc(trades)}</span><br>
            활성 매물: <b>${d.active_count}건</b>${newBadge}<br>
            가격: ${priceStr}<br>
            <a href="/app/complex/${esc(d.complex_no)}" style="font-size:.85em;color:#4fa3e0">단지 보기 →</a>
          </div>`)
        iw.open(map, m as unknown as object)
      })

      return m
    })

    setVisibleCount(data.length)

    return () => {
      markersRef.current.forEach(m => m.setMap(null))
      markersRef.current = []
      iw.close()
      mapObj.current = null
      iwRef.current = null
      delete window.__mapClose
    }
  }, [sdkReady, dataQuery.data])

  // 필터 적용
  useEffect(() => {
    const data = dataQuery.data
    if (!data || !markersRef.current.length) return
    let visible = 0
    data.forEach((d, i) => {
      const m = markersRef.current[i]
      if (!m) return
      const show = d.trade_types.length === 0 || d.trade_types.some(t => filter.has(t as TradeType))
      m.setVisible(show)
      if (show) visible++
    })
    setVisibleCount(visible)
  }, [filter, dataQuery.data])

  function toggleFilter(t: TradeType) {
    setFilter(prev => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })
  }

  return (
    // 레이아웃의 px-4 py-6을 상쇄하고 헤더(h-14=3.5rem) 아래를 꽉 채운다.
    <div className="-mx-4 -mt-6 relative" style={{ height: 'calc(100vh - 3.5rem)' }}>

      {/* API 키 미설정 */}
      {configQuery.data && !clientId && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80">
          <div className="rounded-lg border bg-amber-50 p-8 text-center dark:bg-amber-950">
            <p className="font-semibold">⚠️ 네이버 지도 API 키 미설정</p>
            <p className="mt-2 text-sm text-muted-foreground">
              <code>.env</code>에 <code>NAVER_MAP_CLIENT_ID=...</code>를 추가하고
              서버를 재시작하세요.
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              NCP 발급: console.ncloud.com → Application → Maps API
            </p>
          </div>
        </div>
      )}

      {/* SDK 로드 오류 */}
      {sdkError && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80">
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-8 text-center">
            <p className="text-sm text-destructive">지도 SDK 로드 실패: {sdkError}</p>
          </div>
        </div>
      )}

      {/* 좌표 단지 없음 */}
      {sdkReady && dataQuery.data?.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80">
          <div className="rounded-lg border bg-muted p-8 text-center text-sm text-muted-foreground">
            좌표가 설정된 단지가 없습니다.<br />
            <span className="text-xs">수집 실행 시 자동으로 채워지거나<br /><code>myhouse fill-coords</code>를 실행하세요.</span>
          </div>
        </div>
      )}

      {/* 불러오는 중 */}
      {configQuery.isPending && (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="text-sm text-muted-foreground">불러오는 중…</p>
        </div>
      )}

      {/* config API 오류 (서버 미재시작 등) */}
      {configQuery.isError && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80">
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-8 text-center">
            <p className="font-semibold text-destructive">설정 로드 실패</p>
            <p className="mt-1 text-sm text-muted-foreground">
              서버를 재시작한 뒤 새로고침하세요.
            </p>
          </div>
        </div>
      )}

      {/* 필터 패널 */}
      {sdkReady && !!dataQuery.data?.length && (
        <div className="absolute left-3 top-3 z-10 flex items-center gap-3 rounded-lg border bg-background/95 px-3 py-2 text-sm shadow-md backdrop-blur supports-[backdrop-filter]:bg-background/75">
          {TRADE_TYPES.map(t => (
            <label key={t} className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={filter.has(t)}
                onChange={() => toggleFilter(t)}
                className="accent-primary"
              />
              {t}
            </label>
          ))}
          <span className="border-l pl-3 text-muted-foreground">{visibleCount}개 단지</span>
        </div>
      )}

      {/* 범례 */}
      {sdkReady && !!dataQuery.data?.length && (
        <div className="absolute bottom-7 left-3 z-10 flex flex-col gap-1 rounded-lg border bg-background/95 px-3 py-2 text-xs shadow-md backdrop-blur supports-[backdrop-filter]:bg-background/75">
          {[
            { color: '#2ecc71', label: '매물 3건+' },
            { color: '#4fa3e0', label: '매물 1–2건' },
            { color: '#aaa', label: '매물 없음' },
          ].map(({ color, label }) => (
            <div key={label} className="flex items-center gap-1.5">
              <div
                className="h-3 w-3 shrink-0 rounded-full border-2 border-white shadow-sm"
                style={{ background: color }}
              />
              {label}
            </div>
          ))}
        </div>
      )}

      {/* 지도 컨테이너 */}
      <div ref={mapEl} className="h-full w-full" />
    </div>
  )
}
