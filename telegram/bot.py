from __future__ import annotations
"""
ARK Point Multi-Agent Telegram Bot

Commands:
    /brain   [msg] — Brain Food 글쓰기
    /venture [msg] — 사업 기회 분석
    /atlas   [msg] — Personal Ops
    /ai      [msg] — AI Native 조직
    /archive       — 아카이브 조회

Brain Food 채널 포스트 → writing_samples/telegram/ 자동 저장
"""

import asyncio
import os
import re
import json
from itertools import islice
from pathlib import Path
from datetime import date, timedelta
from dotenv import load_dotenv
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

load_dotenv(Path(__file__).parent / ".env")

HS_ORCHESTRATOR_TOKEN = os.environ["HS_ORCHESTRATOR_TOKEN"]
HS_CHAT_ID            = os.environ["HS_CHAT_ID"]
BRAIN_FOOD_CHANNEL_ID = os.environ.get("BRAIN_FOOD_CHANNEL_ID", "")
SLACK_BOT_TOKEN       = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_AI_LAB_CHANNEL  = os.environ.get("SLACK_AI_LAB_CHANNEL", "")

BASE_DIR    = Path(__file__).parent.parent
AGENTS_DIR  = BASE_DIR / "agents"
ORCHESTRATOR_DIR = BASE_DIR / "hs-orchestrator"
WRITING_DIR = BASE_DIR / "writing_samples"
ARCHIVE_DIR = BASE_DIR / "archive"
CONTEXTS_DIR = BASE_DIR / "contexts"
TASKS_FILE  = BASE_DIR / "atlas" / "tasks.md"

# ── Slack 클라이언트 ─────────────────────────────────────────
try:
    from slack_sdk import WebClient as SlackWebClient
    from slack_sdk.errors import SlackApiError
    slack_client = SlackWebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None
except ImportError:
    slack_client = None

# ── 상태 관리 ──────────────────────────────────────────────
pending_archive: dict[int, dict] = {}   # chat_id → {content, topic}
pending_linkedin: dict[int, str] = {}   # chat_id → content (날짜 대기 중)
current_agent:   dict[int, str]  = {}   # chat_id → agent_name

COMMAND_TO_AGENT = {
    "brain":   "brain",
    "venture": "venture",
    "atlas":   "atlas",
    "ai":      "ai-org",
}

# ── 프롬프트 로딩 ───────────────────────────────────────────
WRITING_PLATFORMS = ("linkedin", "telegram", "essays")


def load_writing_samples() -> str:
    samples = []
    for subdir in WRITING_PLATFORMS:
        sample_dir = WRITING_DIR / subdir
        if not sample_dir.exists():
            continue
        files = _top_n_md(sample_dir, 3)
        for f in files:
            samples.append(f"### [{subdir.upper()}]\n{f.read_text()}")
    if not samples:
        return ""
    return "## 과거 글쓰기 샘플 (스타일 학습용)\n\n" + "\n\n---\n\n".join(samples)


def _top_n_md(directory: Path, n: int = 5) -> list[Path]:
    result: list[Path] = []
    for p in sorted(directory.glob("*.md"), reverse=True):
        if len(result) >= n:
            break
        result.append(p)
    return result


def load_agent_system(agent_name: str) -> str:
    parts = []

    agent_file = AGENTS_DIR / f"{agent_name}.md"
    if agent_file.exists():
        parts.append(agent_file.read_text())

    # partner 메모리 컨텍스트
    for fname in ["SOUL.md", "MEMORY.md"]:
        fpath = ORCHESTRATOR_DIR / fname
        if fpath.exists():
            parts.append(fpath.read_text())

    # 사업별 컨텍스트 파일 로드 (contexts/*.md)
    if CONTEXTS_DIR.exists():
        for ctx_file in sorted(CONTEXTS_DIR.glob("*.md")):
            parts.append(f"## 사업 컨텍스트: {ctx_file.stem}\n{ctx_file.read_text()}")

    # Brain Food: 과거 글 샘플 추가
    if agent_name == "brain":
        samples = load_writing_samples()
        if samples:
            parts.append(samples)

    # 오늘/어제 일기
    for delta in [0, 1]:
        day = date.today() - timedelta(days=delta)
        diary = ORCHESTRATOR_DIR / "memory" / f"{day}.md"
        if diary.exists():
            parts.append(diary.read_text())

    return "\n\n---\n\n".join(parts)


# ── 아카이브 유틸 ───────────────────────────────────────────
ARCHIVE_TAG_RE = re.compile(r"\[ARCHIVE\?\s*([^\]]+)\]", re.IGNORECASE)


