# 🏠 myhouse — 네이버부동산 매물 모니터

관심 아파트 단지의 매물을 **매일 자동 수집**해서 직전 스냅샷과 비교(diff)하고,
**신규 / 가격변동 / 거래완료(추정)** 변화를 **텔레그램으로 요약 알림** + **로컬 웹 대시보드**에서
필터·정렬·별표·메모하며 매수 후보를 추려나가는 개인용 도구입니다. 매물(호가)뿐 아니라
**국토부 실거래가 · 토지거래허가 · 법원경매 · 급매**까지 한곳에서 모니터링합니다.

- **언어/실행**: Python 3.12 + **React SPA**(Vite) 대시보드 · 맥북 로컬(한국 IP) · `launchd` 로 매일 예약
- **데이터**: `new.land.naver.com` 비공식 API. 토큰이 3시간마다 만료되고 봇/rate 차단이 강해,
  **헤드리스 브라우저(Playwright)** 가 실행마다 토큰을 자동 발급하고 브라우저 컨텍스트로 호출해 우회합니다.
- **저장**: 단일 SQLite 파일 (`data/myhouse.db`)
- **실거래가(국토부)**: 매물(호가)과 별개로 **국토부 실거래가**(네이버 `prices/real` 경유)를 **하루 1회**
  수집해 **신규 실거래/거래취소**를 텔레그램으로 알리고 `/deals` 화면에서 단지·평형·기간별로 봅니다. → [11. 실거래가](#11-실거래가-국토부)
- **토지거래허가·법원경매·급매**: 추적 단지의 **토지거래허가**(서울 25구 `land.seoul.go.kr` + 경기 과천 `gyeonggi/`),
  **법원경매**(`courtauction.go.kr`), **급매**(같은 평형 호가 하한을 일정% 이상 밑도는 매물)를 각각 수집·알림하고
  `/permits`·`/auctions`·`/flash` 화면에서 봅니다. → [13. 토지거래허가·법원경매·급매](#13-토지거래허가--법원경매--급매)
- **텔레그램 양방향 봇**: 정기 알림에 더해, 텔레그램에서 **`/add`(신규단지 추가 — 번호 또는 단지명·주소 검색) ·
  `/check`(매물 즉시 갱신+변동) · `/deals`(실거래 확인)** 명령으로 원할 때 바로 조회합니다. → [12. 텔레그램 봇](#12-텔레그램-봇--양방향-명령)

> ⚠️ **비공식 API 주의**: 네이버는 공식 부동산 API 가 없어 비공식 엔드포인트를 사용합니다. 형태가
> 바뀔 수 있으니 **최초 1회 `probe` 로 실제 응답을 검증**하세요(아래 [API 검증](#5-api-검증-중요)).
> 소규모(단지 몇 개 × 1일 2회 × 한국 IP)라 차단 위험은 낮지만, 과도한 호출은 피하세요.

---

## 1. 설치

```bash
# Python 3.12 (Homebrew)
brew install python@3.12

cd ~/Projects/my-house
python3.12 -m venv .venv
.venv/bin/pip install -e .            # 개발 도구까지: .venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium # 헤드리스 브라우저(매물 수집용) — 최초 1회

# 대시보드(React SPA) 빌드 — Node 18+ 필요. 산출물 src/myhouse/web/dist 를 FastAPI 가 루트(/)에 서빙
( cd frontend && npm ci && npm run build )

.venv/bin/python -m myhouse.cli initdb   # DB 생성 (data/myhouse.db)
```

`myhouse` 콘솔 스크립트도 설치됩니다: `.venv/bin/myhouse --help` (또는 `python -m myhouse.cli`).

> 대시보드는 **React SPA**(`frontend/`, Vite+React+TS)이고 `dist/` 는 `.gitignore` 대상이라 **배포 시 빌드**합니다.
> `scripts/install_launchd.sh` 가 설치 단계에서 `npm ci && npm run build` 를 자동 실행합니다.

## 2. 텔레그램 봇 설정

1. 텔레그램에서 **@BotFather** → `/newbot` → 안내대로 이름 지정 → **봇 토큰** 발급
2. 만든 봇과 대화창을 열고 아무 메시지나 1번 전송
3. 본인 **chat_id** 확인:
   ```bash
   curl "https://api.telegram.org/bot<봇토큰>/getUpdates"
   # 응답의 result[].message.chat.id
   ```
4. `.env.example` 를 복사해 `.env` 작성:
   ```bash
   cp .env.example .env
   # TELEGRAM_BOT_TOKEN=... 채우기. 봇을 지인과 함께 쓰면:
   #   TELEGRAM_ALLOWLIST=내chat_id   (운영자 앵커)
   #   TELEGRAM_JOIN_CODE=우리집2026   (지인은 /join 우리집2026 한 번이면 자동 등록 — chat_id 불필요)
   chmod 600 .env
   ```
5. 연결 테스트: `.venv/bin/python -m myhouse.cli test-notify`

> 텔레그램을 설정하지 않아도 동작합니다(알림 없이 수집·대시보드만).

## 3. 추적 대상 설정 — `config.yaml`

**단지 직접 지정** — `complex_no` 만 있으면 됩니다(좌표 불필요):
```yaml
targets:
  - kind: complex
    complex_no: "947"             # 네이버 단지 URL 의 숫자
    label: "방배 삼호1차"
    overrides:                    # defaults 를 덮어쓰는 필터(선택)
      trade_types: ["SALE", "JEONSE"]
      price_max_manwon: 200000    # 20억
```

**complex_no 얻는 법**: PC 네이버부동산에서 단지를 열면 URL 이
`new.land.naver.com/complexes/947?...` 형태입니다. `complexes/` 뒤 숫자가 `complex_no` 입니다.
여러 단지는 블록을 복사해 `complex_no`/`label` 만 바꾸면 됩니다.

> 지역 자동탐색(`kind: region`)은 추후 new.land markers 기반으로 지원 예정입니다.

### 공통 필터 — `defaults`
```yaml
defaults:
  trade_types: ["SALE"]        # SALE(매매) | JEONSE(전세) | WOLSE(월세)
  area_supply_min_m2: 66       # 공급면적(area1) 하한 ㎡
  area_supply_max_m2: 131      # 공급면적(area1) 상한 ㎡
  area_excl_min_m2: null       # 전용면적(area2) 하한 — null=제한없음
  area_excl_max_m2: null
  price_min_manwon: null       # 매매가 하한 (만원). 15억=150000
  price_max_manwon: 300000     # 매매가 상한 (만원). 30억=300000
  floor_min: null              # 최저층 (1층/반지하 제외 시 2)
```

> **공급 vs 전용**: 네이버 API 의 `area1`=공급면적, `area2`=전용면적. 단지 탐색·광고에서 흔히 쓰는
> "몇 평형" 기준은 **공급면적(`area_supply_*`)** 이고, 등기·계약서의 실면적은 **전용(`area_excl_*`)** 입니다.
> 두 필터를 동시에 쓸 수 있습니다.

앱 설정(`app:`)에는 `removal_debounce_hours`(거래완료 확정까지 미노출 시간, 기본 20),
`request_delay_seconds`(요청 간 지연), `notify_on_no_change`(변화 없어도 알림 여부) 등이 있습니다.

## 4. 단지 대량 탐색

관심 지역 전체에서 조건에 맞는 단지를 한 번에 찾아 `config.yaml` 에 등록하는 방법입니다.

### 탐색 스크립트 작성·실행

```python
# /tmp/full_discover.py — 핵심 파라미터만 조정하면 됨
PMIN, PMAX = 150000, 260000    # 가격 사전 필터 (만원)
SUP_MIN, SUP_MAX = 66.0, 131.0 # 공급면적 ㎡

SEEDS = [
    ("동작구",   "1159000000", None),
    ("서초구",   "1165000000", None),
    # ...
    ("여의도동", "1156000000", {"여의도동"}),  # 구 안에서 특정 동만 볼 때
]
```

```bash
python /tmp/full_discover.py 2>&1 | tee /tmp/discover_output.txt
# 결과: data/discovered_accurate.json (단지별 매칭 매물 수·가격범위·샘플 포함)
```

### 탐색 결과 → config.yaml 반영

```python
import json, yaml
data = json.load(open("data/discovered_accurate.json"))
# complex_no / name 을 targets 블록으로 변환해 config.yaml 에 추가
```

> **단지 코드 목록**: 주요 지역 구 코드 — 동작구 `1159000000`, 서초구 `1165000000`,
> 강남구 `1168000000`, 송파구 `1171000000`, 용산구 `1117000000`, 성동구 `1120000000`,
> 영등포구 `1156000000`(여의도), 과천시 `4129000000`

### 4.1 주간 신규편입 자동탐색 (`discover`)

위 대량 탐색을 **주 1회 자동으로** 돌려, 가격대(매매 15~26억)·세대수·면적 조건에 **새로 든 단지**가
생기면 텔레그램으로 알립니다. 추가(추적)는 알림을 보고 사용자가 `/add` 로 직접 합니다.

- **데이터원**: new.land `single-markers`(지도 마커). 지역 bbox 안의 모든 단지를 minDealPrice~maxDealPrice
  (만원)·세대수·면적과 함께 1회로 받아, 가격/세대수/면적은 **서버측 필터**로 거릅니다(구당 1콜).
  ⚠️ bbox 1회 응답은 500개로 캡되고 `cortarNo` 는 서버측 필터가 아닙니다(bbox 가 유일한 지리 경계).
  필터를 걸면 캡 아래로 줄어 완전 수집됩니다 — 캡에 닿으면 로그 경고가 뜨니 bbox 를 조이세요.
- **신규 판정**: 첫 회차는 **baseline**(현재 편입 단지를 전부 기록만, 무알림). 이후 회차부터 baseline·
  추적 단지(config/DB)에 **없던** 단지만 알립니다. 알림은 단지당 1회(`discover_candidate.notified`).
- **설정**: `config.yaml` 의 `discover:` 섹션(가격/세대수/면적·`regions[].bbox`). 기본 8개 구가 들어 있습니다.
- **검증**: `python -m myhouse.cli probe-markers [--region 강남구]` 로 지역별 편입 단지 수를 즉석 확인.
- **수동 실행/봇**: `python -m myhouse.cli discover --trigger manual`, 또는 텔레그램 `/discover`.
- **일정**: launchd `com.myhouse.discover`(매주 월요일 09:00 KST). 시각/요일은 plist 의 `StartCalendarInterval` 수정.

## 5. 사용법

```bash
# 수동 1회 수집(+텔레그램) — 콘솔에 다이제스트 미리보기 출력
.venv/bin/python -m myhouse.cli collect --trigger manual

# 대시보드 실행 → http://localhost:8765
.venv/bin/python -m myhouse.cli serve

# DB 백업(타임스탬프 사본)
.venv/bin/python -m myhouse.cli backup-db
```

대시보드는 **React SPA**(루트 `/`)이고 데이터는 `/api/*` JSON 으로 로드합니다. 페이지(클라이언트 라우팅):
매물 `/` · 실거래가 `/deals` · 토지거래허가 `/permits` · 법원경매 `/auctions` · 급매 `/flash` · 지도 `/map` ·
★ 관심단지 `/shortlist` · 추적단지 `/complexes` · 실행로그 `/runs`.

대시보드에서:
- **필터/정렬**: 단지·거래유형·가격·면적·층·향·상태·검색, 신규순/가격순 등
- **★ 관심 단지**: 행/단지 상세의 ★ 로 **단지**를 관심 등록(같은 단지 행은 함께 켜짐). 관심은 단지 단위 즐겨찾기이며 추적 여부와 무관합니다.
- **제외 / 메모**: 매물(유닛) 단위로 즉시 저장(중개사가 매물번호를 바꿔도 **cluster_key** 로 유지)
- **★ 관심단지**(`/shortlist`): 별표한 **단지**만 모아 활성 매물 수·매매 호가대·신규 수로 비교 (이 도구의 최종 목적)
- **이력**: 매물(유닛)의 가격 변동 스파크라인
- **추적단지**: 단지번호로 **추적 추가**(등록 후 즉시 첫 수집) / **추적 해제**(config 고정 단지도 정기 수집에서 제외, 기존 매물·관심표시는 보존). `config.yaml` 을 직접 고치지 않아도 됩니다.
- **지금 수집** 버튼 / **실행로그**: 스케줄러 건강 상태 확인

## 6. API 검증 (중요)

`probe` 는 헤드리스 브라우저로 토큰을 발급받아 실제 단지 매물을 수집해 봅니다.

```bash
.venv/bin/python -m myhouse.cli probe 947          # 디버그로 브라우저 보기: --no-headless
```
- `수집 N건 (파싱성공 N …) · 완료=True` 와 매물 DTO 가 정상으로 보이면 그대로 `collect` 하면 됩니다.
- 형태가 바뀌면 `src/myhouse/naver/endpoints.py`(요청 URL)·`parser.py`(응답 필드)·`browser.py`(토큰 캡처)
  만 조정하면 됩니다. 네이버 의존 지식은 전부 `naver/` 에 격리돼 있습니다.

## 7. 자동화 (macOS launchd)

```bash
scripts/install_launchd.sh            # 포트 변경: scripts/install_launchd.sh 9000
```
- **대시보드**: 상시 구동(`KeepAlive`) → http://localhost:8765 — 설치 시 `frontend` 를 자동 빌드(`npm ci && npm run build`)
- **수집기(매일, KST)**: 매물 `collector` **08:10** · 실거래 `deals` **09:30** · 토지거래허가 `permits` **11:00** ·
  법원경매 `auctions` **11:30** — 시간 변경은 각 `scripts/launchd/com.myhouse.*.plist` 의 `StartCalendarInterval` 수정 후 재설치
- **신규편입 탐색**: 매주 월요일 **09:00** (`com.myhouse.discover`)
- **텔레그램 봇**: 상시 구동(`KeepAlive`, 롱폴링) — `com.myhouse.bot`. 로그: `tail -f logs/bot.err`. → [12. 텔레그램 봇](#12-텔레그램-봇--양방향-명령)
- 상태: `launchctl list | grep myhouse` · 수동 트리거: `launchctl kickstart gui/$(id -u)/com.myhouse.collector`
- 해제: `scripts/uninstall_launchd.sh`

> **절전 주의**: 예약 시각에 맥이 꺼져/잠들어 있으면 누락분을 큐잉하지 않고 **깨어날 때 1회만** 실행됩니다.
> 디바운스를 경과 '시간' 기준으로 설계해 지연 실행에도 안전합니다. 정시 기상을 원하면(관리자 권한):
> `sudo pmset repeat wakeorpoweron MTWRFSU 08:05:00`

## 8. 동작 원리 (정확성 포인트)

- **수명주기**: 매물은 `article_no` 기준으로 NEW → (가격변동) → 미노출 시 **PENDING_REMOVAL** →
  `removal_debounce_hours`(기본 20h, =실제 2회 연속 미노출) 경과 후 **REMOVED(거래완료 추정)**.
- **안전 규칙**: 수집이 **불완전**(차단/타임아웃)한 단지는 **삭제 판정을 전면 생략** → 일시적 오류가
  스냅샷을 통째로 "거래완료"로 오염시키지 않습니다.
- **다중 중개사 dedup**: 같은 유닛(평형·층·향·거래유형)을 여러 중개사가 다른 가격으로 올리면
  **cluster_key**(가격 제외, 평형 `areaName` 기준)로 묶어 "중개 N곳, 최저~최고가" 로 표시·알림합니다. 제외/메모는 cluster_key 기준, **관심(별표)은 단지(complex) 기준**입니다.
- **토큰/차단 우회**: new.land 토큰은 3시간마다 만료되고 봇/rate 차단이 강해, 실행마다 **헤드리스 브라우저
  (Playwright)** 가 토큰을 자동 발급하고 같은 브라우저 컨텍스트로 API 를 호출(`naver/browser.py`).
- **단지 주소 자동 조회**: 단지를 처음 수집할 때 `/api/articles/{articleNo}` 상세 응답의 `exposureAddress`
  (예: "서울시 동작구 상도동")를 `complex.address` 에 저장합니다. 이후 수집에서는 DB 캐시를 사용하며,
  텔레그램 알림 헤더에 단지명 옆에 이탤릭으로 표시됩니다.

## 9. 개발

```bash
.venv/bin/python -m pytest -q       # 백엔드: parser/diff/dedup/digest/collector/web/regions + 실거래·허가·경매·급매 + 봇
.venv/bin/ruff check src tests      # 백엔드 린트
( cd frontend && npm run test )     # 프론트엔드: vitest
( cd frontend && npm run lint )     # 프론트엔드 린트(eslint)
```
구조(`src/myhouse/`):
- `naver/` — new.land 연동·Playwright·격리(매물 `parser`·실거래 `deal_parser`·지역마커 `regions`·검색 `search_parser`)
- `seoul/`·`gyeonggi/`·`court/` — 토지거래허가(서울 `land.seoul.go.kr` / 경기 과천)·법원경매(`courtauction.go.kr`) 클라이언트
- `db/` — SQLModel 스키마(매물·실거래 `deal`·토지거래허가 `land_permit`·경매 `auction`·급매 `flash_deal`·탐색후보 등)
- `core/` — diff·collector(매물·실거래·허가·경매), 급매 탐지 `flash`, 주간탐색 `discover`, 봇 단건 `on_demand`
- `notify/` — 다이제스트(`digest`·`deal_digest`·`permit_digest`·`auction_digest`·`discover_digest`)·봇 응답 `reply`·`telegram`
- `web/` — FastAPI **JSON API**(`/api/*`) + **React SPA**(루트 `/`). 프론트 소스는 `frontend/`(Vite+React+TS, FSD 구조)
- `bot/` — 롱폴링 `runner`·명령 `commands`

## 10. 한계 / 주의

- 비공식 API 사용은 네이버 ToS 와 충돌할 수 있습니다. **개인적·소규모**로만 사용하고 과도한 호출을 피하세요.
- **해외 IP는 차단** 경향이 있어 한국에서 실행하세요(프록시 불필요).
- 토큰은 실행마다 새로 발급되므로 `.env` 에 네이버 토큰을 넣을 필요는 없습니다(텔레그램 토큰만).
- new.land 가 토큰 발급 방식/응답 구조를 바꾸면 `naver/browser.py`·`parser.py` 수리가 필요할 수 있습니다.

## 11. 실거래가 (국토부)

매물(호가)이 "팔겠다는 가격"이라면, **실거래가**는 **국토부에 신고된 실제 체결가**입니다. 매물과 별개 데이터원
(네이버 `prices/real` 경유, 평형별)이라 **별도 테이블·수집기·화면·알림**으로 분리돼 있습니다.

### 동작
- **수집 단위**: 단지의 평형(`pyeongNo`)별로 매매 실거래를 조회하고, 평형 면적을 거래에 태깅합니다.
  평형 목록(`complexPyeongDetailList`)은 단지당 1회 조회해 `complex.pyeongs_json` 에 캐시합니다.
- **평형 선택**: `defaults` 의 **면적 필터(공급/전용)** 에 맞는 평형만 조회해 호출량을 줄입니다(`use_area_filter`).
- **변화 감지**: 거래는 과거 사실이라 매물 같은 '거래완료' 판정이 없습니다. **신규 신고**와 **거래취소(`deleteYn`)**
  만 추적하며, 자연키(`단지|유형|거래일|층|평형|가격`)로 중복을 제거합니다. 누락(일시적 수집 실패)은 데이터를
  훼손하지 않습니다(다음 회차에 포착).

### 설정 — `config.yaml` 의 `deals:`
```yaml
deals:
  enabled: true              # 실거래 수집·알림 사용 여부
  trade_types: ["SALE"]      # 매매만 — 전세/월세도: ["SALE","JEONSE","WOLSE"]
  years: 3                   # 실거래 조회 기간(년)
  scope: "all"               # all(전체 추적단지) | starred(별표 단지만)
  use_area_filter: true      # defaults 면적필터로 평형 제한(호출량↓)
  notify_on_no_change: false # 신규 0건이어도 알림 보낼지
```

### 사용법
```bash
# 라이브 검증 — 단지 1개의 실거래를 실제 수집해 연동 확인(브라우저 토큰 자동 발급)
.venv/bin/python -m myhouse.cli probe-deals 947          # 디버그: --no-headless

# 수동 1회 수집(+텔레그램 다이제스트 미리보기)
.venv/bin/python -m myhouse.cli collect-deals --trigger manual

# 화면: 대시보드 상단 '실거래가' 탭 → http://localhost:8765/deals
#   필터(단지·구/동·기간·면적·취소포함)·정렬(거래일/가격), 단지 상세에도 실거래 섹션 표시
```

### 자동화
`scripts/install_launchd.sh` 가 매물 수집기(08:10)에 더해 **실거래 수집기를 매일 09:30 (KST)** 로 등록합니다
(`com.myhouse.deals`). 수동 트리거: `launchctl kickstart gui/$(id -u)/com.myhouse.deals`.

> ⚠️ **호출량**: 전체 추적 단지(`scope: all`)를 평형별로 조회하므로 매물 수집과 비슷한 규모의 호출이 하루 1회
> 추가됩니다. 차단이 우려되면 `scope: starred`(별표 단지만) 로 좁히세요. 실거래 API 가 막히거나 구조가 바뀌면
> `naver/endpoints.py`(URL)·`deal_parser.py`(응답 필드)만 수리하면 됩니다.

## 12. 텔레그램 봇 — 양방향 명령

정기 수집/알림(push)에 더해, **텔레그램에서 직접 명령**을 보내 원할 때 바로 조회하는 양방향 봇입니다.

**접근 제어(지인 소수 개방)** — 두 갈래로 게이트합니다(둘 다 비우면 전체 허용·역호환):
- **운영자 앵커**: `.env` 의 `TELEGRAM_ALLOWLIST`(쉼표 구분 chat_id)에 든 사람은 항상 사용 가능.
- **초대코드 셀프등록**: `.env` 의 `TELEGRAM_JOIN_CODE` 를 정해두면, **지인은 chat_id 를 몰라도 봇에 `/join <코드>` 한 번이면 자동 등록**(DB 저장)됩니다. 운영자는 친구에게 코드만 알려주면 되고, 친구마다 `.env` 를 고칠 필요가 없습니다. 미승인 chat 은 `/join` 외 명령이 막히고 가입 안내만 받습니다.

### 명령
| 명령 | 동작 |
|---|---|
| `/join 초대코드` | **초대코드로 봇 참여**(자동 등록). 미승인 사용자가 가장 먼저 보내는 명령 |
| `/add 1234 [별칭]` | 단지를 **추적 목록에 추가**(매일 정기 수집에 포함) + **즉시 1회 수집**해 현재 매물 표시 |
| `/add 방배 삼호1차` | **단지명·주소로 검색**해 단지번호를 역추적하여 추가(번호를 몰라도 됨) |
| `/check 1234` · `/check 도곡렉슬` · `/check 방배 삼호1차` | 그 단지 매물을 **즉시 갱신**하고 **변동(신규/가격변동/거래완료) + 현재 매물** 표시(번호·이름·주소) |
| `/deals 1234` 또는 `/deals 방배 삼호1차` | 그 단지 **실거래를 즉시 갱신**하고 최근 거래 표시(번호·이름·주소) |
| `/band 7 12` | **정기 알림을 받을 관심 가격대(억)** 설정 — 이 가격대의 매물·실거래·신규단지만 push. `/band`=현재 보기, `/band 15`=15억↑, `/band 0 12`=12억↓, `/band off`=전체 |
| `/list` | 텔레그램으로 추가한 추적 단지 목록 |
| `/help` | 도움말 |

> **구독자별 가격밴드**: 봇을 여러 사람이 쓸 때, 수집·diff 는 전역 1회로 끝내고 **정기 push 다이제스트를 발송 직전에 각 구독자의 `/band` 가격대로 필터**합니다(가격은 매물 속성이라 단지 분리가 아니라 알림 시점 필터가 맞음). 자기 밴드에 해당 변동이 없는 구독자는 그 회차 알림을 건너뜁니다. 가격이 없는 **토지거래허가(`/permits`)** 알림은 밴드와 무관하게 전체 발송됩니다.

- **번호·단지명·주소 어느 것으로도** 조회됩니다(`/check`·`/deals`·바로 입력). 먼저 추적/이미 본 단지에서 **로컬로 빠르게** 찾고,
  없으면 new.land 검색(`/api/search`)으로 **역추적**합니다 — 1건이면 바로 처리, 여러 건이면 후보를 번호와 함께 보여주니 `/명령 번호` 로 고릅니다.
- **주소/단지명으로 추가**: `/add` 의 인자가 **숫자가 아니면** 같은 검색으로 단지를 찾아 추가합니다.
  검색은 단지명/지역명 기준이라 **단지명을 포함**하면 가장 잘 맞습니다(순수 지번만으로는 못 찾을 수 있음 — 그땐 번호로). 검증: `myhouse probe-search "방배 삼호1차"`.
- **추적 목록에 없는 번호**로 `/check` 하면 **1회만 조회해 보여주고 추적하지는 않습니다**(추적하려면 `/add`).
  `/add` 로 추가한 단지는 `source=telegram` 으로 저장돼 **정기 수집에도 자동 포함**됩니다(`config.yaml` 은 그대로).
- 명령마다 헤드리스 브라우저를 새로 띄워 토큰을 발급하므로 응답에 **수 초~수십 초**가 걸립니다(진행 중 안내 메시지를 먼저 보냅니다).
  정기 수집이 진행 중이면(파일락) "잠시 후 다시 시도" 로 안내합니다.

### 실행
```bash
# 수동 실행(포그라운드) — Ctrl-C 로 종료
.venv/bin/python -m myhouse.cli bot

# 상시 구동: scripts/install_launchd.sh 가 com.myhouse.bot (KeepAlive) 로 등록합니다.
launchctl kickstart -k gui/$(id -u)/com.myhouse.bot   # 재기동
tail -f logs/bot.err                                   # 로그
```

> 구조: `bot/`(롱폴링 `runner` + 명령 파싱·디스패치 `commands`) · `core/on_demand.py`(단건 추가/매물/실거래/주소검색
> 오케스트레이션, 정기 수집기의 `run_*_for` 재사용) · `notify/reply.py`(응답 포매팅) · `notify/telegram.py`(전송 +
> `getUpdates` 롱폴링) · `naver/search_parser.py`(검색 응답 파싱, `/api/search`). 추적 단지는 `core/targets.py` 가 정기 수집에 병합합니다.

## 13. 토지거래허가 · 법원경매 · 급매

매물(호가)·실거래가에 더해, **추적 단지**를 세 갈래로 더 모니터링합니다. 모두 별도 테이블·수집기·다이제스트로
분리돼 있고, 대시보드 `/permits`·`/auctions`·`/flash` 와 텔레그램 알림으로 봅니다.

### 토지거래허가 (`/permits`)
거래허가구역에서 허가가 나면 곧 실거래로 이어지는 **선행신호**입니다. 추적 단지가 속한 구역의 허가 공고를 수집합니다.
- **데이터원**: 서울 25개구 `land.seoul.go.kr`(`seoul/`), 경기 과천 게시판 HWP(`gyeonggi/`).
- **설정**: `config.yaml` 의 `permits:` 섹션. **검증/수집**: `probe-permits`(서울)·`probe-permits-gc`(과천),
  `collect-permits --trigger manual`. **일정**: `com.myhouse.permits` 매일 11:00.

### 법원경매 (`/auctions`)
추적 단지의 **법원경매**(`courtauction.go.kr`) 물건을 순수 httpx 로 수집해 신규/감정가/최저가/매각기일/유찰횟수를 봅니다.
같은 지번에 형제 단지가 둘 이상이면(예: 과천 주공8·9) 동일 물건을 한쪽에만 귀속해 전역 PK 중복을 피합니다.
- **검증/수집**: `probe-auctions`, `collect-auctions --trigger manual`. **일정**: `com.myhouse.auctions` 매일 11:30.

### 급매 (`/flash`)
같은 단지·평형의 **호가 하한을 일정 % 이상 밑도는** 매물을 수집 시점에 '급매'로 탐지합니다(신규 진입 + 가격 인하 두 트리거).
별도 수집기 없이 **매물 수집(`collect`) 안에서 탐지**되며 `flash_deal` 에 적재됩니다.
- **설정**: `config.yaml` 의 `flash:` 섹션(하락률 임계 등). 화면: `/flash`(트리거·기간·구/동 필터), 텔레그램 🔥급매 섹션.
