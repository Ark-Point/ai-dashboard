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
import argparse
import subprocess
import getpass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter
from config import KST

MAX_HOURS = 168  # 최대 수집 기간: 7일


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


def analyze_session(filepath: Path, cutoff: datetime) -> dict | None:
    """단일 세션 JSONL 분석 — 메타데이터만 추출, 대화 내용 제거"""
    first_ts = None
    last_ts = None
    user_msgs = 0
    assistant_msgs = 0
    tool_counter: Counter[str] = Counter()
    skill_counter: Counter[str] = Counter()
    agent_counter: Counter[str] = Counter()
    cwd = ""

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # 타임스탬프 파싱
                ts_str = obj.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(KST)
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts
                    except ValueError:
                        pass

                # 작업 디렉토리
                if not cwd and obj.get("cwd"):
                    cwd = obj["cwd"]

                msg_type = obj.get("type", "")
                if msg_type == "user":
                    user_msgs += 1
                elif msg_type == "assistant":
                    assistant_msgs += 1
                    content = obj.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tool_name = block.get("name", "unknown")
                                tool_counter[tool_name] += 1

                                # 스킬 감지
                                if tool_name == "Skill":
                                    skill = block.get("input", {}).get("skill", "")
                                    if skill:
                                        skill_counter[skill] += 1

                                # 에이전트 감지
                                if tool_name == "Agent":
                                    agent_type = block.get("input", {}).get("subagent_type", "general")
                                    agent_counter[agent_type] += 1
    except (PermissionError, OSError) as e:
        print(f"[collector] 파일 읽기 실패 (건너뜀): {filepath} — {e}")
        return None

    # cutoff 이전 세션은 제외 (마지막 활동 기준)
    if not last_ts or last_ts < cutoff:
        return None

    duration_min = 0
    if first_ts and last_ts:
        duration_min = round((last_ts - first_ts).total_seconds() / 60)

    return {
        "session_id": filepath.stem,
        "started_at": first_ts.isoformat() if first_ts else "",
        "ended_at": last_ts.isoformat() if last_ts else "",
        "duration_min": duration_min,
        "cwd": _anonymize_path(cwd),
        "user_messages": user_msgs,
        "assistant_messages": assistant_msgs,
        "total_tool_calls": sum(tool_counter.values()),
        "tools": dict(tool_counter.most_common(15)),
        "skills_used": dict(skill_counter),
        "agents_used": dict(agent_counter),
    }


def _anonymize_path(path: str) -> str:
    """홈 디렉토리를 ~ 로 치환"""
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def collect_all_sessions(hours: int = 24) -> dict:
    """모든 프로젝트의 세션 수집"""
    cutoff = datetime.now(KST) - timedelta(hours=hours)
    username = getpass.getuser()

    all_sessions = []
    session_dirs = find_session_dirs()

    for session_dir in session_dirs:
        project_name = session_dir.name
        for jsonl in sorted(session_dir.glob("*.jsonl"), key=os.path.getmtime, reverse=True):
            session = analyze_session(jsonl, cutoff)
            if session:
                session["project"] = project_name
                all_sessions.append(session)

    # 집계
    total_tool_calls = sum(s["total_tool_calls"] for s in all_sessions)
    total_user_msgs = sum(s["user_messages"] for s in all_sessions)
    total_duration = sum(s["duration_min"] for s in all_sessions)
    all_tools: Counter[str] = Counter()
    all_skills: Counter[str] = Counter()
    for s in all_sessions:
        all_tools.update(s["tools"])
        all_skills.update(s["skills_used"])

    return {
        "collector_version": "1.0",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "period_hours": hours,
        "summary": {
            "total_sessions": len(all_sessions),
            "total_user_messages": total_user_msgs,
            "total_tool_calls": total_tool_calls,
            "total_duration_min": total_duration,
            "avg_session_min": round(total_duration / len(all_sessions)) if all_sessions else 0,
            "top_tools": dict(all_tools.most_common(10)),
            "skills_used": dict(all_skills),
        },
        "sessions": all_sessions,
    }


def save_and_push(data: dict, repo_path: str | None = None):
    """수집 결과를 공유 repo에 저장하고 push"""
    if not repo_path:
        repo_path = str(Path(__file__).parent.parent)

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

    output_dir = Path(repo_path) / "ai-monitor" / "team-data" / data["username"]
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = output_dir / f"{date_str}.json"

    # 파일 생성 시 권한 제한 (0o600)
    old_umask = os.umask(0o077)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    finally:
        os.umask(old_umask)

    print(f"[collector] 저장: {filepath}")

    # git add + commit + push
    try:
        subprocess.run(
            ["git", "add", str(filepath)],
            cwd=repo_path, capture_output=True, timeout=10
        )
        commit_result = subprocess.run(
            ["git", "commit", "-m", f"ai-monitor: {data['username']} daily session data ({date_str})"],
            cwd=repo_path, capture_output=True, timeout=10
        )
        if commit_result.returncode != 0:
            # commit 실패 시 staged 상태 롤백
            subprocess.run(
                ["git", "reset", "HEAD", str(filepath)],
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
            # stderr에서 자격증명 관련 패턴 제거
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
    parser.add_argument("--hours", type=validate_hours, default=24, help="수집 기간 (1~168시간, 기본: 24)")
    parser.add_argument("--dry-run", action="store_true", help="push 없이 출력만")
    parser.add_argument("--repo", type=str, default=None, help="ark-agents repo 경로")
    args = parser.parse_args()

    print(f"[collector] Claude Code 세션 수집 시작 (최근 {args.hours}시간)")
    data = collect_all_sessions(hours=args.hours)

    print(f"[collector] 수집 완료: {data['summary']['total_sessions']}세션, "
          f"{data['summary']['total_user_messages']}메시지, "
          f"{data['summary']['total_tool_calls']}도구 호출")

    if args.dry_run:
        print(json.dumps(data["summary"], indent=2, ensure_ascii=False))
    else:
        save_and_push(data, args.repo)


if __name__ == "__main__":
    main()