def extract_archive_tag(text: str) -> tuple[str, str | None]:
    match = ARCHIVE_TAG_RE.search(text)
    if match:
        topic = match.group(1).strip()
        clean = ARCHIVE_TAG_RE.sub("", text).strip()
        return clean, topic
    return text, None


ARCHIVE_CATEGORIES = ("ideas", "decisions", "notes")
ARCHIVE_CATEGORY_ALIASES = {
    "아이디어": "ideas", "idea": "ideas", "i": "ideas",
    "결정": "decisions", "decision": "decisions", "d": "decisions",
    "노트": "notes", "note": "notes", "n": "notes",
}


def save_to_archive(content: str, topic: str, category: str = "notes") -> Path:
    if category not in ARCHIVE_CATEGORIES:
        category = "notes"
    safe_topic = re.sub(r"[^\w가-힣\s-]", "", topic)[:50].strip().replace(" ", "-")
    filename = f"{date.today()}-{safe_topic}.md"
    cat_dir = ARCHIVE_DIR / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    path = cat_dir / filename
    path.write_text(f"# {topic}\n\n날짜: {date.today()}\n카테고리: {category}\n\n---\n\n{content}")
    return path


def save_writing_sample(text: str, platform: str = "telegram", save_date: date | None = None) -> Path:
    if save_date is None:
        save_date = date.today()
    sample_dir = WRITING_DIR / platform
    sample_dir.mkdir(parents=True, exist_ok=True)
    idx = len(list(sample_dir.glob(f"{save_date}-*.md"))) + 1
    filename = f"{save_date}-{idx:03d}.md"
    path = sample_dir / filename
    path.write_text(f"날짜: {save_date}\n플랫폼: {platform}\n\n---\n\n{text}")
    return path


# ── Agent SDK 헬퍼 ──────────────────────────────────────────
async def _call_claude(system: str, prompt: str) -> str:
    """Claude Max 구독으로 실행 (Agent SDK → Claude Code CLI)"""
    result = ""
    async for msg in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            system_prompt=system,
            allowed_tools=[],
            max_turns=1,
        ),
    ):
        if isinstance(msg, ResultMessage):
            result = msg.result
    return result


# ── 에이전트 실행 ───────────────────────────────────────────
AGENT_LABELS = {
    "brain":   "Brain Food ✍️",
    "venture": "Venture Strategy 📊",
    "atlas":   "Atlas 🗂️",
    "ai-org":  "AI Native Org 🤖",
}


async def run_agent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    agent_name: str,
    user_message: str,
):
    chat_id = update.effective_chat.id
    current_agent[chat_id] = agent_name

    label = AGENT_LABELS.get(agent_name, agent_name)
    await update.message.reply_text(f"⚙️ {label} 처리 중...")

    try:
        system = load_agent_system(agent_name)
        reply = await _call_claude(system, user_message)
        clean_reply, archive_topic = extract_archive_tag(reply)

        if len(clean_reply) > 4000:
            clean_reply = clean_reply[:4000] + "\n\n…(생략)"

        await update.message.reply_text(clean_reply)

        if archive_topic:
            pending_archive[chat_id] = {"content": clean_reply, "topic": archive_topic}
            await update.message.reply_text(
                f"💾 이 내용을 아카이브할까요?\n"
                f"📌 제안 주제: *{archive_topic}*\n\n"
                f"'예' / '아니오' 또는 주제를 수정해서 답해주세요.",
                parse_mode="Markdown",
            )

    except Exception as e:
        await update.message.reply_text(f"오류: {str(e)[:300]}")


# ── 아카이브 응답 처리 ──────────────────────────────────────
async def handle_archive_response(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message: str,
):
    chat_id = update.effective_chat.id
    state = pending_archive.pop(chat_id)
    content = state["content"]
    suggested_topic = state["topic"]

    msg = message.strip().lower()
    if msg in ("아니오", "아니요", "no", "노", "ㄴ"):
        await update.message.reply_text("아카이브 건너뜀.")
        return

    # 카테고리 파싱: "ideas", "decisions", "notes" 또는 별칭 지원
    # 예: "예 ideas", "아이디어", "결정: 파트너십 방향"
    category = "notes"
    topic = suggested_topic if msg in ("예", "yes", "y", "네", "ㅇ") else message.strip()

    parts = message.strip().split(None, 1)
    if parts:
        first = parts[0].lower().rstrip(":")
        resolved = ARCHIVE_CATEGORY_ALIASES.get(first) or (first if first in ARCHIVE_CATEGORIES else None)
        if resolved:
            category = resolved
            topic = parts[1].strip() if len(parts) > 1 else suggested_topic

    try:
        path = save_to_archive(content, topic, category)
        await update.message.reply_text(
            f"✅ 저장: `{category}/{path.name}`", parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"저장 실패: {e}")


