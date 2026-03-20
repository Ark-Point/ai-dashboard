# ARK Point — Agentic Workflow System

ARK Point의 AI 에이전트 시스템 및 자동화 워크플로우 레포지토리.

---

## 폴더 구조

```
ark-agents/
├── agents/           # 에이전트 정의 파일 (.md)
├── contexts/         # 프로젝트별 컨텍스트 문서 (.md)
│   ├── medical-marketing/
│   └── social-dating-club/
├── projects/         # 실무 자료 (gitignored — Google Drive 병행 관리)
├── tools/            # 스크립트 및 유틸리티
│   └── scrape_output/ (gitignored)
├── telegram/         # 텔레그램 봇 (morning briefing, weekly report)
├── hs-brain/         # HS 개인 AI 시스템
├── hs-orchestrator/  # 오케스트레이터 설정
└── archive/          # 과거 설계 문서
```

---

## 에이전트 목록

| 파일 | 역할 |
|---|---|
| `agents/brain.md` | 리서치 및 분석 |
| `agents/atlas.md` | 태스크 관리 |
| `agents/auditor.md` | 전략 감사 / 얼라인먼트 체크 |
| `agents/researcher.md` | 외부 리서치 |
| `agents/ai-org.md` | AI Native 조직 설계 |
| `agents/venture.md` | 벤처/투자 분석 |

---

## 주요 시스템

### 텔레그램 봇 (`telegram/`)
- `bot.py` — 모바일 승인 시스템, Claude Code 인터페이스
- `morning.py` — 모닝 브리핑 자동 발송
- `weekly-report.py` — 주간 리포트 생성

### 컨텍스트 레이어 (`contexts/`)
프로젝트별 AI 컨텍스트 파일. 에이전트가 작업 시 참조.

---

## 운영 규칙

- `agents/` — 에이전트 정의 `.md` 파일만 (실무 자료 X)
- `contexts/` — 프로젝트 컨텍스트 `.md` 파일만
- `projects/` — PDF, Excel 등 실무 자료 (gitignored, Google Drive에서 관리)
- `.env` 파일 절대 커밋 금지

---

## 관련 레포

- [claude-plugins](https://github.com/Ark-Point/claude-plugins) — 73개 플러그인, 108개 에이전트
- [lumina-app](https://github.com/Ark-Point/lumina-app) — 풀스택 모노레포
