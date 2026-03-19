# AI Monitor 코드리뷰 & 보안검토 리포트

**검토 일자**: 2026-03-19
**검토 대상**: `ai-monitor/` 디렉토리 내 Python 코드 6개 파일
**검토 범위**: config.py, daily_digest.py, generate_dashboard.py, github_collector.py, session_collector.py, slack_analyzer.py

---

## Executive Summary

코드리뷰와 보안검토를 병렬로 수행한 결과, **Critical 3건, High 4건, Major 10건** 포함 총 43건의 이슈를 발견했습니다. 내부 팀 모니터링 도구로서 외부 노출 범위는 제한적이나, XSS 취약점과 경로 순회(Path Traversal), 날짜 계산 버그 등 실질적 위험이 존재합니다.

### 이슈 요약

| 심각도 | 코드리뷰 | 보안검토 | 합계 |
|--------|---------|---------|------|
| Critical | 2 | 1 | 3 |
| High | - | 4 | 4 |
| Major | 10 | - | 10 |
| Medium | - | 6 | 6 |
| Minor | 8 | - | 8 |
| Low | - | 5 | 5 |
| Suggestion | 5 | - | 5 |
| Informational | - | 2 | 2 |

---

## Part 1: 코드리뷰

### Critical Issues

#### CR-C01. `daily_digest.py:32` — 날짜 계산 버그

```python
# 현재 코드 (버그)
yesterday = (date.today().replace(day=date.today().day - 1)).isoformat() if date.today().day > 1 else today
```

매월 1일에 `yesterday = today`가 되어 어제 데이터를 전혀 조회하지 못합니다. `timedelta`를 사용해야 합니다:

```python
# 수정안
from datetime import timedelta
yesterday = (date.today() - timedelta(days=1)).isoformat()
```

#### CR-C02. `session_collector.py:93` — cutoff 비교 로직 오류

```python
if not first_ts or first_ts < cutoff:
    return None
```

세션 시작 시간이 cutoff 이전이면 전체 세션을 버리지만, cutoff 이전에 시작되어 이후까지 지속된 세션도 무시됩니다. `last_ts`를 기준으로 비교해야 합니다:

```python
if not last_ts or last_ts < cutoff:
    return None
```

---

### Major Issues

#### CR-M01. `daily_digest.py:25-47` — `hours` 파라미터 미사용

`load_team_sessions(hours: int)` 함수가 `hours` 파라미터를 받지만 실제로 사용하지 않습니다. 오늘/어제 파일만 하드코딩으로 탐색하므로 `--hours 48` 옵션을 줘도 동작이 동일합니다.

#### CR-M02. `daily_digest.py:183-196` — 하드코딩된 사용자 매핑

`_get_display_name()`에 OS username → display name 매핑이 하드코딩되어 있어 `config.py`의 `TEAM_MEMBERS`와 중복 관리됩니다. `config.py`에 통합해야 합니다.

#### CR-M03. `generate_dashboard.py:131` — 함수 내부 import

```python
from config import TEAM_MEMBERS  # 함수 내부 (line 131)
```

파일 상단으로 이동해야 합니다. 순환 import 문제가 아닌 이상 함수 내부 import는 피해야 합니다.

#### CR-M04. `generate_dashboard.py:39-438` — 400줄짜리 단일 함수

`generate_html()`이 약 400줄에 달하며, HTML/CSS/JS가 모두 Python f-string 안에 있습니다. Jinja2 템플릿 분리를 강력히 권장합니다.

#### CR-M05. `generate_dashboard.py:144-438` — XSS 취약점 (보안 항목과 중복)

`username`, `summary`, `tool` 이름 등이 이스케이프 없이 HTML에 직접 삽입됩니다. `html.escape()` 적용이 필요합니다.

#### CR-M06. `github_collector.py:12-19` — 에러 로깅 없는 실패 처리

`gh` 명령 실패 시 빈 문자열을 반환하지만 에러 메시지(`stderr`)를 로깅하지 않아 인증 실패, 네트워크 오류, rate limit 등의 원인 파악이 불가능합니다.

#### CR-M07. `github_collector.py:12` — subprocess timeout 미처리

`subprocess.run`에서 `timeout`을 사용하지만 `subprocess.TimeoutExpired` 예외를 catch하지 않아 timeout 발생 시 프로그램이 비정상 종료됩니다.

#### CR-M08. `session_collector.py:184-202` — git push 자동 실행 위험

`save_and_push()`가 `git add`, `git commit`, `git push`를 무조건 실행합니다:
- 현재 브랜치가 main이 아닌 경우에도 push
- 다른 staged 변경사항이 의도치 않은 커밋에 포함 가능
- push 실패 시 재시도 로직 없음

#### CR-M09. `slack_analyzer.py:38-39` — users_list 페이지네이션 미처리

대규모 워크스페이스에서 첫 페이지만 가져옵니다. `cursor` 기반 페이지네이션이 필요합니다.

