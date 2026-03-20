"""
AI Native 워크플로우 주간 리포트
히스토리 데이터 기반 트렌드 분석 + Claude API로 개선 추천 생성

사용법:
  python weekly_report.py           # Slack 발송
  python weekly_report.py --dry-run # 출력만
"""
from __future__ import annotations
import json
import os
import argparse
from datetime import date, timedelta, datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "telegram" / ".env")

from config import TEAM_MEMBERS, KST
from slack_analyzer import get_slack_client, post_to_slack


def load_week_history() -> tuple[list[dict], list[dict]]:
    """이번 주 + 지난 주 히스토리 로드"""
    history_dir = Path(__file__).parent / "history"
    if not history_dir.exists():
        return [], []

    today = date.today()
    this_week = []
    last_week = []

    for i in range(14):
        d = today - timedelta(days=i)
        filepath = history_dir / f"{d.isoformat()}.json"
        if filepath.exists():
            with open(filepath) as f:
                record = json.load(f)
                if i < 7:
                    this_week.append(record)
                else:
                    last_week.append(record)

    return this_week, last_week


def aggregate_week(days: list[dict]) -> dict:
    """주간 데이터 집계"""
    agg = {
        "days_with_data": 0,
        "total_sessions": 0,
        "total_messages": 0,
        "total_tool_calls": 0,
        "total_duration_min": 0,
        "total_commits": 0,
        "total_ai_commits": 0,
        "total_slack_messages": 0,
        "by_member": {},
    }

    for day in days:
        sessions = day.get("claude_sessions", {})
        if sessions:
            agg["days_with_data"] += 1

        for member, stats in sessions.items():
            if member not in agg["by_member"]:
                agg["by_member"][member] = {
                    "sessions": 0, "messages": 0,
                    "tool_calls": 0, "duration_min": 0,
                }
            m = agg["by_member"][member]
            m["sessions"] += stats.get("sessions", 0)
            m["messages"] += stats.get("messages", 0)
            m["tool_calls"] += stats.get("tool_calls", 0)
            m["duration_min"] += stats.get("duration_min", 0)

            agg["total_sessions"] += stats.get("sessions", 0)
            agg["total_messages"] += stats.get("messages", 0)
            agg["total_tool_calls"] += stats.get("tool_calls", 0)
            agg["total_duration_min"] += stats.get("duration_min", 0)

        agg["total_commits"] += day.get("github", {}).get("total_commits", 0)
        agg["total_ai_commits"] += day.get("github", {}).get("ai_commits", 0)
        agg["total_slack_messages"] += day.get("slack", {}).get("total_messages", 0)

    return agg


def calc_change(current: int, previous: int) -> str:
    """변화율 계산"""
    if previous == 0:
        if current > 0:
            return "🆕"
        return "-"
    pct = (current - previous) / previous * 100
    if pct > 0:
        return f"↑{pct:.0f}%"
    elif pct < 0:
        return f"↓{abs(pct):.0f}%"
    return "→"


def generate_rule_based_recommendations(this_week: dict, last_week: dict) -> list[str]:
    """룰 기반 개선 추천 (API 키 불필요)"""
    recs = []

    # 수집률
    coverage = len(this_week["by_member"])
    total = len(TEAM_MEMBERS)
    if coverage < total:
        recs.append(f"데이터 수집률 {coverage}/{total}명 — 미설치 구성원 온보딩이 최우선 과제")

    # 사용량 변화
    if last_week["total_tool_calls"] > 0:
        change = (this_week["total_tool_calls"] - last_week["total_tool_calls"]) / last_week["total_tool_calls"] * 100
        if change > 50:
            recs.append(f"도구 호출 {change:.0f}% 증가 — AI 활용 가속 중. 이 속도를 유지하려면 팀 내 베스트 프랙티스 공유 필요")
        elif change < -20:
            recs.append(f"도구 호출 {abs(change):.0f}% 감소 — 원인 파악 필요 (업무 특성? 도구 불편?)")

    # 개인 편중
    if this_week["by_member"]:
        tools_list = [(m, s["tool_calls"]) for m, s in this_week["by_member"].items()]
        tools_list.sort(key=lambda x: x[1], reverse=True)
        if len(tools_list) >= 2:
            top = tools_list[0][1]
            second = tools_list[1][1]
            if top > second * 5:
                recs.append(f"{tools_list[0][0]}에 사용량이 집중 — {tools_list[0][0]}의 워크플로우를 팀에 공유하면 전체 수준 향상 가능")

    # AI 커밋 비율
    if this_week["total_commits"] > 0:
        ai_pct = this_week["total_ai_commits"] / this_week["total_commits"] * 100
        if ai_pct < 20:
            recs.append(f"AI 커밋 비율 {ai_pct:.0f}% — 커밋 시 Co-Authored-By 태그를 습관화하면 측정 정확도 향상")

    # Slack 활동
    if this_week["total_slack_messages"] < 5:
        recs.append("#ai-lab 대화 저조 — 주 1회 AI 활용 성공 사례 공유를 팀 루틴으로 도입 추천")

    # Productivity Paradox 경고
    if this_week["total_tool_calls"] > 500 and coverage < total / 2:
        recs.append("⚠️ AI Productivity Paradox 주의: 일부만 AI를 활발히 쓰면 팀 워크플로우 병목이 비AI 구간에서 발생")

    return recs[:5] if recs else ["데이터 축적 중 — 다음 주부터 트렌드 기반 추천 시작"]


