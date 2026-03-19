"""
AI Native 워크플로우 일일 다이제스트
매일 아침 실행 → Claude 세션 로그 + GitHub + Slack 분석 → #91-ai-lab 발송

사용법:
  python daily_digest.py           # 실행 + Slack 발송
  python daily_digest.py --dry-run # 실행만 (발송 안 함)
  python daily_digest.py --hours 48 # 최근 48시간 분석
"""
import os
import json
import argparse
from datetime import date, datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# .env 로드 (telegram/.env 재사용)
load_dotenv(Path(__file__).parent.parent / "telegram" / ".env")

from github_collector import collect_github_activity
from slack_analyzer import collect_slack_activity, post_to_slack, get_slack_client
from config import TEAM_MEMBERS


def load_team_sessions(hours: int) -> dict:
    """team-data/ 디렉토리에서 구성원별 세션 데이터 로드"""
    team_data_dir = Path(__file__).parent / "team-data"
    if not team_data_dir.exists():
        return {}

    today = date.today().isoformat()
    yesterday = (date.today().replace(day=date.today().day - 1)).isoformat() if date.today().day > 1 else today

    sessions = {}
    for user_dir in team_data_dir.iterdir():
        if not user_dir.is_dir():
            continue
        username = user_dir.name
        # 오늘 또는 어제 데이터 찾기
        for date_str in [today, yesterday]:
            filepath = user_dir / f"{date_str}.json"
            if filepath.exists():
                with open(filepath) as f:
                    sessions[username] = json.load(f)
                break

    return sessions


def generate_digest(github: dict, slack: dict, team_sessions: dict, report_date: str) -> str:
    """분석 결과를 Slack 메시지 포맷으로 변환"""
    lines = []
    lines.append(f"📊 *AI Native 워크플로우 일일 리포트* — {report_date}")
    lines.append("")

    # ── Claude 세션 섹션 (메인 지표) ──
    lines.append("━━━ *Claude Code 활용* ━━━")

    if not team_sessions:
        lines.append("세션 데이터 없음 — 설치 스크립트를 실행해주세요")
        lines.append("`cd ~/Documents/ark_point/repos/ark-agents && bash ai-monitor/install.sh`")
    else:
        # 구성원별 세션 요약
        member_stats = []
        for username, data in team_sessions.items():
            summary = data.get("summary", {})
            display_name = _get_display_name(username)
            member_stats.append((display_name, summary))

        member_stats.sort(key=lambda x: x[1].get("total_tool_calls", 0), reverse=True)

        total_sessions = sum(s.get("total_sessions", 0) for _, s in member_stats)
        total_msgs = sum(s.get("total_user_messages", 0) for _, s in member_stats)
        total_tools = sum(s.get("total_tool_calls", 0) for _, s in member_stats)
        total_time = sum(s.get("total_duration_min", 0) for _, s in member_stats)

        lines.append(
            f"팀 합계: *{total_sessions}*세션 | *{total_msgs}*대화 "
            f"| *{total_tools}*도구 호출 | *{total_time}*분"
        )
        lines.append("")

        for name, summary in member_stats:
            sessions = summary.get("total_sessions", 0)
            msgs = summary.get("total_user_messages", 0)
            tools = summary.get("total_tool_calls", 0)
            duration = summary.get("total_duration_min", 0)
            avg = summary.get("avg_session_min", 0)

            # 활용 수준 태그
            if tools > 50:
                level = "🟢"
            elif tools > 10:
                level = "🟡"
            elif sessions > 0:
                level = "🔵"
            else:
                level = "⚪"

            lines.append(
                f"  {level} *{name}*: {sessions}세션 | {msgs}대화 | "
                f"{tools}도구 | {duration}분 (평균 {avg}분/세션)"
            )

            # 주요 스킬 사용
            skills = summary.get("skills_used", {})
            if skills:
                skill_list = [f"/{k}" for k in list(skills.keys())[:3]]
                lines.append(f"      스킬: {', '.join(skill_list)}")

        # 미참여자
        participating = {_get_display_name(u) for u in team_sessions}
        all_names = set(TEAM_MEMBERS.values())
        missing = all_names - participating
        if missing:
            lines.append(f"  ⏸ 미수집: {', '.join(missing)}")

    lines.append("")

    # ── GitHub 섹션 (보조 지표) ──
    lines.append("━━━ *GitHub 커밋* ━━━")

    if github["total_commits"] == 0:
        lines.append("커밋 없음")
    else:
        lines.append(
            f"총 *{github['total_commits']}*커밋 "
            f"| AI 기여: *{github['total_ai_commits']}*개 "
            f"({_pct(github['total_ai_commits'], github['total_commits'])})"
        )
        active_members = [
            (login, info) for login, info in github["by_member"].items()
            if info["total_commits"] > 0
        ]
        if active_members:
            active_members.sort(key=lambda x: x[1]["total_commits"], reverse=True)
            parts = []
            for login, info in active_members[:5]:
                name = info["display_name"]
                repos = ", ".join(info["repos_active"][:2])
                parts.append(f"{name}({info['total_commits']}, {repos})")
            lines.append(f"  {' | '.join(parts)}")

    lines.append("")

    # ── Slack 섹션 ──
    lines.append("━━━ *#91-ai-lab 대화* ━━━")

    if slack["total_messages"] == 0:
        lines.append("메시지 없음")
    else:
        sorted_users = sorted(
            slack["by_user"].items(),
            key=lambda x: x[1]["messages"],
            reverse=True,
        )
        top_users = [f"{name}({info['messages']})" for name, info in sorted_users[:5]]
        lines.append(
            f"*{slack['total_messages']}*메시지 | AI 관련: *{slack['ai_mentions']}*개 "
            f"| {', '.join(top_users)}"
        )

    lines.append("")

    # ── 인사이트 ──
    lines.append("━━━ *인사이트* ━━━")
    insights = _generate_insights(github, slack, team_sessions)
    for insight in insights:
        lines.append(f"  💡 {insight}")

    if not insights:
        lines.append("  데이터 축적 중 — 내일부터 트렌드 분석 시작")

    lines.append("")
    lines.append("_자동 생성 리포트 | 피드백은 이 스레드에_")

    return "\n".join(lines)