#### CR-M10. `slack_analyzer.py:22-27` — conversations_history 페이지네이션 미처리

`limit=200`으로 설정했지만 메시지가 200개를 초과하면 나머지를 가져오지 못합니다.

---

### Minor Issues

| ID | 파일 | 내용 |
|----|------|------|
| CR-m01 | `config.py:33-41` | AI_COMMIT_MARKERS 대소문자 중복 (이미 `.lower()` 비교) |
| CR-m02 | `config.py:46-49` | AI_KEYWORDS의 `"ai"` 단독 키워드 오탐 위험 (단어 경계 `\b` 없음) |
| CR-m03 | `daily_digest.py:43` | 파일 열기 시 `encoding="utf-8"` 미지정 |
| CR-m04 | `daily_digest.py:307` | 환경변수 키를 `config.py` 상수 대신 직접 문자열 사용 |
| CR-m05 | `generate_dashboard.py:78` | `max_val=0`일 때 ZeroDivisionError 가능 |
| CR-m06 | `session_collector.py:13` | `import glob` 미사용 (`Path.glob()` 사용 중) |
| CR-m07 | `session_collector.py:175` | `datetime.now()` 사용, KST 미반영 (다른 코드는 KST 명시) |
| CR-m08 | `slack_analyzer.py:49` | SlackApiError를 `pass`로 완전 무시 |

---

### Suggestions

| ID | 내용 |
|----|------|
| CR-S01 | `TypedDict` 또는 `dataclass` 도입으로 데이터 모델 정형화 |
| CR-S02 | `generate_dashboard.py`의 HTML을 Jinja2 템플릿으로 분리 |
| CR-S03 | 단위 테스트 추가 (`is_ai_commit()`, `analyze_messages()`, `_anonymize_path()` 등) |
| CR-S04 | `.env` 파일 경로를 `telegram/.env`가 아닌 프로젝트 루트 또는 `ai-monitor/.env`로 변경 |
| CR-S05 | 함수 시그니처 타입 힌트 보강 |

---

## Part 2: 보안검토

### Critical

#### SEC-C01. XSS (Cross-Site Scripting) — `generate_dashboard.py:70-126`

`team-data/` JSON에서 로드한 `username`, `tool` 이름, `skill` 이름이 HTML 인코딩 없이 f-string으로 직접 삽입됩니다. 조작된 JSON이 커밋되면 대시보드를 열람하는 모든 브라우저에서 임의 코드가 실행됩니다.

**대시보드가 GitHub Pages에 공개 배포되므로 위험이 증폭됩니다.**

```python
# 수정안
import html as html_module

def _escape(value) -> str:
    return html_module.escape(str(value))

# 모든 동적 값에 적용
f'<h3>{_escape(username.upper())}</h3>'
f'<span class="tool-name">{_escape(short_name)}</span>'
```

---

### High

#### SEC-H01. 경로 순회 (Path Traversal) — `session_collector.py:172`

```python
output_dir = Path(repo_path) / "ai-monitor" / "team-data" / data["username"]
# username = "../../etc" 이면 repo 루트 외부에 파일 생성 가능
```

**수정안**: username 검증 + resolve 후 경로 확인

```python
import re

def _validate_username(username: str) -> str:
    if not re.match(r'^[a-zA-Z0-9_-]{1,32}$', username):
        raise ValueError(f"유효하지 않은 사용자명: {username!r}")
    return username

safe_username = _validate_username(data["username"])
output_dir = (Path(repo_path) / "ai-monitor" / "team-data" / safe_username).resolve()
if not str(output_dir).startswith(str(Path(repo_path).resolve())):
    raise ValueError("경로 순회 시도 감지")
```

#### SEC-H02. subprocess 입력값 미검증 — `github_collector.py:58-64`

GitHub API에서 가져온 저장소 이름이 GraphQL 쿼리 인자로 직접 전달됩니다. 에러 처리 미흡으로 실패 원인 추적이 불가능합니다.

```python
def _validate_repo_name(name: str) -> str:
    if not re.match(r'^[a-zA-Z0-9._-]{1,100}$', name):
        raise ValueError(f"유효하지 않은 저장소 이름: {name!r}")
    return name
```

#### SEC-H03. 민감 정보 로그 출력 — `slack_analyzer.py:30, 113`

Slack API 에러 응답을 `print()`로 직접 출력합니다. `run_daily.log`에 저장되며, git에 커밋될 수 있습니다.

```python
# 수정안: 에러 코드만 로깅
import logging
logger = logging.getLogger(__name__)

except SlackApiError as e:
    error_code = e.response.get("error", "unknown_error")
    logger.warning("[slack] API 오류: %s", error_code)
```

#### SEC-H04. `.env` 파일 경로 하드코딩 — `daily_digest.py:18`, `slack_analyzer.py:129`

Slack 토큰이 `telegram/.env`에서 로드됩니다. 다른 서비스의 자격증명과 혼용되며, 토큰 부재 시 빈 토큰으로 API 호출하는 조용한 실패가 발생합니다.