# ── Slack 모니터링 ──────────────────────────────────────────
def read_slack_channel(channel_id: str, limit: int = 100) -> str:
    """ai-lab 채널 메시지 + 쓰레드 답글까지 읽어서 텍스트로 반환"""
    if not slack_client or not channel_id:
        return ""
    try:
        result = slack_client.conversations_history(channel=channel_id, limit=limit)
        messages = result["messages"]

        user_cache: dict[str, str] = {}

        def get_username(user_id: str) -> str:
            if not user_id or user_id == "unknown":
                return "unknown"
            if user_id not in user_cache:
                try:
                    info = slack_client.users_info(user=user_id)
                    user_cache[user_id] = info["user"].get("real_name") or info["user"]["name"]
                except Exception:
                    user_cache[user_id] = user_id
            return user_cache[user_id]

        lines = []
        for msg in reversed(messages):
            if msg.get("subtype"):
                continue
            text = msg.get("text", "").strip()
            if not text:
                continue
            user = get_username(msg.get("user", "unknown"))
            lines.append(f"[{user}]: {text}")

            # 쓰레드 답글 읽기
            if msg.get("reply_count", 0) > 0:
                try:
                    thread = slack_client.conversations_replies(
                        channel=channel_id, ts=msg["thread_ts"], limit=20
                    )
                    for reply in thread["messages"][1:]:  # 첫 번째는 부모 메시지라 스킵
                        if reply.get("subtype"):
                            continue
                        rt = reply.get("text", "").strip()
                        if rt:
                            ru = get_username(reply.get("user", "unknown"))
                            lines.append(f"  ↳ [{ru}]: {rt}")
                except Exception:
                    pass

        return "\n".join(lines)
    except Exception as e:
        return f"Slack 읽기 오류: {e}"


async def send_safe(message, text: str):
    """마크다운 파싱 실패 시 plain text로 fallback"""
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            await message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await message.reply_text(chunk)


async def send_safe_bot(bot, text: str):
    """bot.send_message용 send_safe (스케줄러에서 사용)"""
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            await bot.send_message(chat_id=int(HS_CHAT_ID), text=chunk, parse_mode="Markdown")
        except Exception:
            await bot.send_message(chat_id=int(HS_CHAT_ID), text=chunk)


