"""
아침 브리핑 스크립트 — 매일 09:00
HS_Orchestrator가 HS에게 Telegram으로 오늘의 브리핑 발송
"""
import os
import asyncio
from pathlib import Path
from datetime import date
from dotenv import load_dotenv
import anthropic
import telegram

load_dotenv(Path(__file__).parent / ".env")
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


async def send_briefing():
    bot = telegram.Bot(token=os.environ["HS_ORCHESTRATOR_TOKEN"])
    chat_id = os.environ["HS_CHAT_ID"]
    today = date.today()

    partner_workspace = Path.home() / "Documents/ark_point/repos/ark-agents/hs-orchestrator"
    memory = (partner_workspace / "MEMORY.md").read_text() if (partner_workspace / "MEMORY.md").exists() else ""
    heartbeat = (partner_workspace / "HEARTBEAT.md").read_text() if (partner_workspace / "HEARTBEAT.md").exists() else ""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system="당신은 HS_Orchestrator, ARK Point 비서실장입니다. 매일 아침 HS에게 간결한 브리핑을 제공합니다. 한국어로 답변하세요.",
        messages=[{
            "role": "user",
            "content": f"""오늘({today}) 아침 브리핑을 작성해줘.

MEMORY.md:
{memory}

HEARTBEAT.md:
{heartbeat}

형식 (이모지 포함, 스크롤 없이 읽을 수 있는 길이):
📅 {today} 아침 브리핑

**오늘의 포커스**
(MEMORY 기반 오늘 집중할 것 1-3개)

**미완료 태스크**
(HEARTBEAT 기반, 없으면 이 섹션 생략)

**한마디**
(짧게 하루 시작 한마디)"""
        }]
    )

    briefing = response.content[0].text
    await bot.send_message(chat_id=chat_id, text=briefing, parse_mode="Markdown")
    print(f"[morning] 브리핑 발송 완료 ({len(briefing)}자)")


if __name__ == "__main__":
    asyncio.run(send_briefing())
