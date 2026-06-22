#!/usr/bin/env bash
# launchd 사용자 에이전트 설치.
#
# 사용: scripts/install_launchd.sh [PROFILE [CONFIG [PORT]]]
#
#   PROFILE  식별자 (기본: main)
#            "main" → com.myhouse.*        logs/         08:10/09:30/11:00/월09:00
#            기타   → com.myhouse.PROFILE.*  logs/PROFILE/ 08:40/10:00/11:30/월09:30
#   CONFIG   설정 파일 경로 (기본: config.yaml)
#   PORT     대시보드 포트 (기본: 8765)
#
# 예:
#   scripts/install_launchd.sh                           # 기존과 동일
#   scripts/install_launchd.sh 0715 config.0715.yaml 8766
set -euo pipefail

PROFILE="${1:-main}"
CONFIG="${2:-config.yaml}"
PORT="${3:-8765}"

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_BIN="$PROJECT/.venv/bin"
PYTHON="$VENV_BIN/python"
SRC="$PROJECT/scripts/launchd"
DEST="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

if [[ ! -x "$PYTHON" ]]; then
  echo "❌ venv 파이썬이 없습니다: $PYTHON"
  echo "   먼저: python3.12 -m venv .venv && .venv/bin/pip install -e ."
  exit 1
fi

# 프론트엔드(React SPA) 빌드 → src/myhouse/web/dist (FastAPI 가 루트 / 에 서빙).
# dist 는 .gitignore 대상이라 배포 시 매번 새로 빌드한다.
FRONTEND="$PROJECT/frontend"
if [[ -d "$FRONTEND" ]]; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  # shellcheck disable=SC1091
  [[ -s "$NVM_DIR/nvm.sh" ]] && \. "$NVM_DIR/nvm.sh"
  if command -v npm >/dev/null 2>&1; then
    echo "📦 프론트엔드 빌드…"
    ( cd "$FRONTEND" && npm ci && npm run build )
  else
    echo "⚠ npm 을 찾지 못해 SPA 빌드를 건너뜁니다 — 대시보드 / 가 비어 보일 수 있습니다."
    echo "  Node 설치 후 수동 빌드: (cd frontend && npm ci && npm run build)"
  fi
fi

# 프로파일별 설정
if [[ "$PROFILE" == "main" ]]; then
  LABEL_PREFIX="com.myhouse"
  LOG_DIR="$PROJECT/logs"
  COLLECTOR_HOUR=8;  COLLECTOR_MINUTE=10
  DEALS_HOUR=9;      DEALS_MINUTE=30
  PERMITS_HOUR=11;   PERMITS_MINUTE=0
  AUCTIONS_HOUR=11;  AUCTIONS_MINUTE=30
  DISCOVER_HOUR=9;   DISCOVER_MINUTE=0
else
  LABEL_PREFIX="com.myhouse.$PROFILE"
  LOG_DIR="$PROJECT/logs/$PROFILE"
  COLLECTOR_HOUR=8;  COLLECTOR_MINUTE=40
  DEALS_HOUR=10;     DEALS_MINUTE=0
  PERMITS_HOUR=11;   PERMITS_MINUTE=30
  AUCTIONS_HOUR=12;  AUCTIONS_MINUTE=0
  DISCOVER_HOUR=9;   DISCOVER_MINUTE=30
fi

mkdir -p "$DEST" "$LOG_DIR"

