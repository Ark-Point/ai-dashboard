# ARK Point AI Agent System — Design Document

> 최종 목표 문서. 이 파일이 시스템 구축의 기준점.
> 작성: 2026-03-12 by HS

---

## Vision

A lightweight multi-agent system to help operate ARK Point in an AI-native way.

- **Not a chatbot.** An operational system with clearly defined agent roles.
- **Primary interface: Telegram** — interact from phone.
- **Goal**: thinking, writing, decision-making, knowledge management.
- **Constraint**: simple, extensible, lightweight Python. No heavy frameworks.

---

## Conceptual Agent Architecture

### Core Roles

| Role | Description |
|---|---|
| **Orchestrator** | Controls workflow. Decides which agent runs next. Breaks requests into structured tasks. |
| **Researcher** | Collects context from internal knowledge and external sources. |
| **Executor** | Produces actual output (documents, analysis, summaries). |
| **Auditor** | Critiques outputs. Checks logic, risks, completeness. |
| **Archive** | Stores structured knowledge for long-term retrieval. |

> Researcher and Auditor: added later.

---

## Executors

### Personal Ops (`/atlas`)
Manages workflow and daily operations.
- Daily briefing
- Meeting preparation
- Task summarization

### New Venture Strategy (`/venture`)
Evaluates business ideas and opportunities.
- Analyze startup ideas
- Design validation experiments
- Evaluate market opportunities

### AI Native Organization (`/ai`)
Designs automation and improves internal workflows.
- Propose automation ideas
- Design AI workflows
- Improve team processes

### Brain Food (`/brain`)
Writing agent trained on HS's past writing style.
- Generate posts from ideas or bullet points
- Rewrite drafts in HS's voice
- Output formats: LinkedIn / Telegram / Essays / Threads
- Loads `writing_samples/` as few-shot style examples

---

## Memory & Archive

```
archive/
  ideas/
  decisions/
  notes/
```

- Markdown files only. No database.
- Store only when explicitly requested.
- MEMORY.md = shared context bridge between Claude Code and Telegram.

---

## Telegram Interface

Commands: `/brain` `/venture` `/atlas` `/ai` `/archive` `/memo` `/brief` `/slack`

Flow:
```
User message → Router → Executor → Response
```

Archive: only on explicit request (e.g., `/archive this idea`)

---

## Implementation Status

| Component | Status | Notes |
|---|---|---|
| Orchestrator (router) | ✅ Done | `COMMAND_TO_AGENT` in bot.py |
| Brain Food + writing_samples | ✅ Done | linkedin/telegram/essays |
| /brain /venture /atlas /ai | ✅ Done | All commands live |
| Archive (ideas/decisions/notes) | ✅ Done | `/archive` command |
| MEMORY.md + /memo auto-classify | ✅ Done | M30/M90/M365 by Claude |
| 07:00 KST daily briefing | ✅ Done | Scheduler running |
| Slack monitoring → routing | ✅ Done | `/slack` command |
| Atlas task list (structured) | ✅ Done | `/task add/done/list/del` + `atlas/tasks.md` |
| Researcher agent | ❌ Not built | Web search / news pipeline |
| Agent chaining | ❌ Not built | Researcher → Executor |
| Auditor | ⏸ Deferred | Post-MVP |

---

## Next Build Priority

1. ~~**Atlas task management**~~ ✅ Done
2. **Researcher** — web search → summary → optional Brain Food handoff
3. **Business context files** — `contexts/medical-marketing.md` etc. for Venture agent
4. **Agent chaining** — `/research [topic] → /brain` pipeline
