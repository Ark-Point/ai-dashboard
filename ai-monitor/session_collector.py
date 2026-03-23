"""
Claude Code 세션 메타데이터 수집기
각 구성원 PC에서 실행 → 대화 내용 제외, 통계만 추출 → 공유 repo에 push

사용법:
  python session_collector.py              # 최근 24시간 수집 + push
  python session_collector.py --hours 72   # 최근 72시간
  python session_collector.py --dry-run    # push 없이 출력만
"""
from __future__ import annotations

import json
import os
import re
import argparse
import subprocess
import getpass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter
from config import KST

# 알려진 스킬 목록 (슬래시 커맨드 감지용)
KNOWN_SKILLS = {
    "update-config", "keybindings-help", "simplify", "loop", "claude-api",
    "qa", "gov-script", "gov-ref", "gov-proposal", "gov-ppt", "gov-fit",
    "gov-evaluate", "gov-convert", "gov-compare", "gov-analyze",
    "folder-setup", "commit", "review-pr",
}
_SKILL_PATTERN = re.compile(r"<command-name>/?([\w-]+)</command-name>")

MAX_HOURS = 2160  # 최대 수집 기간: 90일


def validate_hours(value: str) -> int:
    """--hours 입력값 검증 (1~168)"""
    try:
        v = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"정수를 입력해 주세요: {value}")
    if v < 1 or v > MAX_HOURS:
        raise argparse.ArgumentTypeError(f"--hours는 1~{MAX_HOURS} 범위여야 합니다 (입력값: {v})")
    return v


def find_session_dirs() -> list[Path]:
    """Claude Code 세션 디렉토리 탐색"""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return []
    session_dirs = []
    for d in claude_dir.iterdir():
        if d.is_dir():
            jsonl_files = list(d.glob("*.jsonl"))
            if jsonl_files:
                session_dirs.append(d)
    return session_dirs


def analyze_session(filepath: Path, cutoff: datetime) -> list[dict]:
    """단일 세션 JSONL 분석 — 날짜별로 분할해서 반환"""
    # 날짜별 카운터
    daily_stats: dict[str, dict] = {}  # date_str -> {counters}
    cwd = ""
    last_ts_any = None

    def _get_day(date_str: str) -> dict:
        if date_str not in daily_stats:
            daily_stats[date_str] = {
                "first_ts": None, "last_ts": None,
                "user_msgs": 0, "assistant_msgs": 0,
                "tool_counter": Counter(), "skill_counter": Counter(),
                "agent_counter": Counter(),
            }
        return daily_stats[date_str]

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # 타임스탬프 파싱
                ts = None
                ts_str = obj.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(KST)
                        last_ts_any = ts
                    except ValueError:
                        pass

                current_date = ts.strftime("%Y-%m-%d") if ts else (last_ts_any.strftime("%Y-%m-%d") if last_ts_any else None)
                if not current_date:
                    continue

                day = _get_day(current_date)
                if ts:
                    if day["first_ts"] is None:
                        day["first_ts"] = ts
                    day["last_ts"] = ts

                # 작업 디렉토리
                if not cwd and obj.get("cwd"):
                    cwd = obj["cwd"]

                msg_type = obj.get("type", "")
                if msg_type == "user":
                    day["user_msgs"] += 1
                    user_content = obj.get("message", {}).get("content", "")
                    if isinstance(user_content, str):
                        text = user_content
                    elif isinstance(user_content, list):
                        text = " ".join(b.get("text", "") for b in user_content if isinstance(b, dict))
                    else:
                        text = ""
                    if text:
                        for match in _SKILL_PATTERN.finditer(text):
                            name = match.group(1)
                            if name in KNOWN_SKILLS:
                                day["skill_counter"][name] += 1
                        slash_match = re.match(r"^/([\w-]+)", text.strip())
                        if slash_match and slash_match.group(1) in KNOWN_SKILLS:
                            day["skill_counter"][slash_match.group(1)] += 1
                elif msg_type == "assistant":
                    day["assistant_msgs"] += 1
                    content = obj.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tool_name = block.get("name", "unknown")
                                day["tool_counter"][tool_name] += 1
                                if tool_name == "Skill":
                                    skill = block.get("input", {}).get("skill", "")
                                    if skill:
                                        day["skill_counter"][skill] += 1
                                if tool_name == "Agent":
                                    agent_type = block.get("input", {}).get("subagent_type", "general")
                                    day["agent_counter"][agent_type] += 1
    except (PermissionError, OSError) as e:
        print(f"[collector] 파일 읽기 실패 (건너뜀): {filepath} — {e}")
        return []

    # 날짜별 결과 생성
    results = []
    for date_str, day in daily_stats.items():
        if not day["last_ts"] or day["last_ts"] < cutoff:
            continue
        duration_min = 0
        if day["first_ts"] and day["last_ts"]:
            duration_min = round((day["last_ts"] - day["first_ts"]).total_seconds() / 60)
        results.append({
            "session_id": filepath.stem,
            "date": date_str,
            "started_at": day["first_ts"].isoformat() if day["first_ts"] else "",
            "ended_at": day["last_ts"].isoformat() if day["last_ts"] else "",
            "duration_min": duration_min,
            "cwd": _anonymize_path(cwd),
            "user_messages": day["user_msgs"],
            "assistant_messages": day["assistant_msgs"],
            "total_tool_calls": sum(day["tool_counter"].values()),
            "tools": dict(day["tool_counter"].most_common(15)),
            "skills_used": dict(day["skill_counter"]),
            "agents_used": dict(day["agent_counter"]),
        })
    return results


