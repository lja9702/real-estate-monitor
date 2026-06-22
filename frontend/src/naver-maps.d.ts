// Naver Maps API v3 최소 ambient 선언 — SDK는 pages/map에서 동적으로 로드한다.
interface NaverMarker {
  setVisible(v: boolean): void
  setMap(map: object | null): void
}

interface NaverInfoWindow {
  open(map: object, anchor: object): void
  close(): void
  setContent(html: string): void
}

interface NaverMaps {
  Map: new (el: HTMLElement, opts?: Record<string, unknown>) => object
  Marker: new (opts: Record<string, unknown>) => NaverMarker
  LatLng: new (lat: number, lng: number) => object
  InfoWindow: new (opts?: Record<string, unknown>) => NaverInfoWindow
  Point: new (x: number, y: number) => object
  Event: {
    addListener(target: object, name: string, cb: () => void): void
  }
}

interface Window {
  naver?: { maps: NaverMaps }
  __mapClose?: () => void
}
