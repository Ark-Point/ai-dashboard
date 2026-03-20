#!/bin/bash
# ============================================================
# AI Monitor 일일 실행 스크립트 (서버/관리자 전용)
#
# 이 스크립트는 서버 또는 관리자 PC에서만 실행합니다.
# 구성원 PC에서는 install.sh로 설치된 cron이 session_collector.py만 실행합니다.
#
# 역할: 팀 전체 데이터 집계 → 다이제스트 생성 → Slack 발송 → 대시보드 배포
# ============================================================
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

# 5. 매주 금요일이면 주간 리포트
if [ "$(date +%u)" = "5" ]; then
    python "$SCRIPT_DIR/weekly_report.py" >> "$LOG" 2>&1
fi

echo "=== done ===" >> "$LOG"