```python
# 수정안: 전용 .env + 토큰 검증
token = os.environ.get("SLACK_BOT_TOKEN", "")
if not token:
    raise EnvironmentError("SLACK_BOT_TOKEN이 설정되지 않았습니다.")
```

---

### Medium

| ID | 파일 | 내용 |
|----|------|------|
| SEC-M01 | `daily_digest.py:32` | 날짜 계산 버그로 매월 1일 데이터 수집 실패 |
| SEC-M02 | 전반 | JSON 파일 로드 시 스키마 검증 없이 직접 사용 — TypeError/KeyError 가능 |
| SEC-M03 | `run_daily.sh:22-27` | 대시보드가 공개 GitHub Pages에 인증 없이 배포 — 팀 생산성 데이터 외부 노출 |
| SEC-M04 | `session_collector.py:190` | git 커밋 메시지에 OS 사용자명 포함 — 공개 저장소에서 노출 |
| SEC-M05 | `slack_analyzer.py:87-93` | URL 수집 목록 크기 상한 없음 — 메모리 DoS 가능 |
| SEC-M06 | `run_daily.sh:27` | git push 오류 미처리 + `/tmp` 공유 디렉토리 사용 (TOCTOU) |

---

### Low

| ID | 파일 | 내용 |
|----|------|------|
| SEC-L01 | `slack_analyzer.py:22-31` | conversations_history 페이지네이션 미구현 — 데이터 부정확 |
| SEC-L02 | 전반 | 하드코딩 경로 (`~/Documents/ark_point/repos/...`) — 로컬 구조 정보 노출 |
| SEC-L03 | `session_collector.py:178` | 파일 생성 시 권한 미설정 — 공유 환경에서 데이터 읽기 가능 |
| SEC-L04 | 전반 | `except Exception`으로 모든 예외를 잡고 스택 트레이스 미기록 |
| SEC-L05 | `slack_analyzer.py:36-51` | users_list 페이지네이션 미구현 |

### Informational

| ID | 내용 |
|----|------|
| SEC-I01 | `requirements.txt` — 버전 상한선 없음, `pip-audit` 미적용 |
| SEC-I02 | `install.sh` — `curl | bash` 패턴 주석 포함, SHA256 체크섬 검증 없음 |

---

## 우선순위별 조치 로드맵

### 즉시 조치 (1일 이내)

| 항목 | 예상 공수 | 설명 |
|------|---------|------|
| SEC-C01 / CR-M05 | 30분 | `html.escape()` 적용하여 XSS 방어 |
| SEC-H04 | 1시간 | `.env` 파일 분리 및 토큰 유효성 사전 검증 |
| CR-C01 / SEC-M01 | 15분 | `timedelta` 사용한 날짜 계산 수정 |

### 단기 (1주 이내)

| 항목 | 예상 공수 | 설명 |
|------|---------|------|
| SEC-H01 | 1시간 | username 경로 순회 검증 |
| SEC-H03 | 30분 | `logging` 모듈 도입, 민감 정보 제거 |
| SEC-M03 | 2시간 | 대시보드 접근 제어 (Private repo 또는 민감 데이터 제거) |
| CR-C02 | 15분 | session cutoff 비교 로직 수정 |
| CR-M07 | 15분 | `TimeoutExpired` 예외 처리 추가 |

### 중기 (2주 이내)

| 항목 | 예상 공수 | 설명 |
|------|---------|------|
| SEC-H02 | 1시간 | subprocess 입력 검증 강화 |
| CR-M09, CR-M10, SEC-L01 | 2시간 | Slack API 페이지네이션 구현 |
| CR-M01 | 30분 | `hours` 파라미터 실제 반영 |
| CR-M08 | 1시간 | git push 로직 안전장치 추가 |

### 장기

| 항목 | 예상 공수 | 설명 |
|------|---------|------|
| CR-M04 | 반나절 | Jinja2 템플릿 분리 |
| CR-S01 | 반나절 | `dataclass` / `TypedDict` 도입 |
| CR-S03 | 1일 | 단위 테스트 추가 |
| SEC-I01 | 반나절 | 의존성 고정 및 취약점 스캔 CI 통합 |

---

## 핵심 보안 체크리스트

- [ ] HTML 삽입되는 모든 동적 데이터에 `html.escape()` 적용
- [ ] JSON 데이터 로드 시 타입 및 스키마 검증 추가
- [ ] 파일 경로 생성 시 `.resolve()` 후 기대 디렉토리 내 여부 검증
- [ ] 모든 `print()` → `logging` 모듈로 교체 (민감 정보 로그 레벨 제어)
- [ ] 환경 변수 누락 시 명시적 오류 발생 (조용한 실패 제거)
- [ ] `run_daily.log` 및 `dashboard.html`을 `.gitignore`에 추가
- [ ] `run_daily.sh` 상단에 `set -euo pipefail` 추가
- [ ] `/tmp` 대신 사용자별 디렉토리 사용 (`$HOME/.cache/`)
