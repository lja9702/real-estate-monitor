# 인수인계 — myhouse React SPA 마이그레이션

브랜치 `feature/react-spa-migration`. 단계 1~5 + 후속 개선 완료. **단계 6(정리)** 과 **미커밋 작업 2갈래** 가 남았다.

---

## 1. 현재 상태 (✅ 완료, 커밋됨)

- **단계 1 (스캐폴딩)**: `frontend/` — Vite 8 + React 19 + TS 6 + Tailwind v4 + shadcn/ui(nova) + TanStack Query v5 + react-router v7. `app.py`가 `/app`에 dist 마운트.
- **단계 2 (JSON API)**: `/api/listings`, `/api/filter-domains`, `/api/listing/{cluster_key}/history`.
- **단계 3 (매물 페이지)**: 듀얼 슬라이더 5개 + 테이블. 별표/메모/제외/이력. sticky 헤더+필터바.
- **단계 4 (나머지 페이지)**: `/complex/{no}`, `/runs`, `/shortlist`, `/complexes`, `/deals`, `/permits` 전부 React. 각 Jinja 라우트는 `/app/*`로 302 리다이렉트.
- **단계 5 (지도)**: `/map` → `/app/map`. `/api/config`(네이버 키), `/api/map-data`. 네이버 Maps SDK 동적 로드 + 마커 + InfoWindow + 거래유형 필터.
- **헤더 복원** (`68b000b`): 페이지 네비(매물/실거래가/토지거래허가/★ 관심단지/지도/추적단지/실행로그) + 수집 버튼(지금 수집/실거래/허가)을 `root-layout.tsx`에 복원.
- **5가지 UI 개선** (`3f4ffae`):
  1. 지도 InfoWindow 단지명 → 네이버 단지 링크
  2. 전용면적 슬라이더에 평 병기(`formatAreaWithPyeong`)
  3. `/complex/{no}` 단지명 옆 네이버 링크
  4. `/complex/{no}` 매물·실거래 평수 필터 바
  5. 수집 취소 버튼(`/run-cancel` → `pkill -f "myhouse.cli collect"`)
- **새 엔드포인트** (`routes.py`, 커밋됨): `GET /api/config`(네이버 키 노출), `POST /run-cancel`(수집 중단).
  - ⚠️ **라이브(8765)는 launchd 재시작 전까지 구 파이썬 코드 사용** → 이 두 엔드포인트는 `launchctl kickstart -k gui/$(id -u)/com.myhouse.dashboard` 후에야 동작(사용자 동의 필요). 프론트 dist는 실시간 반영됨.

---

## 2. 미커밋 작업 트리 상태 ⚠️ (커밋 전 분리할 것)

`git status` 에 2갈래가 섞여 있다. **별도 커밋 2개로 나눌 것.**

### 갈래 A — SPA 마무리 (커밋 가능)
- `config.yaml`: discover 지역 추가(성남 분당구·성남 구도심·용인 수지구·과천시) + 가격대 **7~30억**(`price_min 70000`, `price_max 300000`). defaults도 `price_min 70000`.
  - 판교는 성남 분당구 bbox `[127.06,127.18,37.42,37.32]` 에 포함 → 별도 등록 안 함.
- `src/myhouse/cli.py`: **`bulk-import` 커맨드 신규**. discover.regions 마커를 수집해 `config.yaml targets` 에 일괄 append(이미 있는 단지·지역 간 중복 스킵).
  - 사용: `PYTHONPATH=src .venv/bin/myhouse bulk-import --dry-run` → 확인 후 `--dry-run` 제거.
  - **아직 dry-run만 실행**(446개 추가 예정). config.yaml에 targets는 미반영 상태.

### 갈래 B — 급매(flash-deals), **백엔드만·미연동** (별도 기능)
메모리 `myhouse-flash-deals.md` 설계대로 백엔드는 구현됐으나 **어디에도 노출 안 됨.**
- 있음: `core/flash.py`(순수함수), `tests/test_flash.py`, `models.py`(FlashDeal 스키마), `repo.py`/`collector.py`(수집 시 탐지), `settings.py`(flash config), `util.py`, `config.yaml`의 `flash:` 블록, `queries.py`.
- **없음(미연동)**: 프론트 `/app/flash` 페이지·router 라우트 ✗, `/api/flash` 엔드포인트 ✗, 텔레그램 🔥급매 다이제스트 ✗.
- → 이 기능을 끝내려면 별도 작업 필요. SPA 마이그레이션 PR과 **섞지 말 것.**

---

