# 🚀 배포 전략 — 지인 공개(초대코드) + 24시간 서빙

지인 소수에게 대시보드를 **초대코드로만** 열어주되, **맥을 상시로 띄우지 않아도** 24시간 접속되게 한다.

## 1. 핵심 제약 (왜 앱 전체를 Vercel 에 못 올리나)

수집 파이프라인은 **맥에 묶여 있다**:

- **SQLite 단일 파일**(`data/myhouse.db`) — 서버리스엔 영구 파일시스템이 없다.
- **launchd 예약** — 서버리스/Vercel 엔 상시 스케줄러가 없다.
- **Playwright(헤드리스 Chromium)** — 네이버 토큰 발급용, 250MB+ 라 서버리스 부적합.
- **롱폴링 텔레그램 봇** — 상시 프로세스.
- **한국 IP 필수** — 네이버가 해외/데이터센터 IP 를 차단하는 경향. 집 IP 가 가장 안전.

→ **수집·봇·DB·수집 트리거는 맥에 남고**, 클라우드엔 **읽기 전용 서빙**만 올린다.

## 2. 선택한 구조 — 수집(맥, 가끔) ↔ 서빙(클라우드, 상시)

같은 코드베이스를 **두 역할**로 띄우고, 역할은 환경변수 `CLOUD_READONLY` 로 가른다.

```
맥(가끔 깸): collect → wal checkpoint → 일관 백업본 → R2 업로드
                                              │
클라우드(상시, Render): R2 pull(주기) → myhouse.db(ro) → FastAPI /api·SPA → [초대코드 게이트] → 지인
```

