# 인수인계 — myhouse React SPA 마이그레이션 (단계 1~3 MVP 완료 · 단계 4 착수)

직전 세션에서 **MVP(스캐폴딩 + 매물 페이지 슬라이더화)를 완료·푸시**했다.
다음 작업은 **나머지 Jinja 페이지를 React로 전환(단계 4)** 하는 것이다.
권장 첫 타깃: **단지 상세(`/complex/{no}`)**.

---

## 1. 현재 상태 (✅ 완료, 모두 푸시됨)

- 브랜치 `feature/react-spa-migration`, 최신 커밋 `52f96a2`. `main` = 마이그레이션 착수 전 기준선.
- **단계 1 (스캐폴딩)**: `frontend/` — Vite 8 + React 19 + TS 6 + Tailwind v4(`@tailwindcss/vite`) + shadcn/ui(nova) + TanStack Query v5 + react-router v7. `app.py`가 `/app`에 dist 마운트.
- **단계 2 (JSON API)**: `routes.py`에 `/api/listings`, `/api/filter-domains`, `/api/listing/{cluster_key}/history`. `queries.py`에 `filter_domains()`. `tests/test_api.py`(6 케이스).
- **단계 3 (매물 페이지)**: React 매물 페이지 — 듀얼 슬라이더 5개(가격·전용·세대수·준공·최소층) + 테이블. 필터 상태 = URL 단일 소스.
- **UI 개선 (단계 3 이후)**: 실거래 YY-MM 표기, 메모 컬럼(인라인 blur 저장), 상태(신규 배지), 즐겨찾기 ★ 토글, 단지명 → 내부 `/complex/{no}` 링크, 전체폭 테이블(가로 스크롤 제거), **헤더 + 필터 바 + 건수 줄 모두 sticky 고정**.

---

## 2. 빌드 · 실행 · 검증 (그대로 재사용)

```bash
# nvm 소싱 필요 (node v24)
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# 프로덕션 빌드 → src/myhouse/web/dist (라이브 8765가 실시간 서빙)
cd frontend && npm run build

# 개발: 터미널1 `myhouse serve`(:8765) + 터미널2 `npm run dev`(:5173) → localhost:5173/app/
# 검증용 프리뷰: .claude/launch.json 의 "myhouse-preview"(:8799) — preview_start 로 기동
```

- 파이썬 테스트: `PYTHONPATH=. pytest -q` (pyproject `pythonpath = ["src", "."]` 설정됨)
- 프론트 테스트: `cd frontend && npx vitest run` (예: `memo-input.test.tsx`)
- **라이브 8765는 dist를 실시간으로 읽음** → 빌드만 하면 `localhost:8765/app/` + Cmd+Shift+R 로 즉시 확인.

---

## 3. 단계 4 — 나머지 페이지 React화 (다음 작업)

대상 Jinja 페이지(`routes.py`):

| 라우트 | 위치 | 비고 |
|---|---|---|
| `/complex/{no}` | `routes.py:232` | **권장 첫 타깃** (아래) |
| `/deals` | `routes.py:192` | 실거래 |
| `/permits` | `routes.py:212` | 토지거래허가 |
| `/shortlist` | `routes.py:182` | 관심 단지 |
| `/complexes` | `routes.py:277` | 단지 목록 |
| `/runs` | `routes.py:268` | 수집 이력 |
| `/map` | `routes.py:317` | 지도 — 단계 5 (네이버 SDK), 마지막 |

**페이지별 레시피** (각 페이지 반복):
1. `/api/*` JSON 읽기 엔드포인트 추가 — 기존 빌더 함수 재사용 + `dataclasses.asdict`. `include_router` 안, SPA 마운트 **앞**.
2. React 라우트/페이지 구현 — `entities/*/api` + `pages/*` (+ 필요 시 `widgets/*`). 기존 패턴(useQuery, `shared/lib/format`, shadcn table) 그대로.
3. 완성 후 해당 Jinja 라우트를 `/app/*`로 리다이렉트(또는 링크 전환). **Jinja 라우트 자체는 단계 6 전까지 삭제 금지.**

**왜 단지 상세부터?** 매물 테이블의 단지명이 이미 `/complex/{no}`로 링크되어 있으나 현재 Jinja라 클릭 시 **전체 네비게이션(SPA 이탈)** 이 발생한다. 이걸 React화하면 SPA 내 이동(`<Link>`)으로 매끄러워진다.
- **백엔드**: `complex_detail`(`routes.py:232`)이 쓰는 `complex_stats` / `build_cluster_rows` / `recent_deals_for_complex` 재사용 → `GET /api/complex/{no}` JSON 추가.
- **프론트**: react-router에 `/complex/:no` 라우트 추가, 매물 테이블의 단지명 `<a href>` → `<Link>`로 교체.
- **가격 이력**: `/api/listing/{cluster_key}/history`가 이미 있음 → 상세의 스파크라인/모달에 재사용.

---

## 4. 컨벤션 · 주의 (새 세션이 다시 발견하지 말 것)

1. **app.py 마운트 순서**: `include_router(router)` → 그 다음 `StaticFiles("/app", html=True)`. 반대면 `/api/*`가 SPA catch-all에 먹힘.
2. **mutation은 form-urlencoded**: 별표/제외/메모/추적/수집 엔드포인트가 `Form(...)`. 프론트는 `apiPostForm`(`URLSearchParams`)로 호출 — JSON 금지. (`shared/api/client.ts`)
3. **react-router `basename: '/app'`**. 내부 이동은 `<Link>`로 (전체 네비 방지).
4. **필터 상태 = URL 단일 소스**(`useSearchParams`). 슬라이더 `onValueChange`→로컬(라벨), `onValueCommit`→URL 커밋. 경계값은 `null`로 보내 URL을 깔끔하게.
5. **TS 6**: `baseUrl` 금지(`paths`만 사용).
6. **절대 커밋 금지**: `.env`, `data/`, `logs/`, `*.db`/`*.db-wal`/`*.db-shm`, `.claude/settings.local.json`. `config.yaml`은 시크릿 없어 안전.
7. **라이브 launchd 무단 재시작 금지**(`com.myhouse.*`) — 사용자 동의 필요.

---

## 5. 참고

- 전체 계획: `/Users/jajs/.claude/plans/drifting-knitting-pudding.md` (단계 4~6 = 205~215행)
- 프로젝트 개요: `MEMORY.md`(자동 로드)
- 프론트 루트: `frontend/src`(FSD — `shared/entities/features/widgets/pages/app`)
- 백엔드: `src/myhouse/web/routes.py`, `queries.py`, DB 모델 `src/myhouse/db/models.py`
