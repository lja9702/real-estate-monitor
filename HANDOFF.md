# 인수인계 — myhouse React SPA 마이그레이션 (단계 2~3 착수 준비 완료)

이 파일은 직전 세션에서 완료된 분석·계획을 요약하고, 다음 세션에서 바로 구현을 착수하기 위한 문서다.

---

## 0. 작업 배경

`/Users/jajs/Projects/my-house` — FastAPI + Jinja2 SSR 부동산 모니터 대시보드.

**요청**: 매물 페이지(`/`)의 가격·전용·층수·세대수·준공 필터를 텍스트 input에서 **min~max 듀얼 슬라이더**로 바꾸고, React + FSD + shadcn/ui 구조로 프론트를 리팩토링.

**확정된 범위: MVP (단계 1~3만)** — 슬라이더+매물 페이지 완성. 나머지 7페이지는 기존 Jinja로 공존.

**전체 계획 파일**: `/Users/jajs/.claude/plans/drifting-knitting-pudding.md` (이미 사용자 승인됨)

---

## 1. 현재 상태 (직전 세션 종료 시점)

- [x] 코드베이스 전수 분석 완료 (web 스택·템플릿·JS·테스트·배포 전부)
- [x] 마이그레이션 계획 승인됨 (`drifting-knitting-pudding.md`)
- [x] Task #1 생성됨: "단계2: 백엔드 JSON API 추가" (pending)
- [ ] **Node.js 미설치** — 사용자가 직접 설치하기로 함 (brew/nvm/공식 인스톨러 중 선택)
- [ ] 구현 착수 전 세션 종료됨

---

## 2. 아키텍처 요약

```
/app/*    → React SPA (Vite 빌드 산출물 → src/myhouse/web/dist)   ← 신규
/         → 기존 Jinja SSR (매물/실거래/허가 등 7페이지)           ← 공존 유지
/api/*    → 신규 JSON API (단계 2에서 추가)
/curation, /complexes, /run* → 기존 JSON mutation (무수정)
```

**핵심 설계 결정**: SPA를 `/app` 경로에 올려 Jinja와 공존. 페이지가 React로 완성될 때마다 Jinja 라우트를 `/app/*`로 넘김. 마지막에 `/`로 승격 (단계 6, 이번 MVP 범위 아님).

---

## 3. 단계별 구현 순서

### 단계 1 — 스캐폴딩 + 빈 SPA 서빙 (Node 설치 후 착수)

**생성**: `frontend/` 디렉터리 — Vite + React 18 + TS + Tailwind + shadcn/ui + TanStack Query v5 + react-router v6

```bash
# Node 설치 확인 후
node --version   # v20+ 권장
cd /Users/jajs/Projects/my-house
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npx tailwindcss init -p   # 또는 tailwind v4 방식
npx shadcn@latest init
npm install @tanstack/react-query react-router-dom
npm install -D vitest @testing-library/react @testing-library/user-event jsdom
```

**핵심 설정 파일**:
- `frontend/vite.config.ts` — `base: "/app/"`, `build.outDir: "../src/myhouse/web/dist"`, dev proxy
- `frontend/tsconfig.json` — `paths: { "@/*": ["./src/*"] }`

**vite.config.ts 핵심 내용**:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  base: '/app/',
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  build: { outDir: path.resolve(__dirname, '../src/myhouse/web/dist'), emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/curation': 'http://127.0.0.1:8765',
      '/complexes': 'http://127.0.0.1:8765',
      '/run': 'http://127.0.0.1:8765',
      '/static': 'http://127.0.0.1:8765',
    },
  },
})
```

**FastAPI 수정** (`src/myhouse/web/app.py` 끝에 추가):
```python
dist = WEB_DIR / "dist"
if dist.exists():
    app.mount("/app", StaticFiles(directory=str(dist), html=True), name="spa")
