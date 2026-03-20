"""
야간 증류 스크립트 — 매일 23:00
1. 오늘 일기 작성 (없으면 생성)
2. M30 → M90 승급 판단 후 MEMORY.md 업데이트
3. 활동 로그 초안 생성 + Telegram 전송 + GitHub push
"""
import os
import json
import subprocess
import urllib.request
import itertools
from pathlib import Path
from datetime import date
from dotenv import load_dotenv
import anthropic

load_dotenv(Path(__file__).parent / ".env")
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

BASE_DIR = Path(__file__).parent.parent
WORKSPACES = {
    "hs-orchestrator": BASE_DIR / "hs-orchestrator",
    "hs-brain":   BASE_DIR / "hs-brain",
}


def distill(agent_name: str, workspace: Path):
    today = date.today()
    diary_path = workspace / "memory" / f"{today}.md"
    memory_path = workspace / "MEMORY.md"

    memory_content = memory_path.read_text() if memory_path.exists() else ""
    diary_content = diary_path.read_text() if diary_path.exists() else ""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=f"당신은 {agent_name}입니다. 오늘 하루를 정리하는 야간 증류 작업을 수행합니다. 한국어로 답변하세요.",
        messages=[{
            "role": "user",
            "content": f"""현재 MEMORY.md:
{memory_content}

오늘 일기 ({today}):
{diary_content if diary_content else "(없음)"}

작업:
1. 오늘 일기가 없으면 MEMORY.md 맥락 기반으로 간단한 일기를 작성해줘 (2-3줄)
2. M30 항목 중 90일 이상 기억할 가치가 있는 것은 M90으로 이동
3. 만료된 M30 항목 제거 (expires 날짜 지난 것)
4. 업데이트된 MEMORY.md 전체를 출력

반드시 아래 형식으로 출력:
DIARY:
(일기 내용, 이미 있으면 "SKIP")

MEMORY:
(업데이트된 MEMORY.md 전체 내용)"""
        }]
    )

    result = response.content[0].text

    if "DIARY:" not in result or "MEMORY:" not in result:
        print(f"[{agent_name}] 파싱 실패 — 스킵")
        return

    diary_part = result.split("DIARY:")[1].split("MEMORY:")[0].strip()
    memory_part = result.split("MEMORY:")[1].strip()

    diary_path.parent.mkdir(exist_ok=True)
    if not diary_path.exists() and diary_part != "SKIP":
        diary_path.write_text(diary_part)
        print(f"[{agent_name}] 일기 작성: {diary_path.name}")

    memory_path.write_text(memory_part)
    print(f"[{agent_name}] MEMORY.md 업데이트 완료")


def git_commit(workspace: Path, agent_name: str):
    today = date.today()
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace, capture_output=True, text=True
        )
        if not result.stdout.strip():
            print(f"[{agent_name}] 변경사항 없음 — 커밋 스킵")
            return
        subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"nightly: {today} 야간 증류"],
            cwd=workspace, check=True
        )
        subprocess.run(["git", "push"], cwd=workspace, check=True)
        print(f"[{agent_name}] git commit + push 완료")
    except subprocess.CalledProcessError as e:
        print(f"[{agent_name}] git 오류: {e}")


def draft_activity_log(today: date, msg_count: int, commit_count: int) -> str:
    """Claude가 오늘 활동 로그 초안 작성"""
    orchestrator_ws = WORKSPACES["hs-orchestrator"]
    memory_content: str = (orchestrator_ws / "MEMORY.md").read_text() if (orchestrator_ws / "MEMORY.md").exists() else ""
    memory_excerpt: str = "\n".join(itertools.islice(memory_content.splitlines(), 40))
    diary_path = orchestrator_ws / "memory" / f"{today}.md"
    diary_content = diary_path.read_text() if diary_path.exists() else ""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system="당신은 HS_Orchestrator입니다. HS의 오늘 활동 로그 초안을 작성합니다. 한국어로, 간결하게.",
        messages=[{
            "role": "user",
            "content": f"""아래 정보를 바탕으로 오늘({today}) 활동 로그 마크다운 초안을 작성해줘.

MEMORY.md 맥락:
{memory_excerpt}

오늘 일기:
{diary_content if diary_content else "(없음)"}

자동화 지표:
- HS_Orchestrator 봇 메시지 처리: {msg_count}건
- 에이전트 Git 커밋: {commit_count}건

형식:
# 활동 로그 — {today} (HS)

## 오늘 한 일
- (일기/맥락 기반으로 추정, 확인 필요)

## 자동화 실행
- 아침 브리핑: ✅
- 야간 증류: ✅

## 지표
- 봇 대화: {msg_count}건
- 에이전트 커밋: {commit_count}건

---
*초안 — /활동수정으로 수정 가능*"""
        }]
    )
    return response.content[0].text


def send_telegram(token: str, chat_id: str, text: str):
    data = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req)


def log_activity():
    """HS 당일 활동 초안 생성 + Telegram 전송 + ark-ai-tools push"""
    today = date.today()
    ark_tools = Path.home() / "Documents/ark_point/repos/ark-agents/ark-ai-tools"

    # 봇 메시지 수
    orchestrator_log = Path("/tmp/hs-orchestrator.log")
    msg_count = sum(
        1 for line in orchestrator_log.read_text().splitlines() if "메시지 수신" in line
    ) if orchestrator_log.exists() else 0

    # 오늘 에이전트 커밋 수
    commit_count = 0
    for ws in WORKSPACES.values():
        result = subprocess.run(
            ["git", "log", "--oneline", "--after=midnight"],
            cwd=ws, capture_output=True, text=True
        )
        commit_count += len([l for l in result.stdout.splitlines() if l.strip()])

    # Claude 초안 생성
    draft = draft_activity_log(today, msg_count, commit_count)

    activity_dir = ark_tools / "activity"
    activity_dir.mkdir(exist_ok=True)
    activity_file = activity_dir / f"{today}-hs.md"
    activity_file.write_text(draft)
    print(f"[activity] 초안 저장: {activity_file.name}")

    # Telegram 전송
    try:
        token = os.environ["HS_ORCHESTRATOR_TOKEN"]
        chat_id = os.environ["HS_CHAT_ID"]
        send_telegram(token, chat_id,
            f"📋 오늘 활동 로그 초안입니다. 확인 후 수정이 필요하면 /활동수정 으로 보내주세요.\n\n{draft[:1500]}"
        )
        print(f"[activity] Telegram 전송 완료")
    except Exception as e:
        print(f"[activity] Telegram 전송 실패: {e}")

    try:
        subprocess.run(["git", "add", "-A"], cwd=ark_tools, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"activity: {today} HS"],
            cwd=ark_tools, check=True
        )
        subprocess.run(["git", "push"], cwd=ark_tools, check=True)
        print(f"[activity] GitHub push 완료")
    except subprocess.CalledProcessError:
        print(f"[activity] 변경사항 없음 또는 오류")


if __name__ == "__main__":
    for name, workspace in WORKSPACES.items():
        print(f"\n[{name}] 야간 증류 시작...")
        distill(name, workspace)
        git_commit(workspace, name)

    log_activity()
    print("\n야간 증류 완료")