def generate_ai_recommendations(this_week: dict, last_week: dict, daily_data: list[dict]) -> list[str]:
    """룰 기반 개선 추천 사용. Claude Code 세션에서 AI 추천이 필요하면 weekly_ai_review.md 참조."""
    return generate_rule_based_recommendations(this_week, last_week)


def generate_weekly_report(this_agg: dict, last_agg: dict, recommendations: list[str]) -> str:
    """주간 리포트 Slack 메시지 생성"""
    today = date.today()
    week_start = today - timedelta(days=6)
    period = f"{week_start.strftime('%m/%d')}~{today.strftime('%m/%d')}"

    lines = []
    lines.append(f"📈 *AI Native 주간 리포트* — {period}")
    lines.append("")

    # ── 주간 KPI ──
    lines.append("━━━ *주간 핵심 지표* ━━━")

    metrics = [
        ("Claude 세션", this_agg["total_sessions"], last_agg["total_sessions"]),
        ("AI 대화", this_agg["total_messages"], last_agg["total_messages"]),
        ("도구 호출", this_agg["total_tool_calls"], last_agg["total_tool_calls"]),
        ("AI 사용(분)", this_agg["total_duration_min"], last_agg["total_duration_min"]),
        ("GitHub 커밋", this_agg["total_commits"], last_agg["total_commits"]),
        ("AI 커밋", this_agg["total_ai_commits"], last_agg["total_ai_commits"]),
    ]

    for label, current, previous in metrics:
        change = calc_change(current, previous)
        lines.append(f"  {label}: *{current}* ({change})")

    lines.append(f"  데이터 수집률: *{len(this_agg['by_member'])}/{len(TEAM_MEMBERS)}*명")
    lines.append("")

    # ── 구성원별 ──
    lines.append("━━━ *구성원별 활용* ━━━")

    if this_agg["by_member"]:
        sorted_members = sorted(
            this_agg["by_member"].items(),
            key=lambda x: x[1]["tool_calls"],
            reverse=True,
        )
        for member, stats in sorted_members:
            # 지난 주 대비
            prev = last_agg["by_member"].get(member, {})
            tool_change = calc_change(stats["tool_calls"], prev.get("tool_calls", 0))

            level = "🟢" if stats["tool_calls"] > 100 else "🟡" if stats["tool_calls"] > 20 else "🔵"
            lines.append(
                f"  {level} *{member}*: {stats['sessions']}세션 | "
                f"{stats['tool_calls']}도구 ({tool_change}) | "
                f"{stats['duration_min']}분"
            )
    else:
        lines.append("  데이터 없음")

    missing = set(TEAM_MEMBERS.values()) - set(this_agg["by_member"].keys())
    if missing:
        lines.append(f"  ⏸ 미수집: {', '.join(missing)}")

    lines.append("")

    # ── AI 개선 추천 ──
    lines.append("━━━ *AI 개선 추천* ━━━")
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"  {i}. {rec}")

    lines.append("")
    lines.append("_주간 자동 리포트 | 대시보드: https://ark-point.github.io/ai-dashboard/_")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AI Native 주간 리포트")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("[weekly] 주간 리포트 생성 시작")

    # 1. 히스토리 로드
    this_week_days, last_week_days = load_week_history()
    this_agg = aggregate_week(this_week_days)
    last_agg = aggregate_week(last_week_days)

    print(f"[weekly] 이번 주: {this_agg['total_sessions']}세션, 지난 주: {last_agg['total_sessions']}세션")

    # 2. AI 개선 추천
    print("[weekly] AI 개선 추천 생성 중...")
    recommendations = generate_ai_recommendations(this_agg, last_agg, this_week_days)

    # 3. 리포트 생성
    report = generate_weekly_report(this_agg, last_agg, recommendations)

    # 4. 발송
    if args.dry_run:
        print("\n" + "=" * 60)
        print(report)
        print("=" * 60)
    else:
        channel_id = os.environ.get("SLACK_AI_LAB_CHANNEL", "")
        if channel_id:
            client = get_slack_client()
            if post_to_slack(client, channel_id, report):
                print("[weekly] ✅ 발송 완료")
            else:
                print("[weekly] ❌ 발송 실패")
                print(report)
        else:
            print(report)


if __name__ == "__main__":
    main()
