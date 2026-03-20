"""
주간 리더보드 — 매주 월요일 09:00
1. ark-ai-tools GitHub 커밋/wins/skills 집계
2. LEADERBOARD.md 업데이트
3. Slack #91-ai-lab 발송
"""
import os
import json
import subprocess
import urllib.request
from pathlib import Path
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
ARK_TOOLS = Path.home() / "workspace/ai/ark-ai-tools"
TEAM_SIZE = 12
GITHUB_URL = "https://github.com/Ark-Point/ai-tools"


def get_week_range():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday


def get_git_commits(since: date):
    until = since + timedelta(days=7)
    result = subprocess.run(
        ["git", "log", "--format=%an", f"--after={since}", f"--before={until}"],
        cwd=ARK_TOOLS, capture_output=True, text=True
    )
    commits = {}
    for author in result.stdout.splitlines():
        author = author.strip()
        if author:
            commits[author] = commits.get(author, 0) + 1
    return commits


def get_wins(since: date):
    wins_dir = ARK_TOOLS / "wins"
    wins = []
    if not wins_dir.exists():
        return wins
    for f in sorted(wins_dir.glob("*.md")):
        if f.name == "README.md":
            continue
        try:
            parts = f.stem.split("-", 3)
            win_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
            if win_date >= since:
                title = f.read_text().split("\n")[0].replace("#", "").strip()
                author = parts[3].split("-")[0] if len(parts) > 3 else "팀원"
                wins.append(f"[{author.upper()}] {title}")
        except Exception:
            wins.append(f.stem)
    return wins


def get_new_skills(since: date):
    result = subprocess.run(
        ["git", "log", "--name-only", "--format=", "--diff-filter=A", f"--after={since}", "--", "skills/"],
        cwd=ARK_TOOLS, capture_output=True, text=True
    )
    skills = [f.split("/")[-1] for f in result.stdout.splitlines()
              if f.startswith("skills/") and f != "skills/README.md" and f.strip()]
    return list(set(skills))


def get_active_members():
    members_dir = ARK_TOOLS / "members"
    if not members_dir.exists():
        return 0
    return len([d for d in members_dir.iterdir() if d.is_dir()])


def update_leaderboard(monday, commits, wins, new_skills):
    week_str = monday.strftime("%Y-W%V")
    active = get_active_members()

    rows = "\n".join(
        f"| {author} | {count} |"
        for author, count in sorted(commits.items(), key=lambda x: -x[1])
    ) or "| (이번 주 커밋 없음) | 0 |"

    wins_text = "\n".join(f"- {w}" for w in wins) if wins else "- (이번 주 Quick Win 없음)"
    skills_text = "\n".join(f"- `{s}`" for s in new_skills) if new_skills else "- (이번 주 신규 스킬 없음)"

    content = f"""# ARK Point AI Lab — 주간 리더보드

> 마지막 업데이트: {monday} ({week_str})
> GitHub에 올리면 여기 등장합니다 → {GITHUB_URL}

---

## 📊 이번 주 커밋 현황

| 팀원 | 커밋 수 |
|------|--------|
{rows}

---

## 🏅 이번 주 Quick Wins

{wins_text}

---

## 🛠️ 이번 주 신규 공유 스킬

{skills_text}

---

## 👥 참여 현황: {active}/{TEAM_SIZE}명

`members/내이름/` 폴더를 만들면 참여자로 등록됩니다.
"""
    (ARK_TOOLS / "LEADERBOARD.md").write_text(content)
    print(f"[leaderboard] LEADERBOARD.md 업데이트 완료")


def post_to_slack(monday, commits, wins, new_skills):
    active = get_active_members()
    week_str = monday.strftime("%Y년 %-m월 %V주차")

    commit_lines = "\n".join(
        f"• {author}: {count}개"
        for author, count in sorted(commits.items(), key=lambda x: -x[1])
    ) or "• (이번 주 커밋 없음 — 첫 번째가 되어보세요!)"

    wins_text = "\n".join(f"• {w}" for w in wins) if wins else "• (없음)"
    skills_text = "\n".join(f"• `{s}`" for s in new_skills) if new_skills else "• (없음)"

    message = f"""🏆 *ARK Point AI Lab — 주간 현황* ({week_str})

*📊 GitHub 커밋*
{commit_lines}

*🏅 Quick Wins*
{wins_text}

*🛠️ 신규 공유 스킬*
{skills_text}

*👥 참여 현황: {active}/{TEAM_SIZE}명*
> GitHub에 올리면 여기 등장합니다 → {GITHUB_URL}"""

    data = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK, data=data,
        headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req)
    print("[slack] 주간 리포트 발송 완료")


if __name__ == "__main__":
    monday = get_week_range()
    commits = get_git_commits(monday)
    wins = get_wins(monday)
    new_skills = get_new_skills(monday)

    update_leaderboard(monday, commits, wins, new_skills)

    try:
        subprocess.run(["git", "add", "LEADERBOARD.md"], cwd=ARK_TOOLS)
        subprocess.run(
            ["git", "commit", "-m", f"leaderboard: {monday} 주간 업데이트"],
            cwd=ARK_TOOLS, check=True
        )
        subprocess.run(["git", "push"], cwd=ARK_TOOLS, check=True)
    except subprocess.CalledProcessError:
        pass

    post_to_slack(monday, commits, wins, new_skills)
    print("주간 리더보드 완료")