render() {
  local job="$1"
  local out="${LABEL_PREFIX}.${job}.plist"
  sed -e "s|__PYTHON__|$PYTHON|g" \
      -e "s|__VENV_BIN__|$VENV_BIN|g" \
      -e "s|__PROJECT__|$PROJECT|g" \
      -e "s|__PORT__|$PORT|g" \
      -e "s|__CONFIG__|$CONFIG|g" \
      -e "s|__LABEL_PREFIX__|$LABEL_PREFIX|g" \
      -e "s|__LOG_DIR__|$LOG_DIR|g" \
      -e "s|__COLLECTOR_HOUR__|$COLLECTOR_HOUR|g" \
      -e "s|__COLLECTOR_MINUTE__|$COLLECTOR_MINUTE|g" \
      -e "s|__DEALS_HOUR__|$DEALS_HOUR|g" \
      -e "s|__DEALS_MINUTE__|$DEALS_MINUTE|g" \
      -e "s|__PERMITS_HOUR__|$PERMITS_HOUR|g" \
      -e "s|__PERMITS_MINUTE__|$PERMITS_MINUTE|g" \
      -e "s|__AUCTIONS_HOUR__|$AUCTIONS_HOUR|g" \
      -e "s|__AUCTIONS_MINUTE__|$AUCTIONS_MINUTE|g" \
      -e "s|__DISCOVER_HOUR__|$DISCOVER_HOUR|g" \
      -e "s|__DISCOVER_MINUTE__|$DISCOVER_MINUTE|g" \
      "$SRC/com.myhouse.${job}.plist" > "$DEST/$out"
}

# 재등록(idempotent). KeepAlive 서비스(bot·dashboard)는 bootout 직후 곧바로 bootstrap 하면
# teardown 레이스로 "Bootstrap failed: 5: Input/output error" 가 난다 →
# ① 완전히 사라질 때까지 대기 ② 실패 시 재시도. 한 개 실패가 전체를 막지 않게 한다.
reload_agent() {
  local job="$1"
  local plist="${LABEL_PREFIX}.${job}.plist"
  local label="${LABEL_PREFIX}.${job}"
  render "$job"
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  # teardown 완료 대기(KeepAlive 는 즉시 안 죽음)
  for _ in 1 2 3 4 5 6; do
    launchctl print "gui/$UID_NUM/$label" >/dev/null 2>&1 || break
    sleep 1
  done
  # bootstrap 재시도(teardown 지연 시 EIO)
  for attempt in 1 2 3; do
    if launchctl bootstrap "gui/$UID_NUM" "$DEST/$plist" 2>/dev/null; then
      echo "✅ 등록: $label"
      return 0
    fi
    sleep 2
  done
  echo "⚠ 등록 실패: $label — 수동 확인: launchctl bootstrap gui/$UID_NUM $DEST/$plist"
  return 1
}

for job in dashboard collector deals permits auctions discover bot; do
  reload_agent "$job" || true
done

# 상시 서비스(대시보드·봇)는 즉시 기동
launchctl kickstart -k "gui/$UID_NUM/${LABEL_PREFIX}.dashboard" 2>/dev/null || true
launchctl kickstart -k "gui/$UID_NUM/${LABEL_PREFIX}.bot" 2>/dev/null || true

echo
echo "프로파일:     $PROFILE  (config=$CONFIG)"
echo "대시보드:     http://localhost:$PORT"
echo "텔레그램 봇:  상시 구동(롱폴링) — 텔레그램에서 /help 로 명령 확인"
echo "매물 일정:    매일 ${COLLECTOR_HOUR}:$(printf '%02d' $COLLECTOR_MINUTE) (KST)"
echo "실거래 일정:  매일 ${DEALS_HOUR}:$(printf '%02d' $DEALS_MINUTE) (KST)"
echo "토지거래허가: 매일 ${PERMITS_HOUR}:$(printf '%02d' $PERMITS_MINUTE) (KST)"
echo "법원경매:     매일 ${AUCTIONS_HOUR}:$(printf '%02d' $AUCTIONS_MINUTE) (KST)"
echo "신규편입 탐색: 매주 월요일 ${DISCOVER_HOUR}:$(printf '%02d' $DISCOVER_MINUTE) (KST)"
echo "상태 확인:    launchctl list | grep myhouse"
echo "봇 로그:      tail -f $LOG_DIR/bot.err"
echo "수동 1회:     launchctl kickstart gui/$UID_NUM/${LABEL_PREFIX}.collector"
echo "제거:         scripts/uninstall_launchd.sh $PROFILE"
echo
echo "⚠ 예약 시각에 맥이 잠들어 있으면 깨어날 때 1회만 실행됩니다(누락분 큐잉 안 함)."
echo "  정시 기상을 원하면(관리자 권한): sudo pmset repeat wakeorpoweron MTWRFSU 08:05:00"
