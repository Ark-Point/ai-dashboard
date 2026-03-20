#!/bin/bash
# ============================================================
# ARK Point AI Monitor — 설치 스크립트
# 구성원 각자 PC에서 한 번만 실행하면 됩니다.
#
# 설치 명령:
#   curl -sL https://raw.githubusercontent.com/Ark-Point/ark-agents/main/ai-monitor/install.sh | bash
#   또는
#   cd ~/Documents/ark_point/repos/ark-agents && bash ai-monitor/install.sh
# ============================================================

set -euo pipefail
trap 'echo "❌ 설치 실패 (line $LINENO). 오류를 확인하고 다시 시도해 주세요."' ERR

echo "🔧 ARK Point AI Monitor 설치 시작"
echo ""

# 1. ark-agents repo 클론 또는 pull
REPO_DIR="$HOME/Documents/ark_point/repos/ark-agents"
if [ -d "$REPO_DIR" ]; then
    echo "✅ ark-agents repo 발견 — pull"
    cd "$REPO_DIR"
    git stash --quiet 2>/dev/null || true
    if ! git pull --quiet --rebase; then
        echo "⚠️  git pull 실패 — 로컬 변경사항 충돌 가능성이 있습니다."
        echo "   수동으로 확인해 주세요: cd $REPO_DIR && git status"
        exit 1
    fi
else
    echo "📦 ark-agents repo 클론"
    mkdir -p "$HOME/Documents/ark_point/repos"
    cd "$HOME/Documents/ark_point/repos"
    git clone https://github.com/Ark-Point/ark-agents.git
fi

# 2. Python 의존성 설치
echo "📦 Python 의존성 설치"
cd "$REPO_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install -q -r ai-monitor/requirements.txt

# 3. 일일 자동 실행 설정 (cron)
CRON_CMD="cd $REPO_DIR && .venv/bin/python ai-monitor/session_collector.py --hours 24 # ark-ai-monitor"
CRON_SCHEDULE="30 9 * * *"  # 매일 09:30

# 기존 cron 제거 후 추가
(crontab -l 2>/dev/null | grep -v "# ark-ai-monitor" || true; echo "$CRON_SCHEDULE $CRON_CMD") | crontab -

echo ""
echo "✅ 설치 완료!"
echo ""
echo "📊 수집하는 데이터:"
echo "   - 세션 수, 세션 시간, 작업 디렉토리 (홈 경로는 ~로 치환)"
echo "   - 도구 사용 횟수 (Read, Write, Bash 등)"
echo "   - 사용한 스킬 (/deep-research, /commit 등)"
echo "   - 에이전트 사용 유형 (web-dev, backend-architect 등)"
echo "   - ❌ 대화 내용·코드·프롬프트는 수집하지 않습니다"
echo ""
echo "⏰ 매일 09:30에 자동 실행됩니다"
echo ""
echo "🧪 지금 테스트하려면 (push 없이 결과만 확인):"
echo "   cd $REPO_DIR && .venv/bin/python ai-monitor/session_collector.py --dry-run"
echo ""
