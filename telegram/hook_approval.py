#!/usr/bin/env python3
"""
Claude Code PreToolUse Hook — Mobile Approval

위험한 툴 실행 전:
- 5분 대기 (Mac에서 볼 기회)
- 5분 후 텔레그램 승인 요청
- 응답 올 때까지 무한 대기 (Claude Code 멈춤)
"""
import json
import sys
import time
import os
import re
from pathlib import Path

# .env 직접 파싱
ENV_FILE = Path(__file__).parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

TOKEN   = os.environ.get("HS_ORCHESTRATOR_TOKEN", "")
CHAT_ID = os.environ.get("HS_CHAT_ID", "")

PENDING_FILE  = Path("/tmp/claude_pending_approval.json")
RESPONSE_FILE = Path("/tmp/claude_approval_response.txt")

WAIT_BEFORE_TELEGRAM = 300  # 5분 대기 후 텔레그램 발송

# ── 위험 패턴 ───────────────────────────────────────────────
DANGEROUS_BASH = [
    r"\brm\s+",
    r"\brm\b.*-[rf]",
    r"git\s+push",
    r"git\s+reset\s+--hard",
    r"git\s+branch\s+-[Dd]",
    r"pkill\b",
    r"kill\s+-9",
    r"DROP\s+TABLE",
    r"DELETE\s+FROM",
    r"truncate\b",
    r"chmod\s+[0-7]*7[0-7]*",
    r":\s*>\s*\S",
]

DANGEROUS_WRITE_PATHS = [".env", "credentials", "secrets", "id_rsa", "token"]


def is_dangerous(tool_name: str, tool_input: dict) -> tuple[bool, str]:
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        for pattern in DANGEROUS_BASH:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True, cmd[:200]
        return False, ""

    if tool_name == "Write":
        path = tool_input.get("file_path", "")
        for sensitive in DANGEROUS_WRITE_PATHS:
            if sensitive in path:
                return True, path
        return False, ""

    return False, ""


def send_telegram(text: str):
    import urllib.request
    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ 승인", "callback_data": "approval_ok"},
                {"text": "❌ 거절", "callback_data": "approval_no"},
            ]]
        }
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=10)


def wait_for_response() -> str:
    """응답 올 때까지 무한 대기"""
    RESPONSE_FILE.unlink(missing_ok=True)
    while True:
        if RESPONSE_FILE.exists():
            decision = RESPONSE_FILE.read_text().strip()
            RESPONSE_FILE.unlink(missing_ok=True)
            return decision
        time.sleep(1)


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool_name  = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    dangerous, detail = is_dangerous(tool_name, tool_input)
    if not dangerous:
        sys.exit(0)

    # 5분 대기 (Mac에서 볼 기회)
    time.sleep(WAIT_BEFORE_TELEGRAM)

    # 텔레그램 발송
    PENDING_FILE.write_text(json.dumps({
        "tool_name": tool_name,
        "detail": detail,
        "timestamp": time.time()
    }))

    try:
        send_telegram(
            f"⚠️ *Claude Code 승인 요청*\n\n"
            f"툴: `{tool_name}`\n"
            f"내용:\n```\n{detail}\n```"
        )
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}", file=sys.stderr)
        PENDING_FILE.unlink(missing_ok=True)
        sys.exit(2)

    # 응답 올 때까지 무한 대기
    decision = wait_for_response()
    PENDING_FILE.unlink(missing_ok=True)

    if decision == "ok":
        sys.exit(0)
    else:
        print(f"🚫 승인 거절", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