def _get_display_name(username: str) -> str:
    """시스템 username → 표시명"""
    # TEAM_MEMBERS는 GitHub login 기반이므로, OS username 매핑 추가
    os_to_display = {
        "hs": "HS",
        "ann": "Ann",
        "teo": "TEO",
        "freddie": "Freddie",
        "hook": "Hook",
        "jesse": "Jesse",
        "rae": "Rae",
        "mew": "Mew",
        "dooyoung": "두영",
        "harry": "Harry",
        "uno": "Uno",
    }
    return os_to_display.get(username.lower(), username)


def _generate_insights(github: dict, slack: dict, team_sessions: dict) -> list[str]:
    """데이터 기반 인사이트 생성"""
    insights = []

    # 세션 기반 인사이트
    if team_sessions:
        total_members = len(TEAM_MEMBERS)
        active_members = len(team_sessions)

        if active_members < total_members:
            insights.append(
                f"세션 데이터: {total_members}명 중 {active_members}명 수집 완료 — "
                f"나머지 구성원 설치 독려 필요"
            )

        # 도구 사용 다양성
        for username, data in team_sessions.items():
            summary = data.get("summary", {})
            tools = summary.get("top_tools", {})
            skills = summary.get("skills_used", {})
            name = _get_display_name(username)

            if summary.get("total_tool_calls", 0) > 0 and not skills:
                insights.append(f"{name}: 도구는 사용하지만 스킬 미활용 — 스킬 온보딩 추천")

            if summary.get("total_sessions", 0) > 5:
                insights.append(f"{name}: 활발한 사용자 — 베스트 프랙티스 공유 후보")

    # GitHub 인사이트
    if github["total_commits"] > 0:
        ai_pct = github["total_ai_commits"] / github["total_commits"] * 100
        if ai_pct > 0:
            insights.append(f"GitHub AI 기여 커밋 {ai_pct:.0f}%")

    # Slack 인사이트
    if slack["total_messages"] > 10:
        insights.append(f"#ai-lab 활발 ({slack['total_messages']}메시지) — 지식 공유 문화 형성 중")

    return insights[:5]  # 최대 5개


def _pct(part: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{part / total * 100:.0f}%"


def save_history(report_date: str, github: dict, slack: dict, team_sessions: dict, digest: str):
    """리포트 히스토리 저장"""
    history_dir = Path(__file__).parent / "history"
    history_dir.mkdir(exist_ok=True)

    session_summary = {}
    for username, data in team_sessions.items():
        s = data.get("summary", {})
        session_summary[_get_display_name(username)] = {
            "sessions": s.get("total_sessions", 0),
            "messages": s.get("total_user_messages", 0),
            "tool_calls": s.get("total_tool_calls", 0),
            "duration_min": s.get("total_duration_min", 0),
        }

    record = {
        "date": report_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "claude_sessions": session_summary,
        "github": {
            "total_commits": github["total_commits"],
            "ai_commits": github["total_ai_commits"],
            "active_members": sum(
                1 for info in github["by_member"].values()
                if info["total_commits"] > 0
            ),
        },
        "slack": {
            "total_messages": slack["total_messages"],
            "ai_mentions": slack["ai_mentions"],
            "active_users": len(slack["by_user"]),
        },
    }

    filepath = history_dir / f"{report_date}.json"
    with open(filepath, "w") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(f"[history] 저장: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="AI Native 워크플로우 일일 다이제스트")
    parser.add_argument("--dry-run", action="store_true", help="Slack 발송 없이 출력만")
    parser.add_argument("--hours", type=int, default=24, help="분석 기간 (시간)")
    args = parser.parse_args()

    report_date = date.today().isoformat()
    print(f"[digest] {report_date} 다이제스트 생성 (최근 {args.hours}시간)")

    # 1. Claude 세션 데이터 로드
    print("[digest] Claude 세션 데이터 로드...")
    team_sessions = load_team_sessions(hours=args.hours)
    print(f"[digest] 세션 데이터: {len(team_sessions)}명")

    # 2. GitHub 활동
    print("[digest] GitHub 수집...")
    github = collect_github_activity(hours=args.hours)
    print(f"[digest] GitHub: {github['total_commits']}커밋")

    # 3. Slack 활동
    print("[digest] Slack 수집...")
    channel_id = os.environ.get("SLACK_AI_LAB_CHANNEL", "")
    if channel_id:
        slack = collect_slack_activity(channel_id, hours=args.hours)
        print(f"[digest] Slack: {slack['total_messages']}메시지")
    else:
        slack = {"total_messages": 0, "by_user": {}, "ai_mentions": 0, "shared_links": [], "active_threads": 0}

    # 4. 다이제스트 생성
    digest = generate_digest(github, slack, team_sessions, report_date)

    # 5. 히스토리 저장
    save_history(report_date, github, slack, team_sessions, digest)

    # 6. 출력 또는 발송
    if args.dry_run:
        print("\n" + "=" * 60)
        print(digest)
        print("=" * 60)
    else:
        if channel_id:
            client = get_slack_client()
            if post_to_slack(client, channel_id, digest):
                print("[digest] ✅ #91-ai-lab 발송 완료")
            else:
                print("[digest] ❌ 발송 실패")
                print(digest)
        else:
            print(digest)


if __name__ == "__main__":
    main()
