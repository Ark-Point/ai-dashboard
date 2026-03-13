# Weekly Curation Agent

범용 주간 콘텐츠 큐레이션 에이전트. 프리셋 또는 직접 입력으로 소스를 수집하고, Notion 페이지로 출력한다.

## 사용법

```
/weekly-curation          # 애드혹 모드 — 대화형으로 소스 입력
/weekly-curation sui      # 프리셋 모드 — curation-presets.yaml에서 로드
```

## 워크플로우

### 1단계: 모드 감지 + 소스 확보

**프리셋 모드** (인자가 있을 때):
- `curation-presets.yaml` 파일을 읽는다 (프로젝트 루트: `/Users/kyongeunlee/HQ/client-news/`)
- 인자로 받은 프리셋 이름을 찾는다.
- 프리셋이 없으면 사용 가능한 프리셋 목록을 보여주고 선택을 요청한다.
- 질문 없이 바로 2단계로 진행한다.

**애드혹 모드** (인자가 없을 때):
- AskUserQuestion으로 순서대로 질문한다:

1. **프로젝트 이름?** (예: "Aptos", "Solana", "Ethereum")
2. **소스 붙여넣기** — 아래 형식을 자동 감지한다:
   - `@handle` → 트위터 핸들
   - URL에 `/rss/`, `/feed/`, `/rss`, `/feed` 포함 → RSS 피드
   - 그 외 URL → 웹페이지 직접 수집
3. **Notion 상위 페이지 URL?** (어떤 페이지 아래에 만들지)
   - URL에서 page ID를 추출한다 (마지막 32자 hex, 하이픈 포맷으로 변환)
4. **타겟 독자?** (기본값: "한국 리테일 투자자")

**소스 파싱 규칙:**
```
입력 예시:
@AptosLabs @AptosFoundation
https://medium.com/feed/aptoslabs
https://aptosfoundation.org/blog

파싱 결과:
- 트위터: AptosLabs, AptosFoundation
- RSS: https://medium.com/feed/aptoslabs
- 웹페이지: https://aptosfoundation.org/blog
```

### 2단계: 콘텐츠 수집

**RSS 피드 수집:**
- 각 RSS URL에 대해 WebFetch를 사용한다.
- 프롬프트: "이 RSS 피드에서 최근 {days}일 이내의 포스트를 모두 추출해줘. 각 포스트의 제목, 날짜, URL, 요약(description), 본문 내용을 가져와. 오늘 날짜는 {오늘 날짜}야."
- 수집된 포스트 수를 보고한다.

**웹페이지 직접 수집:**
- RSS가 아닌 일반 URL은 WebFetch로 직접 페이지 내용을 수집한다.
- 프롬프트: "이 웹페이지에서 최근 {days}일 이내의 뉴스, 블로그 포스트, 공지사항을 모두 추출해줘. 각 항목의 제목, 날짜, URL, 내용을 가져와. 오늘 날짜는 {오늘 날짜}야."

**트위터 수집 (3단계 폴백):**

각 핸들에 대해 아래 순서로 시도한다. 성공하면 다음 단계는 건너뛴다.

**1차: Nitter RSS**
- URL: `https://nitter.net/{handle}/rss`
- WebFetch 프롬프트: "이 RSS 피드에서 최근 {days}일 이내의 트윗을 모두 추출해줘. 각 트윗의 내용, 날짜, URL을 가져와. RT(리트윗)는 제외해. 오늘 날짜는 {오늘 날짜}야."
- 실패 조건: 빈 응답, 에러, 또는 트윗 0건

**2차: Nitter 대안 인스턴스**
- URL: `https://nitter.privacydev.net/{handle}/rss`
- 같은 프롬프트 사용

**3차: WebSearch 폴백**
- Nitter가 모두 실패하면 WebSearch를 사용한다.
- 검색 쿼리: `"from:@{handle}" site:x.com {프로젝트명} latest news`
- 추가 검색: `{프로젝트명} {handle} twitter announcement this week`
- 결과 보고 시 "웹 검색으로 보충"이라고 명시한다.

수집 실패 시 해당 소스를 건너뛰고 나머지로 계속 진행한다.

### 3단계: 큐레이션 분석

수집된 모든 콘텐츠를 분석하여 큐레이션을 작성한다.

**분석 기준:**
- 프리셋 모드: 프리셋의 `focus` 필드에 정의된 우선순위를 따른다.
- 애드혹 모드: 기본 기준을 사용한다:
  1. 가격/투자에 직접 영향
  2. 기관 채택 시그널
  3. 생태계 성장
  4. 기술 발전
  5. 일반 커뮤니티/마케팅

**출력 구조:**