## 3. 테스트 상태

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q     # 330 passed
cd frontend && npx vitest run                  # 19 passed
```

전부 그린. 단계 6 정리 후 웹 스모크 테스트는 모두 JSON API/SPA 셸 기준으로 재작성됨.

---

## 4. 단계 6 — 정리 (✅ 완료)

| 항목 | 상태 |
|---|---|
| Jinja 라우트 삭제 | ✅ `routes.py` 페이지/리다이렉트 라우트·`_tpl`·`templates/`·`static/`(app.js·app.css) 제거 |
| SPA를 `/`로 승격 | ✅ `app.py` SPA 마운트 `/app`→`/`(include_router 뒤), `vite.config.ts` base `/`, `router.tsx` basename 기본값 |
| HTML 테스트 재작성 | ✅ `test_web*.py` 전부 JSON API/SPA 셸 단언으로 전환 |
| 빌드 단계 추가 | ✅ `install_launchd.sh` 에 nvm 소싱 + `npm ci && npm run build`(dist 는 .gitignore) |

> 잔여: `/api/listing/{ck}/history` 등 JSON API 만 사용. 구 Jinja 파셜 라우트(`/listing/.../history`)는 제거됨.

---

## 5. DB 방침 — SQLite 유지 (결론)

데이터 증가가 걱정됐으나 **현 워크로드에 SQLite가 정답.** 바꾸지 말 것.
- 단일 호스트(launchd) · 단일 writer(수집 subprocess) + 동시 reader(대시보드) → 이미 **WAL**(`engine.py`)로 해결.
- 큰 `listing`(13MB)은 누적 로그가 아니라 **현재상태(upsert)** — 단지수에 비례해 상한, 평탄화됨.
- 무한증가는 `listing_history`(이벤트 로그) 하나뿐. 보수적 추정 5년 후도 200MB대 → SQLite 여유.
- 이미 SQLModel/SQLAlchemy라 훗날 Postgres 전환도 거의 공짜(connection string + WAL PRAGMA만). **미리 옮길 이유 없음.**
- (선택) 용량 못 박고 싶으면 `listing_history` 보존정책 prune 잡 하나면 충분 — 현재 정리 로직 없음.

---

## 6. 빌드 · 실행 · 검증

```bash
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
cd frontend && npm run build                                   # 프로덕션 빌드

launchctl kickstart -k gui/$(id -u)/com.myhouse.dashboard      # 라이브 재시작(사용자 동의 필요)
```

- 라이브 8765는 dist를 실시간으로 읽음 → 빌드 후 `localhost:8765/app/` + Cmd+Shift+R
- 파이썬 코드(routes.py 등) 변경은 launchd 재시작 후 반영

---

## 7. 컨벤션 · 주의 (다시 발견하지 말 것)

1. **app.py 마운트 순서**: `include_router(router)` 먼저 → `SPAStaticFiles("/app")`. 반대면 `/api/*`가 catch-all에 먹힘.
2. **SPAStaticFiles**: Starlette `StaticFiles(html=True)`는 서브경로 직접접근 시 404 → 커스텀 서브클래스가 index.html로 대체.
3. **mutation은 form-urlencoded**(`apiPostForm`/`URLSearchParams`) — JSON 금지.
4. **react-router `basename: '/app'`**, 내부 이동은 `<Link>`.
5. **필터 상태 = URL 단일 소스**(`useSearchParams`), 슬라이더는 `onValueCommit`→URL.
6. **네이버 Maps SDK**: `pages/map/index.tsx` `_sdkLoad` 싱글턴 동적 로드, key는 `/api/config`로 노출. InfoWindow 닫기 버튼은 `window.__mapClose` 전역.
7. **discover bbox 가 실제 지리 필터**(cortarNo는 메타). bbox=`[leftLon, rightLon, topLat, bottomLat]`. 신규 지역은 `probe-markers --region "이름"` 으로 누락/노이즈 확인 후 조정.
8. **절대 커밋 금지**: `.env`, `data/`, `logs/`, `*.db`/`*.db-wal`/`*.db-shm`, `.claude/settings.local.json`. `config.yaml`은 시크릿 없어 안전.
9. **라이브 launchd 무단 재시작 금지**(`com.myhouse.*`) — 사용자 동의 필요.

---

## 8. 참고

- 전체 계획: `/Users/jajs/.claude/plans/drifting-knitting-pudding.md`
- 프론트 루트: `frontend/src` (FSD — `shared/entities/features/widgets/pages/app`)
- 백엔드: `src/myhouse/web/routes.py`, `queries.py`, `app.py` · CLI: `src/myhouse/cli.py`