def _anonymize_path(path: str) -> str:
    """홈 디렉토리를 ~ 로 치환"""
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def _aggregate_sessions(sessions: list[dict], username: str, hours: int) -> dict:
    """세션 리스트를 하나의 집계 데이터로 변환"""
    total_tool_calls = sum(s["total_tool_calls"] for s in sessions)
    total_user_msgs = sum(s["user_messages"] for s in sessions)
    total_duration = sum(s["duration_min"] for s in sessions)
    all_tools: Counter[str] = Counter()
    all_skills: Counter[str] = Counter()
    for s in sessions:
        all_tools.update(s["tools"])
        all_skills.update(s["skills_used"])

    return {
        "collector_version": "1.1",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "period_hours": hours,
        "summary": {
            "total_sessions": len(sessions),
            "total_user_messages": total_user_msgs,
            "total_tool_calls": total_tool_calls,
            "total_duration_min": total_duration,
            "avg_session_min": round(total_duration / len(sessions)) if sessions else 0,
            "top_tools": dict(all_tools.most_common(10)),
            "skills_used": dict(all_skills),
        },
        "sessions": sessions,
    }


def collect_all_sessions(hours: int = 24) -> dict:
    """모든 프로젝트의 세션 수집 — 날짜별로 그룹화"""
    cutoff = datetime.now(KST) - timedelta(hours=hours)
    username = getpass.getuser()

    all_sessions = []
    session_dirs = find_session_dirs()

    for session_dir in session_dirs:
        project_name = session_dir.name
        for jsonl in sorted(session_dir.glob("*.jsonl"), key=os.path.getmtime, reverse=True):
            sessions = analyze_session(jsonl, cutoff)
            for session in sessions:
                session["project"] = project_name
                all_sessions.append(session)

    # 날짜별 그룹화 (analyze_session이 이미 날짜별로 분할함)
    daily: dict[str, list[dict]] = {}
    for s in all_sessions:
        date_key = s.get("date", datetime.now().strftime("%Y-%m-%d"))
        daily.setdefault(date_key, []).append(s)

    # 날짜별 집계 데이터 생성
    daily_data = {}
    for date_key, sessions in sorted(daily.items()):
        daily_data[date_key] = _aggregate_sessions(sessions, username, hours)

    return daily_data