# ── 오케스트레이터 + 익스큐터 ──────────────────────────────────
async def orchestrator_decide(channel_content: str) -> tuple[str, list[dict]]:
    """오케스트레이터: Slack 분석 → 현황 요약 + 실행할 에이전트·지시 결정"""

    prompt = f"""너는 ARK Point AI-Native 전환 오케스트레이터다.
아래 ai-lab 슬랙 채널 내용을 분석하고, 지금 당장 실행해야 할 에이전트 작업을 결정하라.

채널 내용:
{channel_content}

---
아래 JSON 형식으로만 응답하라 (코드블록 없이, 순수 JSON만):
{{
  "status_summary": "현재 팀 AI-Native 전환 진도 2-3문장 요약",
  "tasks": [
    {{
      "agent": "ai-org",
      "reason": "이 액션이 필요한 이유 한 줄",
      "instruction": "에이전트에게 전달할 구체적 지시 (슬랙 컨텍스트 포함)"
    }}
  ]
}}

선택 가능한 agent 값:
- "ai-org": AI Native 전환 실행 (다음 숙제 초안, 팀원 가이드, 자동화 설계)
- "brain": LinkedIn/텔레그램 글 작성
- "venture": 사업 기회 분석
- "atlas": HS 개인 태스크/일정 관리

결정 규칙:
- tasks는 최대 2개 (없으면 빈 배열 [])
- 슬랙에서 실제로 확인된 것만 근거로 삼을 것
- instruction은 에이전트가 바로 실행할 수 있도록 구체적으로"""

    try:
        raw = await _call_claude("", prompt)
        # JSON 코드블록 제거 후 파싱
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`")
        data = json.loads(raw)
        return data.get("status_summary", ""), data.get("tasks", [])
    except Exception as e:
        return f"오케스트레이터 오류: {e}", []


async def execute_agent_task(agent_name: str, instruction: str) -> str:
    """익스큐터: 에이전트 시스템 프롬프트 + 지시 → 결과 텍스트"""
    try:
        system = load_agent_system(agent_name)
        return await _call_claude(system, instruction)
    except Exception as e:
        return f"⚠️ {AGENT_LABELS.get(agent_name, agent_name)} 오류: {e}"


async def run_orchestrator(bot, reply_fn=None, extra_instruction: str = ""):
    """
    전체 오케스트레이터 흐름:
    Slack 읽기 → orchestrator_decide → execute_agent_task × N → 전송

    reply_fn: async fn(text) — 메시지 전송 함수 (cmd에서는 update.message.reply_text, 스케줄러에서는 bot.send_message)
    """

    async def send(text: str):
        if reply_fn:
            await send_safe(reply_fn, text)
        else:
            await send_safe_bot(bot, text)

    # 1. Slack 채널 읽기
    channel_content = await asyncio.to_thread(read_slack_channel, SLACK_AI_LAB_CHANNEL, 100)
    if not channel_content:
        await send("⚠️ Slack ai-lab 채널을 읽을 수 없습니다.")
        return

    # 2. 오케스트레이터: 현황 파악 + 다음 액션 결정
    status_summary, tasks = await orchestrator_decide(channel_content)

    # 현황 헤더 전송
    header = f"📊 *AI-Native 전환 현황*\n\n{status_summary}"
    if tasks:
        task_lines = "\n".join(
            f"• [{AGENT_LABELS.get(t['agent'], t['agent'])}] {t['reason']}"
            for t in tasks
        )
        header += f"\n\n⚡ *오케스트레이터 결정*\n{task_lines}"
    else:
        header += "\n\n✅ 현재 추가 실행 액션 없음"
    await send(header)

    # 3. 익스큐터: 각 태스크 실행
    for task in tasks:
        agent_name = task.get("agent", "")
        instruction = task.get("instruction", "")
        if extra_instruction:
            instruction = f"{extra_instruction}\n\n{instruction}"

        label = AGENT_LABELS.get(agent_name, agent_name)
        await send(f"⚙️ *{label}* 실행 중...")

        result = await execute_agent_task(agent_name, instruction)
        clean_result, archive_topic = extract_archive_tag(result)

        await send(f"*{label} 결과*\n\n{clean_result}")


# ── Atlas 태스크 관리 ────────────────────────────────────────
import re as _re

TASK_LINE_RE = _re.compile(r"^- \[([ x])\] (\d+)\. (.+?) \[(\d{4}-\d{2}-\d{2})\]$")


def _load_tasks() -> list[dict]:
    """tasks.md → [{num, done, content, date}] 리스트"""
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TASKS_FILE.exists():
        TASKS_FILE.write_text("# Atlas Tasks\n\n")
        return []
    tasks = []
    for line in TASKS_FILE.read_text().splitlines():
        m = TASK_LINE_RE.match(line.strip())
        if m:
            tasks.append({
                "done": m.group(1) == "x",
                "num": int(m.group(2)),
                "content": m.group(3),
                "date": m.group(4),
            })
    return tasks


def _save_tasks(tasks: list[dict]):
    lines = ["# Atlas Tasks", ""]
    for t in tasks:
        mark = "x" if t["done"] else " "
        lines.append(f"- [{mark}] {t['num']}. {t['content']} [{t['date']}]")
    lines.append("")
    TASKS_FILE.write_text("\n".join(lines))


async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/task list | add [내용] | done [번호]"""
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return

    args = context.args or []
    sub = args[0].lower() if args else "list"

    if sub == "list" or not args:
        tasks = _load_tasks()
        if not tasks:
            await update.message.reply_text("📋 태스크가 없습니다.\n`/task add [내용]`으로 추가하세요.", parse_mode="Markdown")
            return
        todo = [t for t in tasks if not t["done"]]
        done = [t for t in tasks if t["done"]]
        lines = ["📋 *Atlas Tasks*\n"]
        if todo:
            lines.append("*진행 중*")
            for t in todo:
                lines.append(f"▪️ {t['num']}. {t['content']}")
        if done:
            lines.append("\n*완료*")
            for t in done:
                lines.append(f"✅ ~{t['num']}. {t['content']}~")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif sub == "add":
        content = " ".join(args[1:]).strip()
        if not content:
            await update.message.reply_text("사용법: `/task add [내용]`", parse_mode="Markdown")
            return
        tasks = _load_tasks()
        next_num = max((t["num"] for t in tasks), default=0) + 1
        tasks.append({"done": False, "num": next_num, "content": content, "date": str(date.today())})
        _save_tasks(tasks)
        await update.message.reply_text(f"✅ 태스크 추가: `{next_num}. {content}`", parse_mode="Markdown")

    elif sub == "done":
        if len(args) < 2 or not args[1].isdigit():
            await update.message.reply_text("사용법: `/task done [번호]`", parse_mode="Markdown")
            return
        num = int(args[1])
        tasks = _load_tasks()
        found = False
        for t in tasks:
            if t["num"] == num:
                t["done"] = True
                found = True
                break
        if not found:
            await update.message.reply_text(f"번호 {num}을 찾을 수 없습니다.")
            return
        _save_tasks(tasks)
        await update.message.reply_text(f"✅ 완료: `{num}번` 태스크", parse_mode="Markdown")

    elif sub == "del":
        if len(args) < 2 or not args[1].isdigit():
            await update.message.reply_text("사용법: `/task del [번호]`", parse_mode="Markdown")
            return
        num = int(args[1])
        tasks = _load_tasks()
        tasks = [t for t in tasks if t["num"] != num]
        _save_tasks(tasks)
        await update.message.reply_text(f"🗑️ 삭제: `{num}번` 태스크", parse_mode="Markdown")

    else:
        await update.message.reply_text(
            "사용법:\n`/task list` — 목록\n`/task add [내용]` — 추가\n`/task done [번호]` — 완료\n`/task del [번호]` — 삭제",
            parse_mode="Markdown"
        )


async def cmd_slack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/slack — 오케스트레이터 실행: Slack 분석 → 익스큐터 자동 라우팅"""
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return
    extra = " ".join(context.args) if context.args else ""
    await update.message.reply_text("📡 오케스트레이터 가동 중...")
    await run_orchestrator(None, reply_fn=update.message, extra_instruction=extra)


async def generate_brief() -> str:
    """MEMORY.md + 일기 → 프로젝트별 현황/이전 작업/다음 액션 브리핑"""
    parts: list[str] = []

    memory_path = ORCHESTRATOR_DIR / "MEMORY.md"
    if memory_path.exists():
        parts.append(f"## MEMORY\n{memory_path.read_text()}")

    for delta in [0, 1]:
        day = date.today() - timedelta(days=delta)
        diary = ORCHESTRATOR_DIR / "memory" / f"{day}.md"
        if diary.exists():
            parts.append(f"## 일기 ({day})\n{diary.read_text()}")

    # 최근 decisions 아카이브
    decision_files = _top_n_files(ARCHIVE_DIR / "decisions", 3)
    for f in decision_files:
        parts.append(f"## 결정 기록\n{f.read_text()}")

    context = "\n\n---\n\n".join(parts) if parts else "(컨텍스트 없음)"

    prompt = f"""다음 컨텍스트를 바탕으로 HS에게 아침 브리핑을 작성하라.

{context}

---

형식:
🌅 오전 브리핑 — {date.today()}

진행 중인 프로젝트별로 각각:
**[프로젝트명]**
- 현황: (한 줄)
- 이전까지 한 것: (핵심만)
- 다음 액션: (구체적으로)

마지막에 오늘 집중할 최우선 1가지를 굵게 표시.
불필요한 인사말, 설명 없이 내용만."""

    return await _call_claude("", prompt)


async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/brief — 프로젝트 현황 + 다음 액션 브리핑"""
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return
    await update.message.reply_text("📋 브리핑 생성 중...")
    try:
        brief = await generate_brief()
        await update.message.reply_text(_trunc(brief), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"브리핑 오류: {e}")


async def scheduled_brief(bot):
    """매일 07:00 KST 프로젝트 브리핑"""
    await bot.send_message(
        chat_id=int(HS_CHAT_ID),
        text="📋 *오전 브리핑*",
        parse_mode="Markdown",
    )
    try:
        brief = await generate_brief()
        await bot.send_message(chat_id=int(HS_CHAT_ID), text=_trunc(brief), parse_mode="Markdown")
    except Exception as e:
        await bot.send_message(chat_id=int(HS_CHAT_ID), text=f"브리핑 오류: {e}")


async def scheduled_slack_report(bot):
    """매일 09:00 오케스트레이터 자동 실행"""
    if not SLACK_AI_LAB_CHANNEL:
        return
    await bot.send_message(
        chat_id=int(HS_CHAT_ID),
        text="🌅 *AI-Native 전환 일간 오케스트레이터 시작*",
        parse_mode="Markdown",
    )
    await run_orchestrator(bot)


# ── 커맨드 핸들러 ───────────────────────────────────────────
def _make_cmd(agent_name: str, hint: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != HS_CHAT_ID:
            return
        msg = " ".join(context.args) if context.args else None
        if msg:
            await run_agent(update, context, agent_name, msg)
        else:
            current_agent[update.effective_chat.id] = agent_name
            await update.message.reply_text(hint)
    return handler


cmd_brain   = _make_cmd("brain",   "✍️ Brain Food 활성화. 어떤 글을 쓸까요?\n(포맷: LinkedIn / Telegram / 에세이)")
cmd_venture = _make_cmd("venture", "📊 Venture Strategy 활성화. 어떤 사업 기회를 분석할까요?")
cmd_atlas   = _make_cmd("atlas",   "🗂️ Atlas 활성화. 무엇을 도와드릴까요?")
cmd_ai      = _make_cmd("ai-org",  "🤖 AI Native Org 활성화. 어떤 워크플로우를 개선할까요?")


def _trunc(s: str, n: int = 4000) -> str:
    if len(s) <= n:
        return s
    result = []
    for i, c in enumerate(s):
        if i >= n:
            break
        result.append(c)
    return "".join(result) + "\n\n…(생략)"


def _top_n_files(directory: Path, n: int = 5) -> list[Path]:
    if not directory.exists():
        return []
    result: list[Path] = []
    for p in sorted(directory.glob("*.md"), reverse=True):
        if len(result) >= n:
            break
        result.append(p)
    return result


async def cmd_archive_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return
    lines: list[str] = ["📚 *아카이브*\n"]
    total: int = 0
    emoji_map = {"ideas": "💡", "decisions": "✅", "notes": "📝"}
    for cat in ARCHIVE_CATEGORIES:
        files = _top_n_files(ARCHIVE_DIR / cat)
        if not files:
            continue
        emoji = emoji_map.get(cat, "📄")
        lines.append(f"{emoji} *{cat}* ({len(files)}개)")
        for f in files:
            lines.append(f"  • `{f.stem}`")
        lines.append("")
        total = total + len(files)
    # flat 루트 파일 (이전 방식으로 저장된 것)
    root_files = _top_n_files(ARCHIVE_DIR)
    if root_files:
        lines.append("📄 *기타* (이전 저장)")
        for f in root_files:
            lines.append(f"  • `{f.stem}`")
        total = total + len(root_files)
    if total == 0:
        await update.message.reply_text("아카이브가 비어있습니다.")
        return
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_samples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return
    arg = context.args[0].lower() if context.args else ""
    platforms: list[str] = [arg] if arg in WRITING_PLATFORMS else list(WRITING_PLATFORMS)

    lines: list[str] = []
    for p in platforms:
        files = _top_n_md(WRITING_DIR / p, 10)
        if not files:
            continue
        lines.append(f"*{p.upper()}* ({len(files)}개)")
        for f in files:
            lines.append(f"• `{f.stem}`")
        lines.append("")

    if not lines:
        await update.message.reply_text("저장된 샘플이 없습니다.")
        return
    lines.append("삭제: `/delete [파일명]`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_delete_sample(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("사용법: `/delete [파일명]`\n예: `/delete 2026-03-12-001`", parse_mode="Markdown")
        return

    stem = context.args[0].strip()
    deleted = []
    for p in WRITING_PLATFORMS:
        path = WRITING_DIR / p / f"{stem}.md"
        if path.exists():
            path.unlink()
            deleted.append(f"{p}/{stem}.md")

    if deleted:
        await update.message.reply_text(f"🗑️ 삭제 완료: `{'`, `'.join(deleted)}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"`{stem}.md` 파일을 찾을 수 없습니다.", parse_mode="Markdown")