> **호스트 이력**: 처음엔 Fly.io 로 띄웠으나 무료 체험이 **2 VM-시간/7일**로 매우 짧아(헬스체크가 머신을 계속 깨워 하루 만에 소진) → **Render 무료 티어**(같은 Dockerfile·750시간/월·$0)로 이전했다. Fly 종량제 실비는 월 ~$2 수준이라 비싸진 건 아니지만 "$0 유지"가 목표라 갈아탔다. Fly 런북은 아래 [부록](#부록-flyio-런북-대안)에 남겨둔다. **Vercel 은 부적합**(상시 백그라운드 R2-pull 루프 + 로컬 SQLite 파일이 서버리스와 충돌 — 위 1절 참고).

| | 맥 (수집·운영) | 클라우드 (읽기 전용 서빙) |
|---|---|---|
| 하는 일 | 지금 그대로 수집·봇·큐레이션 + **수집 후 `myhouse.db` 를 R2 에 업로드** | 같은 FastAPI 를 **읽기 전용**으로 상시 구동, R2 에서 최신 DB 를 주기적으로 받아 서빙 |
| 쓰기/`run*` | 허용 | **전부 비활성(403)** |
| Playwright/봇 | 있음 | 없음 (이미지 가벼움) |
| 접근 | localhost | **초대코드 게이트** 뒤 |

- **신선도 트레이드오프**: 지인이 보는 데이터는 **맥이 마지막으로 수집한 시점** 기준. 하루 1회 갱신 데이터라 실사용 무리 없음.
- **큐레이션(★/메모)**: 맥에서 하고 다음 업로드에 반영. 클라우드는 읽기만 하므로 위험한 동작이 없고, 초대코드 한 겹으로 공개해도 안전.

> 대안으로 검토했으나 보류: ② 정적 JSON 익스포트(무서버·무비용이나 필터/집계를 프론트로 이관 필요), ③ Turso(libSQL) 자동 동기화(데이터 계층 변경 폭 큼), 한국 VPS 통째 배포(수집까지 24시간이지만 데이터센터 IP 차단 위험).

## 3. 단계별 체크리스트

### 1단계 — 초대코드 게이트 (로컬에서 먼저 완성, 클라우드 불필요)

- [x] `settings.py`: `WEB_INVITE_CODES`·`SESSION_SECRET`·`GATE_LOCAL_BYPASS` 필드 + `.env.example`
- [x] `web/auth.py`: stdlib `hmac` 쿠키 서명/검증 + 게이트 미들웨어
      (쿠키 없으면 HTML 요청은 게이트 페이지, `/api/*` 는 `401`)
- [x] `routes.py`: `GET/POST /gate`(코드 검증→httpOnly 쿠키 30일), `GET /api/me`, `GET /healthz`
- [x] 게이트는 **서버 렌더 미니 HTML 1장** — 인증 전엔 React SPA 자체가 로드되지 않게
- [x] `app.py`: 미들웨어 연결
- [x] **초대코드 통일**: 웹 코드 = `WEB_INVITE_CODES` ∪ `TELEGRAM_JOIN_CODE`(텔레그램 `/join` 과 같은 코드)
- [x] **로컬 면제**: localhost(루프백·프록시 미경유)는 코드 면제(`GATE_LOCAL_BYPASS`, 기본 on). 클라우드/터널은 `X-Forwarded-*` 로 항상 차단
- [x] `tests/test_web_gate.py` + ruff/pytest 통과
- [x] **호환성**: 초대코드(`TELEGRAM_JOIN_CODE`·`WEB_INVITE_CODES`)가 모두 비면 게이트 off(전체 허용). 테스트는 conftest autouse 픽스처로 실제 `.env` 를 격리해 항상 게이트 off 에서 시작

### 2단계 — 읽기 전용 클라우드 모드 (`CLOUD_READONLY=1`) ✅

- [x] `app.py`: 이 모드면 `init_db`/좀비정리(둘 다 쓰기) 건너뛰고 엔진을 **ro(`mode=ro`)** 로 오픈
- [x] 미들웨어가 변경 메서드(POST/PUT/PATCH/DELETE)를 게이트와 무관하게 `403` — `/run*` 서브프로세스 spawn 까지 라우트 진입 전 차단(`/gate` 로그인은 예외)
- [x] `engine.py`: `make_engine(..., readonly=True)`(`mode=ro` URI + `query_only`, WAL/-shm 미생성)
- [x] `GET /api/me` 가 `readonly` 플래그 반환(프론트가 쓰기 컨트롤 숨김용)
- [x] `tests/test_web_readonly.py`(읽기 OK·쓰기 403·엔진 직접쓰기 거부)

### 3단계 — DB 동기화 ✅

- [x] 맥 push: CLI `myhouse sync-push` — sqlite online backup 으로 WAL 포함 일관 사본 → R2 업로드
- [x] 클라우드 pull: 기동 시 1회 + `SYNC_PULL_INTERVAL_SECONDS`(기본 600s)마다 ETag 조건부 GET → temp→원자적 rename 교체, 갱신 시 엔진 dispose 로 재연결
- [x] S3 호환 클라이언트는 **순수 httpx + SigV4**(boto3 미사용) — `cloud/s3.py`, AWS 공식 벡터로 서명 검증(`tests/test_s3_sigv4.py`)
- [ ] (후속) 각 수집기(`collect*`) 성공 직후 자동 `sync-push` — 현재는 수동/별도 스케줄

### 4단계 — 컨테이너 + 배포 ✅(산출물 준비)

- [x] `Dockerfile`(2-스테이지: Vite 빌드 → python:3.12-slim, **Playwright 브라우저 없음**) + `.dockerignore`
- [x] `fly.toml`(`/healthz` 헬스체크 · scale-to-zero · 256MB)
- [ ] **직접**: R2 버킷·키 발급 → `sync-push` 1회 시드 → `fly launch`/`fly deploy` → 시크릿 주입 (아래 런북)
- [ ] (선택) 커스텀 도메인 · README/HANDOFF 에 배포 절 추가

## 4. 시크릿 / 환경변수

| 변수 | 위치 | 용도 |
|---|---|---|
| `TELEGRAM_JOIN_CODE` | 맥·클라우드 | **웹·텔레그램 공용 초대코드.** 설정 시 웹 게이트가 이 코드로 켜진다(지인은 텔레그램 `/join` 과 같은 코드로 입장) |
| `WEB_INVITE_CODES` | 맥·클라우드 | (선택) 웹 전용 추가 초대코드(쉼표 복수) |
| `WEB_ADMIN_CODES` | 맥·터널 | (선택) 운영자 코드 — role=admin → 수집 버튼 노출. 클라우드(읽기전용)에선 admin 이어도 숨김(수집은 맥 전용) |
| `SESSION_SECRET` | 맥·클라우드 | 게이트 쿠키 서명 키(랜덤 32바이트 권장) |
| `GATE_LOCAL_BYPASS` | 맥 | 기본 `true` — localhost(루프백·프록시 미경유)는 코드 면제. 로컬도 막으려면 `false` |
| `CLOUD_READONLY` | 클라우드만 | `1` 이면 읽기 전용(DB ro 오픈 + 모든 쓰기/수집 트리거 403) |
| `R2_ACCOUNT_ID`·`R2_ACCESS_KEY_ID`·`R2_SECRET_ACCESS_KEY`·`R2_BUCKET` | 맥(push)·클라우드(pull) | DB 동기화용 S3 호환 자격증명. 하나라도 비면 동기화 비활성 |
| `R2_DB_KEY` | 맥·클라우드 | (선택) 버킷 내 DB 오브젝트 키. 기본 `myhouse.db` |
| `SYNC_PULL_INTERVAL_SECONDS` | 클라우드만 | (선택) 최신 DB 재수신 주기(초). 기본 600 |
| `TELEGRAM_BOT_TOKEN`·`TELEGRAM_*` | 맥만 | 봇/알림(기존) |

> 웹 게이트의 초대코드 = `TELEGRAM_JOIN_CODE` ∪ `WEB_INVITE_CODES`. **`TELEGRAM_JOIN_CODE` 하나면 텔레그램·웹이 같은 코드로 통일**된다(지인 안내 단순화). 운영자의 **localhost 접속은 기본 면제**(`GATE_LOCAL_BYPASS=true`)라 코드를 묻지 않고, 클라우드/터널 경유만 코드를 요구한다.

## 5. 비용 · 운영 주의

- **비용**: Fly 작은 머신 **월 $0~5**, Cloudflare R2 무료 티어. 다 무료로 시작 가능.
- **네이버 차단 방지**: 외부 공개 후에도 **수집은 맥에서만**. 클라우드는 읽기 전용이라 호출 폭증 위험 없음.
- **비밀 관리**: 코드/시크릿은 `.env`(이미 `chmod 600`·gitignore)·Fly secrets 에. 코드 유출 시 회수(rotate) 가능하게 복수 코드 지원.
- **개인 정보**: 클라우드에 올라가는 건 공개 매물 데이터뿐(개인 식별정보 없음).

## 6. 배포 런북 (Fly.io + Cloudflare R2)

코드/이미지 산출물은 준비됨(`Dockerfile`·`fly.toml`·`sync-push`). 아래는 **직접 하는 계정·배포 단계**.

### A. Cloudflare R2 (DB 저장소)
1. Cloudflare 가입 → 좌측 **R2** → **Create bucket** (예: `myhouse-db`).
2. **R2 → Manage API Tokens → Create API Token**(Object Read & Write) → **Access Key ID·Secret Access Key** 복사.
3. 계정 ID 확인: R2 개요나 endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` 의 `<ACCOUNT_ID>`.

### B. 맥 `.env` 에 R2 채우고 1회 시드 push
```bash
cat >> .env <<'EOF'
R2_ACCOUNT_ID=<account_id>
R2_ACCESS_KEY_ID=<access_key>
R2_SECRET_ACCESS_KEY=<secret_key>
R2_BUCKET=myhouse-db
EOF
.venv/bin/myhouse sync-push        # ✅ 업로드: myhouse-db/myhouse.db (etag=...)
```

### C. Render 배포 (Blueprint)
리포에 [`render.yaml`](render.yaml) 이 있으니 클릭 몇 번이면 된다(CLI 불필요).

1. [dashboard.render.com](https://dashboard.render.com) 가입(GitHub 로그인) → **New ▾ → Blueprint**.
2. 이 리포 선택 → Render 가 `render.yaml` 을 읽어 `myhouse-dashboard`(Docker·free·Singapore) 를 생성.
3. **Apply** 누르면 `sync:false` 비밀값 입력을 요구한다. 다음을 채운다(초대코드는 텔레그램과 같은 값 권장):
   - `TELEGRAM_JOIN_CODE` = `우리집2026`
   - `SESSION_SECRET` = `python3 -c 'import secrets;print(secrets.token_urlsafe(32))'` 결과
   - `R2_ACCOUNT_ID` · `R2_ACCESS_KEY_ID` · `R2_SECRET_ACCESS_KEY` · `R2_BUCKET`
4. 첫 빌드(원격 Docker 빌드) 후 `https://myhouse-dashboard.onrender.com` 발급. (Blueprint 없이 하려면 **New → Web Service → 리포 → Docker** 로 잡고 위 env 를 수동 입력해도 동일.)

> **무료 티어 특성**: 15분 무접속 시 sleep → 다음 접속 때 **30~50초 콜드스타트**(이후 빠름). 데이터가 하루 1회 갱신·지인 소수 용도라 무방. sleep 중엔 백그라운드 R2-pull 도 멈추지만, 깰 때 기동 pull 로 최신 DB 를 다시 받는다.

### D. 스모크 체크
- `curl -sf https://myhouse-dashboard.onrender.com/healthz` → `{"ok":true}` (첫 호출은 콜드스타트로 수십 초 지연 가능)
- 브라우저로 접속 → 초대코드 입력 → 대시보드(읽기 전용). `지금 수집` 등은 403(읽기 전용).

### E. 지속 동기화(데이터 신선도)
맥에서 새로 수집할 때마다 `sync-push` 가 돌면 클라우드가 600초 안에 반영한다. 가장 간단한 방법:
- 임시: 수집 후 수동 `myhouse sync-push`.
- 권장(후속): launchd 수집기들(`com.myhouse.collector` 등) 성공 직후 `sync-push` 가 돌도록 래핑하거나, 각 `collect*` 끝에 자동 push 훅 추가.

> **첫 배포 순서 주의**: R2 가 비어 있으면 클라우드가 DB 를 못 받아 데이터가 안 보인다(헬스체크는 OK). 반드시 **B(시드 push) → C(배포)** 순서로.

---

## 부록: Fly.io 런북 (대안)

처음 쓰던 호스트. 무료 체험이 짧아 Render 로 이전했지만, 종량제 실비(이 워크로드 기준 월 ~$2)를 감수하면 그대로 쓸 수 있다. [`fly.toml`](fly.toml) 이 리포에 남아 있다(같은 Dockerfile 사용). A·B(R2 시드)는 위와 동일.

```bash
brew install flyctl && fly auth signup    # 또는 fly auth login (+ 카드 등록 — 체험 후 종량제)
fly launch --no-deploy                     # fly.toml 인식 — app 이름/리전 확인(빌드는 Fly 원격)

# 비밀 주입(이미지엔 비밀 없음). 초대코드는 텔레그램과 같은 값 권장.
fly secrets set \
  TELEGRAM_JOIN_CODE='우리집2026' \
  SESSION_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" \
  R2_ACCOUNT_ID='<account_id>' \
  R2_ACCESS_KEY_ID='<access_key>' \
  R2_SECRET_ACCESS_KEY='<secret_key>' \
  R2_BUCKET='myhouse-db'

fly deploy
fly open                                    # https://<app>.fly.dev → 초대코드 페이지
```

> **비용 주의**: Fly 신규 무료는 **2 VM-시간 또는 7일** 체험뿐이다. `fly.toml` 의 30초 헬스체크가 머신을 계속 깨워 체험이 하루 만에 소진될 수 있다. 종량제로 넘어간 뒤엔 scale-to-zero(`min_machines_running=0`·`auto_stop='suspend'`)로 유휴 비용을 줄인다.