```
# {프로젝트명} 주간 큐레이션
기간: {시작일} ~ {종료일}
소스: 블로그 {N}건 + 트윗 {N}건 분석

---

## 추천 포스팅 1: ★★★★★

**제목:** "{한국어 제목, 30자 이내}"

**핵심 포인트:**
- {구체적 사실, 숫자 포함}
- {2~4개 불릿}

**투자자 시사점:** {이 뉴스가 왜 중요한지 1~2문장}

**참고 링크:**
- {출처 URL}

---

## 추천 포스팅 2: ★★★★
...

---

## 선택적 포스팅 (관심도 ★3 미만)

| 제목 | 카테고리 | 핵심 요약 | 링크 |
|------|---------|----------|------|
| ... | ... | ... | ... |

---

## 추천 포스팅 순서
1. {제목} — {이유}
2. ...
```

**규칙:**
- 총 추천 수는 `max_recommendations` 이하 (기본 5개)
- 제목은 한국어로, 30자 이내
- 핵심 포인트는 사실 위주 (주관적 예측 금지)
- 블로그와 트윗이 같은 주제면 하나로 합친다
- 대상은 타겟 독자 기준

### 4단계: Notion 페이지 생성

먼저 Notion MCP 도구를 ToolSearch로 로드한다:
- `select:mcp__notion__API-post-page`
- `select:mcp__notion__API-patch-block-children`

**페이지 생성:**
- `mcp__notion__API-post-page`를 사용한다.
- parent: 프리셋의 `notion_parent_page_id` 또는 애드혹에서 입력받은 페이지 ID
- 제목: `{YYYY-MM-DD} 주간 큐레이션`
- 아이콘: 📊

**콘텐츠 블록 추가:**
- `mcp__notion__API-patch-block-children`으로 콘텐츠를 추가한다.
- 한 번의 호출에 최대 20~25개 블록을 넣는다. 더 많으면 나누어 호출한다.

**Notion 블록 구조:**

사용 가능한 블록 타입: `paragraph`, `bulleted_list_item` 만 사용한다.
시각적 구분은 이모지와 유니코드 구분선(━━━)으로 한다.

```
paragraph: "기간: {시작일} ~ {종료일} · 소스: 블로그 {N}건 + 트윗 {N}건"
paragraph: "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
paragraph: "⭐⭐⭐⭐⭐  추천 포스팅 1"
paragraph: "📰 {제목}"  (bold)
paragraph: "핵심 포인트:"
bulleted_list_item: "{포인트 1}"
bulleted_list_item: "{포인트 2}"
...
paragraph: "💡 투자자 시사점: {시사점}"
paragraph: "🔗 참고: {링크텍스트}"  (link 속성 사용)
paragraph: "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
... 반복 ...
paragraph: "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
paragraph: "📋 선택적 포스팅 (★3 미만)"
bulleted_list_item: "{제목} — {요약} (링크)"
...
paragraph: "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
paragraph: "🏆 추천 포스팅 순서"
paragraph: "1️⃣  {제목} — {이유}"
paragraph: "2️⃣  {제목} — {이유}"
...
```

**Rich text 링크 형식:**
```json
{
  "type": "text",
  "text": {
    "content": "링크 텍스트",
    "link": { "url": "https://..." }
  }
}
```

**Bold 텍스트 형식:**
```json
{
  "type": "text",
  "text": { "content": "굵은 텍스트" },
  "annotations": { "bold": true }
}
```

### 5단계: 결과 보고

사용자에게 아래 형식으로 보고한다:

```
✅ {프로젝트명} 주간 큐레이션 완료
📊 수집: 블로그 {N}건 + 트윗 {N}건
📝 추천 포스팅: {N}건
📄 Notion: {페이지 URL}
```

Notion 페이지 URL 형식: `https://www.notion.so/{페이지ID에서 하이픈 제거}`

## 에러 처리

- **RSS 피드 접근 실패**: 해당 소스를 건너뛰고 나머지로 진행. 실패한 소스를 결과에 명시.
- **트위터 수집 실패**: Nitter 1차 → 2차 → WebSearch 3차 순서로 폴백. 모두 실패하면 블로그 소스만으로 진행.
- **모든 소스 실패**: 사용자에게 알리고 중단.
- **Notion 페이지 접근 불가**: "Notion에서 해당 페이지에 통합(Integration)을 연결해주세요. 페이지 → ··· 메뉴 → 연결(Connections) → 통합 추가" 안내 메시지 출력.
- **Notion 블록 추가 실패**: 큐레이션 내용을 콘솔에 마크다운으로 출력하여 수동 복사 가능하게.
- **외부 서비스 오래 걸림**: 평소보다 오래 걸리면 즉시 중단하고 사용자에게 알린다. 대안 제시.