async def cmd_memo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("사용법: `/memo [내용]`\n예: `/memo 메디컬 첫 클라이언트 미팅 확정`", parse_mode="Markdown")
        return

    text = " ".join(context.args).strip()
    memory_path = ORCHESTRATOR_DIR / "MEMORY.md"
    if not memory_path.exists():
        await update.message.reply_text("MEMORY.md 파일을 찾을 수 없습니다.")
        return

    # Claude가 티어 분류
    tier_raw = await _call_claude("", f"""다음 메모를 메모리 티어로 분류하라.

메모: "{text}"

티어 정의:
- M30: 단기(30일) — 오늘 결정, 이번 주 이슈, 단발성 태스크
- M90: 중기(90일) — 진행 중인 프로젝트, 신사업, 전략적 방향
- M365: 장기(1년) — 핵심 원칙, 조직 구조, 영구적 사실

응답: M30 또는 M90 또는 M365 (한 단어만)""")
    tier = tier_raw.strip().upper()
    if tier not in ("M30", "M90", "M365"):
        tier = "M30"

    TIER_META = {
        "M30":  ("## 📝 M30 : 30일 기억",  30),
        "M90":  ("## 📚 M90 : 90일 기억",  90),
        "M365": ("## 🌳 M365 : 1년 기억", 365),
    }
    marker, days = TIER_META[tier]
    today = date.today()
    expire = today + timedelta(days=days)
    new_line = f"- [{today}] {text} <!-- expires: {expire} -->"

    content = memory_path.read_text()
    if marker in content:
        content = content.replace(marker, f"{marker}\n{new_line}", 1)
    else:
        content += f"\n{new_line}"

    memory_path.write_text(content)
    await update.message.reply_text(f"✅ [{tier}] MEMORY 업데이트: `{text}`", parse_mode="Markdown")


