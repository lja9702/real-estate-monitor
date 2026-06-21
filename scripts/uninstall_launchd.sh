#!/usr/bin/env bash
# launchd 에이전트 해제·삭제.
# 사용: scripts/uninstall_launchd.sh [PROFILE]   (기본: main)
set -euo pipefail

PROFILE="${1:-main}"
UID_NUM="$(id -u)"
DEST="$HOME/Library/LaunchAgents"

if [[ "$PROFILE" == "main" ]]; then
  LABEL_PREFIX="com.myhouse"
else
  LABEL_PREFIX="com.myhouse.$PROFILE"
fi

for job in dashboard collector deals permits discover bot; do
  label="${LABEL_PREFIX}.${job}"
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  rm -f "$DEST/$label.plist"
  echo "🗑  해제: $label"
done
echo "완료. (DB·로그는 그대로 둡니다)"