def save_and_push(daily_data: dict[str, dict], repo_path: str | None = None):
    """날짜별 수집 결과를 공유 repo에 저장하고 push"""
    if not repo_path:
        repo_path = str(Path(__file__).parent.parent)

    if not daily_data:
        print("[collector] 저장할 데이터 없음")
        return

    username = next(iter(daily_data.values()))["username"]

    # 브랜치 확인 — main이 아니면 skip
    try:
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        current_branch = branch_result.stdout.strip()
        if current_branch != "main":
            print(f"[collector] main 브랜치가 아님 ({current_branch}) — push 건너뜀")
            return
    except Exception:
        pass

    # 최신 상태로 pull
    try:
        subprocess.run(
            ["git", "pull", "--rebase", "--quiet"],
            cwd=repo_path, capture_output=True, timeout=30
        )
    except Exception:
        pass

    output_dir = Path(repo_path) / "ai-monitor" / "team-data" / username
    output_dir.mkdir(parents=True, exist_ok=True)

    filepaths = []
    for date_str, data in sorted(daily_data.items()):
        filepath = output_dir / f"{date_str}.json"
        old_umask = os.umask(0o077)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        finally:
            os.umask(old_umask)
        filepaths.append(str(filepath))
        print(f"[collector] 저장: {filepath}")

    # git add + commit + push
    try:
        for fp in filepaths:
            subprocess.run(
                ["git", "add", fp],
                cwd=repo_path, capture_output=True, timeout=10
            )
        commit_result = subprocess.run(
            ["git", "commit", "-m", f"ai-monitor: {username} session data ({len(daily_data)} days)"],
            cwd=repo_path, capture_output=True, timeout=10
        )
        if commit_result.returncode != 0:
            for fp in filepaths:
                subprocess.run(
                    ["git", "reset", "HEAD", fp],
                    cwd=repo_path, capture_output=True, timeout=10
                )
            print("[collector] commit 실패 — staged 변경사항 롤백")
            return

        result = subprocess.run(
            ["git", "push"],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print("[collector] push 완료")
        else:
            stderr = result.stderr or ""
            for pattern in ["username", "password", "token", "credential"]:
                if pattern in stderr.lower():
                    stderr = "[자격증명 관련 오류 — git 인증 설정을 확인하세요]"
                    break
            print(f"[collector] push 실패: {stderr[:200]}")
    except subprocess.TimeoutExpired:
        print("[collector] git 명령 시간 초과 — 네트워크 연결을 확인하세요")
    except Exception as e:
        print(f"[collector] git 오류: {e}")


def main():
    parser = argparse.ArgumentParser(description="Claude Code 세션 메타데이터 수집")
    parser.add_argument("--hours", type=validate_hours, default=24, help="수집 기간 (1~2160시간, 기본: 24)")
    parser.add_argument("--dry-run", action="store_true", help="push 없이 출력만")
    parser.add_argument("--repo", type=str, default=None, help="ark-agents repo 경로")
    args = parser.parse_args()

    print(f"[collector] Claude Code 세션 수집 시작 (최근 {args.hours}시간)")
    daily_data = collect_all_sessions(hours=args.hours)

    # 전체 통계
    total_sessions = sum(d["summary"]["total_sessions"] for d in daily_data.values())
    total_msgs = sum(d["summary"]["total_user_messages"] for d in daily_data.values())
    total_tools = sum(d["summary"]["total_tool_calls"] for d in daily_data.values())
    print(f"[collector] 수집 완료: {total_sessions}세션, {total_msgs}메시지, {total_tools}도구 호출 ({len(daily_data)}일)")

    if args.dry_run:
        for date_str, data in sorted(daily_data.items()):
            s = data["summary"]
            print(f"  {date_str}: {s['total_sessions']}세션, {s['total_user_messages']}메시지, {s['total_tool_calls']}도구")
    else:
        save_and_push(daily_data, args.repo)


if __name__ == "__main__":
    main()
