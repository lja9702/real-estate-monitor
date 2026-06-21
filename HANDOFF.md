# 인수인계 — myhouse React SPA 마이그레이션 (단계 1~5 완료)

브랜치 `feature/react-spa-migration`. 단계 6(정리)만 남았다.

---

## 1. 현재 상태 (✅ 완료, 모두 푸시됨)

- **단계 1 (스캐폴딩)**: `frontend/` — Vite 8 + React 19 + TS 6 + Tailwind v4 + shadcn/ui(nova) + TanStack Query v5 + react-router v7. `app.py`가 `/app`에 dist 마운트.
- **단계 2 (JSON API)**: `/api/listings`, `/api/filter-domains`, `/api/listing/{cluster_key}/history`.
- **단계 3 (매물 페이지)**: 듀얼 슬라이더 5개 + 테이블. 별표/메모/제외/이력. sticky 헤더+필터바.
- **단계 4 (나머지 페이지 React화)**: `/complex/{no}`, `/runs`, `/shortlist`, `/complexes`, `/deals`, `/permits` 전부 React 페이지. 각 Jinja 라우트는 `/app/*`로 302 리다이렉트.
- **단계 5 (지도)**: `/map` → `/app/map` 리다이렉트. `/api/config`(네이버 키), `/api/map-data`(기존). 네이버 Maps SDK 동적 로드 + 마커 + InfoWindow + 거래유형 필터.

---

## 2. 빌드 · 실행 · 검증

```bash
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# 프로덕션 빌드
cd frontend && npm run build

# 라이브 서버 재시작 (사용자 동의 필요)
launchctl kickstart -k gui/$(id -u)/com.myhouse.dashboard
```

- 파이썬 테스트: `PYTHONPATH=. pytest -q`
- 프론트 테스트: `cd frontend && npx vitest run`
- **라이브 8765는 dist를 실시간으로 읽음** → 빌드 후 `localhost:8765/app/` + Cmd+Shift+R

---

## 3. 단계 6 — 정리 (남은 작업)

| 항목 | 내용 |
|---|---|
| Jinja 라우트 삭제 | `routes.py`의 리다이렉트 라우트들, Jinja 템플릿(`templates/*.html`), 구 `app.js`/`app.css` |
| SPA를 `/`로 승격 | `app.py` — `/app` 마운트를 `/`로, basename 변경 (`vite.config.ts` + `router.tsx`) |
| HTML 테스트 재작성 | `tests/test_api.py` — `in r.text` 방식 → JSON 응답 검증으로 |
| 빌드 단계 추가 | `install_launchd.sh`에 `npm ci && npm run build` 추가 |

---

## 4. 컨벤션 · 주의 (새 세션이 다시 발견하지 말 것)

1. **app.py 마운트 순서**: `include_router(router)` 먼저 → `SPAStaticFiles("/app")`. 반대면 `/api/*`가 SPA catch-all에 먹힘.
2. **SPAStaticFiles**: Starlette `StaticFiles(html=True)`는 SPA 서브경로 직접 접근 시 404 반환 → 커스텀 서브클래스(`app.py`)가 404를 index.html로 대체.
3. **mutation은 form-urlencoded**: `apiPostForm`(`URLSearchParams`) — JSON 금지.
4. **react-router `basename: '/app'`**. 내부 이동은 `<Link>`.
5. **필터 상태 = URL 단일 소스**(`useSearchParams`). 슬라이더는 `onValueCommit`→URL 커밋.
6. **네이버 Maps SDK**: `pages/map/index.tsx`가 `_sdkLoad` 싱글턴으로 동적 로드. key는 `/api/config`로 노출.
7. **절대 커밋 금지**: `.env`, `data/`, `logs/`, `*.db`/`*.db-wal`/`*.db-shm`, `.claude/settings.local.json`.
8. **라이브 launchd 무단 재시작 금지**(`com.myhouse.*`) — 사용자 동의 필요.

---

## 5. 참고

- 전체 계획: `/Users/jajs/.claude/plans/drifting-knitting-pudding.md`
- 프론트 루트: `frontend/src` (FSD — `shared/entities/features/widgets/pages/app`)
- 백엔드: `src/myhouse/web/routes.py`, `queries.py`, `app.py`
