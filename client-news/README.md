# Client News — 주간 큐레이션 에이전트

블록체인 생태계별 주간 뉴스를 자동 수집 → 큐레이션 → **Notion 페이지**로 생성하는 Claude Code 에이전트입니다.

## 사용법

### 프리셋 모드 (등록된 프로젝트)

```bash
cd client-news
/weekly-curation sui
```

`curation-presets.yaml`에 등록된 프리셋으로 자동 실행됩니다.

### 애드혹 모드 (아무 프로젝트나)

```bash
cd client-news
/weekly-curation
```

에이전트가 순서대로 질문합니다:
1. 프로젝트 이름 (예: Aptos, Solana)
2. 소스 붙여넣기 — 자동 감지:
   - `@handle` → 트위터
   - `/rss/` 또는 `/feed/` 포함 URL → RSS 피드
   - 그 외 URL → 웹페이지 직접 수집
3. Notion 상위 페이지 URL
4. 타겟 독자 (기본: 한국 리테일 투자자)

### 입력 예시

```
@AptosLabs @AptosFoundation
https://medium.com/feed/aptoslabs
https://aptosfoundation.org/blog
```

## 사전 설정

### 1. Notion MCP 연결

Claude Code에 Notion MCP 서버를 추가해야 합니다:

```bash
claude mcp add notion \
  --type stdio \
  npx -y @notionhq/notion-mcp-server
```

환경변수에 Notion API 토큰 설정:
- [Notion Integration 생성](https://www.notion.so/my-integrations) → Internal Integration → 토큰 복사
- `.claude.json`에 토큰 추가:
  ```json
  "notion": {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@notionhq/notion-mcp-server"],
    "env": { "NOTION_TOKEN": "your_token_here" }
  }
  ```

### 2. Notion 페이지 연결

큐레이션을 생성할 상위 Notion 페이지에 Integration을 연결합니다:
- Notion 페이지 열기 → 우측 상단 `···` → **연결(Connections)** → Integration 추가

## 출력 예시

> **실제 결과물**: [Sui 주간 큐레이션 2026-03-13 (Notion)](https://www.notion.so/2026-03-13-32293ff92712811c8547f4379804ff5e)

`/weekly-curation sui` 실행 결과 — Notion 페이지 구조:

```
📊 2026-03-13 주간 큐레이션
│
│  기간: 2026-03-06 ~ 2026-03-13 · 소스: 블로그 4건 + 웹 검색 뉴스
│
├── ⭐⭐⭐⭐⭐ 추천 포스팅 1
│   ├── 📰 Sui 네이티브 스테이블코인 USDsui 메인넷 출시
│   ├── • Stripe 자회사 Bridge의 Open Issuance 플랫폼 기반 발행
│   ├── • 월 $100B 이상 스테이블코인 거래량 시장 진입
│   ├── 💡 Stripe 계열사의 규제 친화적 스테이블코인은 기관 자금 유입의 핵심 인프라
│   └── 🔗 blog.sui.io/sui-dollar-launch-bridge/
│
├── ⭐⭐⭐⭐⭐ 추천 포스팅 2
│   ├── 📰 Sui ETF 3종 미국 상장 — 기관 투자 시대 개막
│   ├── • Grayscale, Canary Capital, 21Shares 세 곳이 Sui ETF 상장
│   ├── 💡 비트코인, 이더리움에 이어 Layer 1 중 ETF를 확보한 사례
│   └── 🔗 blog.sui.io/sui-monthly-february-2026/
│
├── ⭐⭐⭐⭐ 추천 포스팅 3
│   ├── 📰 4월 SUI 4,290만 토큰 언락 예정 — 매도 압력 주의
│   └── 💡 비중 1.1%로 작지만 단기 트레이딩 관점에서 유의
│
├── ⭐⭐⭐ 추천 포스팅 4
│   ├── 📰 Seal 분산형 키서버 테스트넷 출시
│   └── 💡 프라이버시 인프라 강화, 기관 채택의 전제 조건
│
├── 📋 선택적 포스팅 (★3 미만)
│   ├── • Sui 초보자 가이드 시리즈 — 교육/커뮤니티
│   └── • $10,000 SUI 콘텐츠 경연 결과 — 마케팅
│
└── 🏆 추천 포스팅 순서
    ├── 1️⃣ USDsui 스테이블코인 — 가격/생태계 직접 영향
    ├── 2️⃣ Sui ETF 3종 상장 — 기관 채택 상징적 이벤트
    ├── 3️⃣ 4월 토큰 언락 — 단기 트레이딩 실용 정보
    └── 4️⃣ Seal 키서버 — 기술 관심 높은 팔로워 대상
```

## 프리셋 추가

`curation-presets.yaml`에 새 프리셋을 추가하면 됩니다:

```yaml
presets:
  aptos:
    name: "Aptos Ecosystem"
    rss_feeds:
      - url: "https://medium.com/feed/aptoslabs"
        label: "Aptos Labs 블로그"
    twitter_handles:
      - Aptos
    audience: "한국 리테일 투자자"
    focus: "투자 관련성 중심 큐레이션"
    days: 7
    notion_parent_page_id: "your-notion-page-id"
    max_recommendations: 5
```

## 파일 구조

```
client-news/
├── .claude/agents/
│   └── weekly-curation.md    # 에이전트 정의
├── curation-presets.yaml      # 프리셋 설정
└── README.md
```
