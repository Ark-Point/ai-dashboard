# ARK Point Agentic System — 설계 문서

날짜: 2026-03-12

---

## 개념 아키텍처 (6-Role Model)

- Orchestrator
- Planner
- Researcher
- Executor
- Auditor
- Archive

## 구현 v1 (Simple Router Model)

- Router (Orchestrator + Planner 통합)
- Brain Food
- New Venture Strategy
- Personal Ops
- AI Native Organization
- Archive

## 설계 원칙

- Telegram을 주 인터페이스로 사용
- Router가 어떤 Executor를 호출할지 결정
- Research는 optional, 나중에 추가
- Auditor는 optional, 명시적 요청 시만 실행
- Archive는 manual-first (`/archive` 커맨드)
- 모든 것은 경량(lightweight)하고 파일 기반(file-based)
- 기존 `telegram/bot.py` 구조 재사용

## Brain Food 설계

- `writing_samples/` 를 스타일 corpus로 사용
- 과거 글 few-shot prompting으로 스타일 학습
- 지원 모드: idea → draft, bullet points → post, rewrite in my voice

## 구현 결과

- `telegram/bot.py` — Router + 모든 Executor 커맨드
- `agents/brain.md` — Brain Food 시스템 프롬프트
- `agents/venture.md` — New Venture Strategy 프롬프트
- `agents/atlas.md` — Personal Ops 프롬프트
- `agents/ai-org.md` — AI Native Organization 프롬프트
- `writing_samples/telegram/` — Brain Food 텔레그램 글 corpus (2개)
- `writing_samples/linkedin/` — LinkedIn 글 corpus (51개)
- `telegram/hook_approval.py` — Claude Code 모바일 승인 hook

## 오늘 완료한 것

1. Telegram 봇 구축 및 실행 (brain/venture/atlas/ai/archive 커맨드)
2. Brain Food 채널 → writing_samples 자동 저장
3. 과거 LinkedIn 글 51개 일괄 학습
4. 포워드 메시지 원본 날짜 보존 저장
5. Claude Code 모바일 승인 시스템 (hook + 텔레그램 버튼)
