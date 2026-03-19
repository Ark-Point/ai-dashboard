"""
AI Native 워크플로우 대시보드 생성기
history/*.json + team-data/ → dashboard.html
"""
import json
import os
from datetime import date, datetime
from pathlib import Path


def load_history() -> list[dict]:
    """날짜순 히스토리 로드"""
    history_dir = Path(__file__).parent / "history"
    if not history_dir.exists():
        return []
    records = []
    for f in sorted(history_dir.glob("*.json")):
        with open(f) as fh:
            records.append(json.load(fh))
    return records


def load_latest_team_data() -> dict:
    """최신 team-data 로드"""
    team_dir = Path(__file__).parent / "team-data"
    if not team_dir.exists():
        return {}
    result = {}
    for user_dir in team_dir.iterdir():
        if not user_dir.is_dir():
            continue
        files = sorted(user_dir.glob("*.json"), reverse=True)
        if files:
            with open(files[0]) as f:
                result[user_dir.name] = json.load(f)
    return result


def generate_html(history: list[dict], team_data: dict) -> str:
    today = date.today().isoformat()

    # 최신 데이터 추출
    latest = history[-1] if history else {}
    github = latest.get("github", {})
    slack = latest.get("slack", {})
    sessions = latest.get("claude_sessions", {})

    # 팀 전체 집계
    total_sessions = sum(s.get("sessions", 0) for s in sessions.values())
    total_messages = sum(s.get("messages", 0) for s in sessions.values())
    total_tools = sum(s.get("tool_calls", 0) for s in sessions.values())
    total_duration = sum(s.get("duration_min", 0) for s in sessions.values())

    # 히스토리 차트 데이터
    dates = json.dumps([r.get("date", "")[-5:] for r in history])
    commits_data = json.dumps([r.get("github", {}).get("total_commits", 0) for r in history])
    ai_commits_data = json.dumps([r.get("github", {}).get("ai_commits", 0) for r in history])
    slack_data = json.dumps([r.get("slack", {}).get("total_messages", 0) for r in history])
    session_data = json.dumps([
        sum(v.get("sessions", 0) for v in r.get("claude_sessions", {}).values())
        for r in history
    ])
    tool_data = json.dumps([
        sum(v.get("tool_calls", 0) for v in r.get("claude_sessions", {}).values())
        for r in history
    ])

    # 구성원별 상세 데이터
    member_cards = []
    for username, data in team_data.items():
        summary = data.get("summary", {})
        top_tools = summary.get("top_tools", {})
        skills = summary.get("skills_used", {})
        tools_list = list(top_tools.items())[:5]

        tools_bars = ""
        if tools_list:
            max_val = max(v for _, v in tools_list) if tools_list else 1
            for tool, count in tools_list:
                pct = count / max_val * 100
                short_name = tool.replace("mcp__plugin_ouroboros_ouroboros__", "ouroboros:")
                tools_bars += f"""
                <div class="tool-row">
                    <span class="tool-name">{short_name}</span>
                    <div class="tool-bar-bg"><div class="tool-bar" style="width:{pct}%"></div></div>
                    <span class="tool-count">{count}</span>
                </div>"""

        skills_html = ""
        if skills:
            skills_html = '<div class="skills">' + " ".join(
                f'<span class="skill-tag">/{s}</span>' for s in skills.keys()
            ) + '</div>'

        level_class = "high" if summary.get("total_tool_calls", 0) > 50 else "mid" if summary.get("total_tool_calls", 0) > 10 else "low"

        member_cards.append(f"""
        <div class="member-card {level_class}">
            <div class="member-header">
                <h3>{username.upper()}</h3>
                <span class="member-badge">{summary.get('total_sessions', 0)} sessions</span>
            </div>
            <div class="member-stats">
                <div class="stat-item">
                    <div class="stat-value">{summary.get('total_user_messages', 0)}</div>
                    <div class="stat-label">대화</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{summary.get('total_tool_calls', 0)}</div>
                    <div class="stat-label">도구 호출</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{summary.get('total_duration_min', 0)}m</div>
                    <div class="stat-label">총 시간</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{summary.get('avg_session_min', 0)}m</div>
                    <div class="stat-label">평균/세션</div>
                </div>
            </div>
            <div class="tools-section">
                <h4>도구 사용</h4>
                {tools_bars}
            </div>
            {skills_html}
        </div>""")

    members_html = "\n".join(member_cards) if member_cards else '<p class="empty">세션 데이터 수집 대기 중</p>'

    # 미참여자
    from config import TEAM_MEMBERS
    participating = {u.upper() for u in team_data}
    all_names = set(TEAM_MEMBERS.values())
    missing = all_names - participating
    missing_html = ""
    if missing:
        missing_html = f"""
        <div class="missing-section">
            <h4>미수집 구성원</h4>
            <div class="missing-names">{', '.join(missing)}</div>
            <code>cd ~/Documents/ark_point/repos/ark-agents && bash ai-monitor/install.sh</code>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ARK Point AI Native Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
    --bg: #0a0a0f;
    --card: #12121a;
    --border: #1e1e2e;
    --text: #e0e0e8;
    --text-dim: #6b6b7b;
    --accent: #6366f1;
    --accent-glow: rgba(99,102,241,0.15);
    --green: #22c55e;
    --yellow: #eab308;
    --blue: #3b82f6;
    --red: #ef4444;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
}}
.header {{
    text-align: center;
    margin-bottom: 2.5rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
}}
.header h1 {{
    font-size: 1.8rem;
    font-weight: 700;
    background: linear-gradient(135deg, #6366f1, #8b5cf6, #a855f7);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}}
.header .date {{ color: var(--text-dim); margin-top: 0.3rem; font-size: 0.9rem; }}
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
}}
.kpi-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.2rem;
    text-align: center;
}}
.kpi-card .kpi-value {{
    font-size: 2rem;
    font-weight: 700;
    color: var(--accent);
}}
.kpi-card .kpi-label {{
    font-size: 0.8rem;
    color: var(--text-dim);
    margin-top: 0.2rem;
}}
.charts-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
    margin-bottom: 2rem;
}}
.chart-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
}}
.chart-card h3 {{
    font-size: 0.9rem;
    color: var(--text-dim);
    margin-bottom: 1rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}
.section-title {{
    font-size: 1.1rem;
    font-weight: 600;
    margin: 2rem 0 1rem;
    padding-left: 0.5rem;
    border-left: 3px solid var(--accent);
}}
.members-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 1.5rem;
    margin-bottom: 2rem;
}}
.member-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    transition: border-color 0.2s;
}}
.member-card:hover {{ border-color: var(--accent); }}
.member-card.high {{ border-left: 3px solid var(--green); }}
.member-card.mid {{ border-left: 3px solid var(--yellow); }}
.member-card.low {{ border-left: 3px solid var(--blue); }}
.member-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
}}
.member-header h3 {{ font-size: 1.1rem; }}
.member-badge {{
    background: var(--accent-glow);
    color: var(--accent);
    padding: 0.2rem 0.6rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
}}
.member-stats {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.5rem;
    margin-bottom: 1rem;
}}
.stat-item {{ text-align: center; }}
.stat-value {{ font-size: 1.2rem; font-weight: 700; color: var(--text); }}
.stat-label {{ font-size: 0.7rem; color: var(--text-dim); }}
.tools-section h4 {{
    font-size: 0.75rem;
    color: var(--text-dim);
    margin-bottom: 0.5rem;
    text-transform: uppercase;
}}
.tool-row {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.3rem;
    font-size: 0.8rem;
}}
.tool-name {{ width: 90px; text-align: right; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.tool-bar-bg {{ flex: 1; height: 6px; background: var(--border); border-radius: 3px; }}
.tool-bar {{ height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.5s; }}
.tool-count {{ width: 30px; text-align: right; font-weight: 600; font-size: 0.75rem; }}
.skills {{ margin-top: 0.8rem; }}
.skill-tag {{
    display: inline-block;
    background: rgba(34,197,94,0.1);
    color: var(--green);
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    margin: 0.15rem;
    font-family: monospace;
}}
.missing-section {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 2rem;
}}
.missing-section h4 {{ color: var(--text-dim); margin-bottom: 0.5rem; }}
.missing-names {{ color: var(--yellow); margin-bottom: 0.8rem; }}
.missing-section code {{
    display: block;
    background: var(--bg);
    padding: 0.8rem;
    border-radius: 6px;
    font-size: 0.8rem;
    color: var(--green);
    word-break: break-all;
}}
.empty {{ color: var(--text-dim); text-align: center; padding: 2rem; }}
.footer {{
    text-align: center;
    color: var(--text-dim);
    font-size: 0.75rem;
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
}}
@media (max-width: 768px) {{
    .charts-grid {{ grid-template-columns: 1fr; }}
    .members-grid {{ grid-template-columns: 1fr; }}
    body {{ padding: 1rem; }}
}}
</style>
</head>
<body>
<div class="header">
    <h1>ARK Point AI Native Dashboard</h1>
    <div class="date">{today} | AI Native 워크플로우 모니터링</div>
</div>

<div class="kpi-grid">
    <div class="kpi-card">
        <div class="kpi-value">{total_sessions}</div>
        <div class="kpi-label">Claude 세션</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-value">{total_messages}</div>
        <div class="kpi-label">AI 대화</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-value">{total_tools}</div>
        <div class="kpi-label">도구 호출</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-value">{total_duration}m</div>
        <div class="kpi-label">총 AI 사용 시간</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-value">{github.get('total_commits', 0)}</div>
        <div class="kpi-label">GitHub 커밋</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-value">{github.get('ai_commits', 0)}</div>
        <div class="kpi-label">AI 기여 커밋</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-value">{slack.get('total_messages', 0)}</div>
        <div class="kpi-label">#ai-lab 메시지</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-value">{len(team_data)}/{len(TEAM_MEMBERS)}</div>
        <div class="kpi-label">데이터 수집률</div>
    </div>
</div>

<div class="charts-grid">
    <div class="chart-card">
        <h3>Claude 세션 & 도구 호출 트렌드</h3>
        <canvas id="sessionChart"></canvas>
    </div>
    <div class="chart-card">
        <h3>GitHub & Slack 활동</h3>
        <canvas id="activityChart"></canvas>
    </div>
</div>

<h2 class="section-title">구성원별 AI 활용</h2>
<div class="members-grid">
    {members_html}
</div>

{missing_html}

<div class="footer">
    ARK Point AI Native 워크플로우 모니터링 시스템 | 자동 생성
</div>

<script>
const chartOptions = {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: '#6b6b7b', font: {{ size: 11 }} }} }} }},
    scales: {{
        x: {{ ticks: {{ color: '#6b6b7b' }}, grid: {{ color: '#1e1e2e' }} }},
        y: {{ ticks: {{ color: '#6b6b7b' }}, grid: {{ color: '#1e1e2e' }} }}
    }}
}};

new Chart(document.getElementById('sessionChart'), {{
    type: 'line',
    data: {{
        labels: {dates},
        datasets: [
            {{ label: '세션', data: {session_data}, borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', fill: true, tension: 0.3 }},
            {{ label: '도구 호출', data: {tool_data}, borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.1)', fill: true, tension: 0.3 }}
        ]
    }},
    options: chartOptions
}});

new Chart(document.getElementById('activityChart'), {{
    type: 'bar',
    data: {{
        labels: {dates},
        datasets: [
            {{ label: '커밋', data: {commits_data}, backgroundColor: '#3b82f6' }},
            {{ label: 'AI 커밋', data: {ai_commits_data}, backgroundColor: '#8b5cf6' }},
            {{ label: 'Slack', data: {slack_data}, backgroundColor: '#eab308' }}
        ]
    }},
    options: chartOptions
}});
</script>
</body>
</html>"""


def main():
    history = load_history()
    team_data = load_latest_team_data()
    html = generate_html(history, team_data)

    output = Path(__file__).parent / "dashboard.html"
    with open(output, "w") as f:
        f.write(html)
    print(f"[dashboard] 생성 완료: {output}")
    print(f"[dashboard] 브라우저에서 열기: open {output}")


if __name__ == "__main__":
    main()