```
`include_router(router)` **뒤에** 달아야 `/api/*`가 SPA에 안 먹힘.

**.gitignore 추가**:
```
frontend/node_modules/
src/myhouse/web/dist/
```

**완료 기준**: `npm run build` → `myhouse serve` → `localhost:8765/app/` 에서 React 셸 렌더. 기존 `/` Jinja 정상. `pytest` green.

---

### 단계 2 — 백엔드 JSON API 추가 (Node 불필요, 먼저 가능)

**`src/myhouse/web/queries.py` 끝에 추가**:
```python
@dataclass
class FilterDomains:
    price_min: int
    price_max: int
    area_min: float
    area_max: float
    households_min: int
    households_max: int
    year_min: int
    year_max: int
    floor_max: int

def filter_domains(session: Session) -> FilterDomains:
    from sqlmodel import select as sel, func
    from ..db.models import Listing, Complex
    # Listing의 활성 매물 기준 min/max 집계. None 안전 + 빈 DB 폴백.
    r = session.exec(
        sel(
            func.min(Listing.price_deal), func.max(Listing.price_deal),
            func.min(Listing.area_excl), func.max(Listing.area_excl),
            func.min(Listing.floor_num), func.max(Listing.floor_num),
        ).where(Listing.article_status != "REMOVED")
    ).first()
    cx = session.exec(
        sel(func.min(Complex.total_households), func.max(Complex.total_households),
            func.min(Complex.use_approve_ymd), func.max(Complex.use_approve_ymd))
    ).first()
    def yi(ymd): return int(ymd[:4]) if ymd else None
    return FilterDomains(
        price_min=r[0] or 0,        price_max=r[1] or 300000,
        area_min=r[2] or 0,         area_max=r[3] or 200,
        households_min=cx[0] or 0,  households_max=cx[1] or 5000,
        year_min=yi(cx[2]) or 1970, year_max=yi(cx[3]) or 2025,
        floor_max=r[5] or 30,
    )
```

**`src/myhouse/web/routes.py` 에 추가** (기존 map_data 라우트 아래):
```python
@router.get("/api/listings")
def api_listings(
    filters: Filters = Depends(get_filters),
    session: Session = Depends(get_session_dep),
):
    rows = build_area_group_rows(session, filters, _last_run_id(session))
    return {
        "rows": [dataclasses.asdict(r) for r in rows],
        "total": len(rows),
        "new_count": sum(1 for r in rows if r.is_new),
        "complexes": [
            {"complex_no": c.complex_no, "name": c.name or c.complex_no}
            for c in list_complexes_filtered(session, filters.gu, filters.dong)
        ],
        "gu_dong_map": address_option_map(session),
    }


@router.get("/api/filter-domains")
def api_filter_domains(session: Session = Depends(get_session_dep)):
    return dataclasses.asdict(filter_domains(session))


@router.get("/api/listing/{cluster_key}/history")
def api_listing_history(cluster_key: str, session: Session = Depends(get_session_dep)):
    pts = price_history(session, cluster_key)
    return {"points": [dataclasses.asdict(p) for p in pts], "spark": sparkline(pts)}
```

`routes.py` import에 `filter_domains` 추가 필요 (`from .queries import ... filter_domains`).

**검증용 테스트** (`tests/test_api.py` 신규):
- `GET /api/listings` → 200, `rows/total/new_count/complexes/gu_dong_map` 키 존재
- `GET /api/listings?price_min=99999999` → `rows` 빈 배열 (극단값 필터 동작)
- `GET /api/filter-domains` → 200, `price_min <= price_max` 등
- 기존 `tests/test_web.py` 전부 green 유지 확인

---

### 단계 3 — React 매물 페이지 구현 (단계 1+2 완료 후)

FSD 디렉터리 구조 (`frontend/src/`):
```
app/          App.tsx, providers/router+query, layouts/root-layout, styles/index.css
pages/listings/index.tsx
widgets/app-header/, filter-panel/listing-filter-panel.tsx, listing-table/
features/
  filter-listings/model/use-listing-filters.ts   ← URL↔필터 동기화
  star-complex/, exclude-listing/, edit-memo/, price-history/
entities/listing/api/get-listings.ts, model/types.ts
shared/
  ui/ (shadcn: slider, select, checkbox, input, button, dialog, table, badge)
  ui/range-slider.tsx  ← ★ 듀얼핸들 래퍼
  api/client.ts, query-keys.ts
  lib/format.ts, cn.ts, debounce.ts
  config/constants.ts
```

**듀얼 슬라이더** (`shared/ui/range-slider.tsx`):
- shadcn `<Slider value={[lo, hi]}>`면 thumb 2개 자동 렌더 (Radix 기본)
- `onValueChange` → 로컬 state (라벨 즉시 갱신)
- `onValueCommit` → URL 커밋 → TanStack Query refetch

**슬라이더 step**:
- 가격: 1000 (만원 단위, = 천만원)
- 전용: 1 (㎡)
- 세대수: 50
- 준공: 1 (년)
- 층(floor_min): 1 — **단일 슬라이더** (하한만)

**format_manwon 포팅** (`shared/lib/format.ts`):
```ts
export function formatManwon(v: number | null): string {
  if (v == null) return "-";
  if (v < 0) return "-" + formatManwon(-v);
  const eok = Math.floor(v / 10000), rem = v % 10000;
  if (eok && rem) return `${eok}억${rem.toLocaleString("ko-KR")}`;
  if (eok) return `${eok}억`;
  return v.toLocaleString("ko-KR");
}
// vitest: formatManwon(158000)==="15억8,000", 90000=>"9억", 5000=>"5,000"
```

---

## 4. 재사용 자산 (건드리지 않아도 되는 것들)

| 파일 | 재사용 포인트 |
|---|---|
| `src/myhouse/web/queries.py` | 모든 빌더 함수 무수정 재사용. `build_area_group_rows`, `price_history`, `sparkline`, `address_option_map`, `list_complexes_filtered` |
| `src/myhouse/web/routes.py:65-92` | `get_filters()` + `Filters` dataclass — JSON API에서도 동일 `Depends` 재사용 |
| `src/myhouse/web/routes.py:291-434` | 별표/제외/메모/추적/수집 mutation (POST) — React에서 그대로 호출 |
| `src/myhouse/web/app.py:37` | `StaticFiles` 패턴 — SPA dist 마운트에 재사용 |
| `src/myhouse/util.py:6-17` | `format_manwon` 원본 — TS 포팅의 정답 소스 |
| `tests/conftest.py` | `engine` fixture (tmp SQLite) — 신규 test_api.py에서 그대로 재사용 |

---

## 5. 주의사항

1. **app.py 마운트 순서**: `app.include_router(router)` **뒤에** SPA StaticFiles. 반대면 `/api/*`가 SPA catch-all에 먹힘.
2. **`filter_domains`의 Listing 모델 필드명**: `src/myhouse/db/models.py`에서 실제 컬럼명 확인 필요 (`price_deal`, `area_excl`, `floor_num`, `article_status` 등). 집계 쿼리 작성 전 확인.
3. **TradeType enum**: `AreaGroupRow.trade_type`이 `TradeType(str, Enum)`이라 `dataclasses.asdict()`→`"SALE"` 문자열로 직렬화됨 — OK.
4. **공존 기간**: 기존 Jinja HTML 라우트(`GET /`, `GET /deals` 등)는 단계 4~6까지 **그대로 유지**. 건드리지 말 것.

---

## 6. 다음 세션 시작 체크리스트

```
[ ] node --version   # v20+ 확인 (없으면 단계 2 먼저)
[ ] cd /Users/jajs/Projects/my-house
[ ] python -m pytest tests/test_web.py -q   # 기준선 확인
[ ] Task #1 in_progress 마크 후 단계 2 구현 착수
    (단계 2는 Node 없어도 됨 — 백엔드 Python 작업)
```

---

## 7. 참고 링크

- 전체 계획: `/Users/jajs/.claude/plans/drifting-knitting-pudding.md`
- 기존 필터 UI: `src/myhouse/web/templates/index.html:54-62`
- 백엔드 라우트: `src/myhouse/web/routes.py`
- 쿼리/빌더: `src/myhouse/web/queries.py`
- DB 모델: `src/myhouse/db/models.py` (단계 2 filter_domains 작성 전 확인)