async def cmd_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "사용법: /save [platform] [글 내용]\n\n"
            "예시:\n"
            "/save telegram 글 내용...\n"
            "/save linkedin 글 내용..."
        )
        return

    platform = context.args[0].lower()
    if platform not in WRITING_PLATFORMS:
        await update.message.reply_text(f"플랫폼은 {', '.join(WRITING_PLATFORMS)} 중 하나여야 합니다.")
        return

    text = " ".join(context.args[1:]).strip()
    if not text:
        await update.message.reply_text("글 내용을 입력해주세요.")
        return

    if platform == "linkedin":
        pending_linkedin[update.effective_chat.id] = text
        await update.message.reply_text(
            "📅 날짜를 입력해주세요 (YYYY-MM-DD)\n오늘 날짜로 저장하려면 *오늘* 입력",
            parse_mode="Markdown",
        )
    else:
        try:
            path = save_writing_sample(text, platform=platform)
            await update.message.reply_text(f"✅ 저장: `{path.name}`", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"저장 실패: {e}")


async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if str(query.message.chat.id) != HS_CHAT_ID:
        return
    await query.answer()

    pending_file  = Path("/tmp/claude_pending_approval.json")
    response_file = Path("/tmp/claude_approval_response.txt")

    if not pending_file.exists():
        await query.edit_message_text("⏱️ 이미 처리됐거나 타임아웃된 요청입니다.")
        return

    info = json.loads(pending_file.read_text())

    if query.data == "approval_ok":
        response_file.write_text("ok")
        await query.edit_message_text(
            f"✅ *승인됨*\n툴: `{info['tool_name']}`\n`{info['detail'][:100]}`",
            parse_mode="Markdown"
        )
    else:
        response_file.write_text("no")
        await query.edit_message_text(
            f"❌ *거절됨*\n툴: `{info['tool_name']}`",
            parse_mode="Markdown"
        )


