"""
Slack #91-ai-lab 활동 분석기
"""
from __future__ import annotations
import os
import re
from datetime import datetime, timedelta, timezone
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from config import TEAM_MEMBERS, AI_KEYWORDS


def get_slack_client() -> WebClient:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    return WebClient(token=token)


def get_channel_messages(client: WebClient, channel_id: str, hours: int = 24) -> list[dict]:
    """최근 N시간의 채널 메시지 수집"""
    oldest = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    messages = []

    try:
        result = client.conversations_history(
            channel=channel_id,
            oldest=str(oldest),
            limit=200,
        )
        messages = result.get("messages", [])
    except SlackApiError as e:
        print(f"[slack] Error: {e.response['error']}")

    return messages


def get_user_map(client: WebClient) -> dict[str, str]:
    """Slack user ID → display name 매핑"""
    user_map = {}
    try:
        result = client.users_list()
        for member in result.get("members", []):
            if not member.get("is_bot") and not member.get("deleted"):
                uid = member["id"]
                name = (
                    member.get("profile", {}).get("display_name")
                    or member.get("real_name")
                    or member.get("name", "unknown")
                )
                user_map[uid] = name
    except SlackApiError:
        pass
    return user_map


def analyze_messages(messages: list[dict], user_map: dict[str, str]) -> dict:
    """메시지 분석: 누가, 얼마나, 어떤 주제로 대화했는지"""
    analysis = {
        "total_messages": len(messages),
        "by_user": {},
        "ai_mentions": 0,
        "shared_links": [],
        "top_topics": [],
        "active_threads": 0,
    }

    ai_pattern = re.compile("|".join(AI_KEYWORDS), re.IGNORECASE)

    for msg in messages:
        user_id = msg.get("user", "")
        text = msg.get("text", "")
        user_name = user_map.get(user_id, user_id)

        # 사용자별 메시지 수
        if user_name not in analysis["by_user"]:
            analysis["by_user"][user_name] = {
                "messages": 0,
                "ai_mentions": 0,
                "links_shared": 0,
            }
        analysis["by_user"][user_name]["messages"] += 1

        # AI 키워드 감지
        if ai_pattern.search(text):
            analysis["ai_mentions"] += 1
            analysis["by_user"][user_name]["ai_mentions"] += 1

        # 링크 공유
        urls = re.findall(r'https?://[^\s>|]+', text)
        if urls:
            analysis["by_user"][user_name]["links_shared"] += len(urls)
            for url in urls[:3]:
                analysis["shared_links"].append({
                    "user": user_name,
                    "url": url[:100],
                })

        # 스레드 감지
        if msg.get("reply_count", 0) > 0:
            analysis["active_threads"] += 1

    return analysis


def post_to_slack(client: WebClient, channel_id: str, text: str) -> bool:
    """Slack 채널에 메시지 발송"""
    try:
        client.chat_postMessage(
            channel=channel_id,
            text=text,
            mrkdwn=True,
        )
        return True
    except SlackApiError as e:
        print(f"[slack] Post error: {e.response['error']}")
        return False


def collect_slack_activity(channel_id: str, hours: int = 24) -> dict:
    """Slack 채널 활동 수집 및 분석"""
    client = get_slack_client()
    user_map = get_user_map(client)
    messages = get_channel_messages(client, channel_id, hours)
    return analyze_messages(messages, user_map)


if __name__ == "__main__":
    import json
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent.parent / "telegram" / ".env")

    channel_id = os.environ.get("SLACK_AI_LAB_CHANNEL", "")
    data = collect_slack_activity(channel_id)
    print(json.dumps(data, indent=2, ensure_ascii=False))
