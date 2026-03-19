#!/bin/bash
# AI Monitor 일일 실행 스크립트
# cron에서 호출됨: 매일 09:30 KST

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LOG="$SCRIPT_DIR/run_daily.log"

echo "=== $(date) ===" >> "$LOG"

# 1. 세션 데이터 수집 (로컬)
cd "$REPO_DIR" && source .venv/bin/activate
python "$SCRIPT_DIR/session_collector.py" --hours 24 >> "$LOG" 2>&1

# 2. 일일 다이제스트 생성 + Slack 발송
python "$SCRIPT_DIR/daily_digest.py" --hours 24 >> "$LOG" 2>&1

# 3. 대시보드 HTML 갱신
python "$SCRIPT_DIR/generate_dashboard.py" >> "$LOG" 2>&1

# 4. 대시보드 GitHub Pages 배포
DASH_REPO="/tmp/ai-dashboard"
if [ ! -d "$DASH_REPO" ]; then
    git clone https://github.com/Ark-Point/ai-dashboard.git "$DASH_REPO" >> "$LOG" 2>&1
fi
cp "$SCRIPT_DIR/dashboard.html" "$DASH_REPO/index.html"
cd "$DASH_REPO" && git add index.html && git commit -m "dashboard: $(date +%Y-%m-%d)" && git push >> "$LOG" 2>&1

echo "=== done ===" >> "$LOG"