COMMANDS_TEXT = (
    "🤖 *ARK Point 에이전트 명령어*\n\n"
    "*에이전트*\n"
    "/brain `[내용]` — Brain Food 글쓰기 (LinkedIn/Telegram/에세이)\n"
    "/venture `[내용]` — 사업 기회 분석\n"
    "/atlas `[내용]` — Personal Ops (일정·태스크·의사결정)\n"
    "/ai `[내용]` — AI Native 조직 워크플로우 설계\n\n"
    "*태스크 관리*\n"
    "/task list — 태스크 목록\n"
    "/task add `[내용]` — 태스크 추가\n"
    "/task done `[번호]` — 완료 처리\n"
    "/task del `[번호]` — 삭제\n\n"
    "*메모·아카이브*\n"
    "/memo `[내용]` — MEMORY.md에 기록 (M30/M90/M365 자동 분류)\n"
    "/archive — 아카이브 목록 조회\n\n"
    "*글쓰기 샘플*\n"
    "/save `[platform] [내용]` — 샘플 저장 (telegram/linkedin)\n"
    "/samples `[platform]` — 샘플 목록\n"
    "/delete `[파일명]` — 샘플 삭제\n\n"
    "*리포트·슬랙*\n"
    "/brief — 프로젝트 현황 브리핑\n"
    "/slack — 오케스트레이터 실행 (Slack ai-lab 분석)\n\n"
    "/list — 이 명령어 목록"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return
    await update.message.reply_text(COMMANDS_TEXT, parse_mode="Markdown")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return
    await update.message.reply_text(COMMANDS_TEXT, parse_mode="Markdown")


# ── LinkedIn 날짜 응답 처리 ─────────────────────────────────
async def handle_linkedin_date(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message: str,
):
    from datetime import datetime
    chat_id = update.effective_chat.id
    content = pending_linkedin.pop(chat_id)

    msg = message.strip()
    if msg in ("오늘", "today", ""):
        save_date = date.today()
    else:
        try:
            save_date = datetime.strptime(msg, "%Y-%m-%d").date()
        except ValueError:
            await update.message.reply_text(
                "날짜 형식이 올바르지 않습니다. YYYY-MM-DD 또는 *오늘* 입력해주세요.",
                parse_mode="Markdown",
            )
            pending_linkedin[chat_id] = content
            return

    try:
        path = save_writing_sample(content, platform="linkedin", save_date=save_date)
        await update.message.reply_text(f"✅ 저장: `{path.name}`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"저장 실패: {e}")


# ── 메시지 핸들러 ───────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != HS_CHAT_ID:
        return

    msg = update.message
    chat_id = update.effective_chat.id
    message = msg.text or ""

    # 포워드된 메시지 → Brain Food 텔레그램 샘플로 저장
    if msg.forward_origin is not None:
        text = message.strip()
        if text:
            try:
                from telegram import MessageOriginChannel, MessageOriginUser
                origin = msg.forward_origin
                if hasattr(origin, "date") and origin.date:
                    save_date = origin.date.date()
                else:
                    save_date = date.today()
                path = save_writing_sample(text, platform="telegram", save_date=save_date)
                await msg.reply_text(f"✅ 포워드 저장: `{path.name}`", parse_mode="Markdown")
            except Exception as e:
                await msg.reply_text(f"저장 실패: {e}")
        return

    if chat_id in pending_archive:
        await handle_archive_response(update, context, message)
        return

    if chat_id in pending_linkedin:
        await handle_linkedin_date(update, context, message)
        return

    agent = current_agent.get(chat_id, "atlas")
    await run_agent(update, context, agent, message)


# ── Brain Food 채널 자동 저장 ───────────────────────────────
async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BRAIN_FOOD_CHANNEL_ID:
        return
    post = update.channel_post
    if not post or str(post.chat.id) != BRAIN_FOOD_CHANNEL_ID:
        return
    text = post.text or post.caption or ""
    if not text.strip():
        return
    try:
        path = save_writing_sample(text, platform="telegram")
        print(f"[brain-food] 샘플 저장: {path.name}")
    except Exception as e:
        print(f"[brain-food] 저장 실패: {e}")


# ── 봇 실행 ────────────────────────────────────────────────
async def _wait_until(hour: int, minute: int = 0):
    import pytz
    from datetime import datetime
    kst = pytz.timezone("Asia/Seoul")
    while True:
        now = datetime.now(kst)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= target:
            target = target + timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        yield


async def run_daily_scheduler(bot):
    """07:00 브리핑 + 09:00 오케스트레이터 스케줄러"""
    async def brief_loop():
        async for _ in _wait_until(7):
            try:
                await scheduled_brief(bot)
            except Exception as e:
                print(f"[scheduler] 브리핑 오류: {e}")

    async def slack_loop():
        async for _ in _wait_until(9):
            try:
                await scheduled_slack_report(bot)
            except Exception as e:
                print(f"[scheduler] 오케스트레이터 오류: {e}")

    await asyncio.gather(brief_loop(), slack_loop())


def _register_handlers(app):
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("list",    cmd_list))
    app.add_handler(CommandHandler("brain",   cmd_brain))
    app.add_handler(CommandHandler("venture", cmd_venture))
    app.add_handler(CommandHandler("atlas",   cmd_atlas))
    app.add_handler(CommandHandler("ai",      cmd_ai))
    app.add_handler(CommandHandler("archive", cmd_archive_list))
    app.add_handler(CommandHandler("save",    cmd_save))
    app.add_handler(CommandHandler("samples", cmd_samples))
    app.add_handler(CommandHandler("delete",  cmd_delete_sample))
    app.add_handler(CommandHandler("brief",   cmd_brief))
    app.add_handler(CommandHandler("memo",    cmd_memo))
    app.add_handler(CommandHandler("task",    cmd_task))
    app.add_handler(CommandHandler("slack",   cmd_slack))
    app.add_handler(CallbackQueryHandler(handle_approval_callback, pattern="^approval_"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Chat(int(HS_CHAT_ID)),
        handle_message,
    ))
    if BRAIN_FOOD_CHANNEL_ID:
        app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POSTS, handle_channel_post))


if __name__ == "__main__":

    async def _run():
        app = Application.builder().token(HS_ORCHESTRATOR_TOKEN).job_queue(None).build()
        _register_handlers(app)

        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)

            # ── 시작 알림 ──────────────────────────────────────
            slack_status = "✅ Slack 연결됨" if (SLACK_AI_LAB_CHANNEL and slack_client) else "⚠️ Slack 미연결"
            await app.bot.send_message(
                chat_id=int(HS_CHAT_ID),
                text=f"🤖 *ARK 오케스트레이터 시작*\n{slack_status}\n09:00 자동 리포트 활성화",
                parse_mode="Markdown",
            )

            if SLACK_AI_LAB_CHANNEL and slack_client:
                asyncio.create_task(run_daily_scheduler(app.bot))
            print("[bot] ARK Point 에이전트 시스템 시작...")
            await asyncio.Event().wait()  # run forever

    asyncio.run(_run())
