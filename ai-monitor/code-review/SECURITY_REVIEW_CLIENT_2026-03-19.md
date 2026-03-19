# AI Monitor 보안검토 & 코드리뷰 — 클라이언트 사이드 집중 리포트

**검토 일자**: 2026-03-19
**검토 관점**: 구성원 PC에서 실행되는 코드 중심
**검토 수행**: backend-architect (코드리뷰), backend-security-coder (보안검토)

---

## 리뷰 우선순위

| 순위 | 대상 | 실행 환경 | 위험 근거 |
|------|------|----------|----------|
| **1** | `install.sh` | 구성원 PC (1회) | 시스템 변경, cron 등록, venv 설치 — 첫 실행 시 신뢰가 결정됨 |
| **2** | `session_collector.py` | 구성원 PC (매일 cron) | `~/.claude/projects` 읽기, JSON 생성, git push 자동 실행 |
| **3** | 서버 사이드 스크립트 | 운영 서버/CI | 외부 API 호출, HTML 생성 — 별도 요약 |

---

## 수집 설계 의도

본 시스템은 구성원의 AI 도구 활용 현황을 **팀 내 투명하게 공유**하기 위한 모니터링 도구입니다.

- **대화 내용/프롬프트는 수집하지 않음** — 메타데이터(도구 사용 횟수, 스킬, 세션 통계)만 추출
- **MCP 툴 이름 수집은 의도된 설계** — 어떤 도구를 활용하는지 파악하기 위함
- **전체 프로젝트 스캔은 의도된 설계** — 해당 직원이 Claude Code를 어떻게 활용하는지 투명하게 공유

아래 리뷰는 이 설계 의도를 존중하면서, **기술적 보안 이슈와 안정성 문제**에 집중합니다.

---

## 총평

설계 의도는 적절하나, 구현 단계에서 다음 기술적 위험이 존재합니다:

1. **install.sh의 `curl|bash` 패턴**으로 인한 원격 코드 실행 위험
2. **cron의 `source` 명령이 cron 환경에서 동작하지 않을 가능성** — 수집 자체가 실행 안 될 수 있음
3. **git push 자동 실행 시** 브랜치 미확인, 충돌 미처리, 자격증명 노출 위험

### 이슈 요약

| 심각도 | 건수 | 주요 내용 |
|--------|------|----------|
| High | 4 | cron source 실패 가능성, 비검증 git pull, git push 다중 위험, 수집 안내 문구 보완 |
| Major | 5 | cron 다른 항목 삭제, set -e만 사용, git pull 충돌, cutoff 로직, 실행 경로 혼재 |
| Medium | 4 | cron 인젝션, 파일 I/O 예외, hours 미검증, run_daily.sh 에러 전파 |
| Minor/Low | 9 | curl\|bash 참고, pip 버전, 설치 검증, Python 호환성, 로그 증가, 파일 권한 등 |

---

## Part 1: install.sh (최우선)

### [LOW] IST-L01. `curl | bash` 패턴 — 참고 사항

**라인 7:**
```bash
curl -sL https://raw.githubusercontent.com/Ark-Point/ark-agents/main/ai-monitor/install.sh | bash
```

구성원이 설치를 잊지 않도록 원커맨드로 실행할 수 있게 한 의도적 설계입니다. Private 레포이므로 외부 접근 위험은 낮습니다. 다만 일반적인 보안 관점에서 `curl|bash`는 부분 다운로드 시 불완전한 스크립트가 실행될 수 있으므로, 이미 제공하고 있는 로컬 실행 방법(9행)도 함께 안내하면 좋습니다.

---

### [HIGH] IST-H02. cron의 `source` 명령이 cron 환경에서 실패할 수 있음

**라인 39:**
```bash
CRON_CMD="cd $REPO_DIR && source .venv/bin/activate && python ai-monitor/session_collector.py --hours 24"
```

macOS의 cron은 기본적으로 `/bin/sh`로 실행되는데, `source`는 bash 전용 built-in입니다. macOS의 `/bin/sh`는 실제로 bash 호환이라 동작할 수 있지만, 환경에 따라 실패할 수 있습니다. 또한 cron 환경은 PATH가 최소한이라 `python`을 못 찾을 수도 있습니다.

**해결 방안:** venv의 python 바이너리를 직접 호출하면 `source activate`가 불필요하고, PATH 문제도 해결됩니다.

```bash
CRON_CMD="cd $REPO_DIR && .venv/bin/python ai-monitor/session_collector.py --hours 24"
```

---

### [HIGH] IST-H01. 비검증 git pull이 cron 실행 코드로 연결 — 공급망 공격

**라인 21:**
```bash
cd "$REPO_DIR" && git pull --quiet
```

main 브랜치에 악성 코드가 push되면 다음 cron 실행 시 **모든 구성원 PC에서 해당 코드가 실행**됩니다. 커밋 해시 고정, GPG 서명 검증, 파일 해시 검증이 없습니다.

**해결 방안:** 이 레포는 Private이며, 수집 데이터를 자동 커밋/push하는 것이 핵심 워크플로우이므로 PR 리뷰를 끼워넣는 것은 적절하지 않습니다. 대안으로:

```bash
# 방법 1: cron에서는 pull을 하지 않고, install 시점에만 코드를 고정
# → session_collector.py 코드 업데이트가 필요할 때만 구성원이 수동으로 git pull
# → 자동 push는 team-data/ 디렉토리의 JSON 데이터만 대상

# 방법 2: git add 대상을 team-data/ 하위로 명시적 제한
# session_collector.py의 save_and_push()에서:
subprocess.run(
    ["git", "add", str(filepath)],  # 현재도 특정 파일만 add — OK
    cwd=repo_path, capture_output=True, timeout=10
)
```

현재 코드는 이미 `git add`가 특정 JSON 파일만 대상이므로, 실행 코드(.py, .sh)가 의도치 않게 커밋되는 위험은 낮습니다.

---

### [MAJOR] IST-M01. cron 등록 시 다른 cron 항목 삭제 위험

**라인 43:**
```bash
(crontab -l 2>/dev/null | grep -v "session_collector.py"; echo "$CRON_SCHEDULE $CRON_CMD") | crontab -
```

`grep -v "session_collector.py"`가 이 문자열을 포함한 **모든 cron 라인**을 삭제합니다.

**해결 방안:** 고유 마커 사용

```bash
CRON_MARKER="# ark-ai-monitor"
(crontab -l 2>/dev/null | grep -v "$CRON_MARKER"; echo "$CRON_SCHEDULE $CRON_CMD $CRON_MARKER") | crontab -
```

---

### [MAJOR] IST-M02. `set -e`만 사용 — pipefail, nounset 누락

**라인 12:** `set -e`

파이프라인 중간 실패를 감지하지 못하고, 정의되지 않은 변수 참조 시 빈 문자열로 대체됩니다.

**해결 방안:**

```bash
set -euo pipefail
trap 'echo "❌ 설치 실패 (line $LINENO). 에러 확인 후 재시도하세요."' ERR
```

---

### [MAJOR] IST-M03. git pull 충돌 시 설치 중단 — 사용자 안내 없음

**라인 21:**

로컬에 변경사항이 있으면 merge conflict로 `set -e` 때문에 전체 설치가 중단되지만, 어떤 문제인지 안내하지 않습니다.

**해결 방안:**

```bash
cd "$REPO_DIR"
git stash --quiet 2>/dev/null || true
git pull --quiet --rebase || {
    echo "❌ git pull 실패. 수동으로 '$REPO_DIR'에서 충돌을 해결해 주세요."
    exit 1
}
```

---

### [MINOR] IST-m01~m03

| ID | 라인 | 내용 | 해결 방안 |
|----|------|------|----------|
| IST-m01 | 36 | `pip install`이 `requirements.txt`를 사용하지 않음 | `pip install -q -r ai-monitor/requirements.txt` |
| IST-m02 | 전반 | 설치 성공 확인 절차 부재 | 설치 마지막에 `.venv/bin/python -c "from config import KST; print('OK')"` 검증 추가 |
| IST-m03 | 18 | 하드코딩 경로 — iCloud 동기화 문제 가능 | `REPO_DIR="${ARK_AGENTS_DIR:-$HOME/Documents/ark_point/repos/ark-agents}"` |

---

## Part 2: session_collector.py (보안 핵심)

### [HIGH] SEC-H01. 수집 안내 문구 보완 필요

**위치**: `install.sh` 48-53행

현재 안내:
```
📊 수집하는 데이터:
   - 세션 수, 세션 시간
   - 도구 사용 횟수 (Read, Write, Bash 등)
   - 사용한 스킬 (/deep-research, /commit 등)
   - ❌ 대화 내용은 수집하지 않습니다
```

안내 내용이 사실이지만, 실제 수집 항목을 좀 더 구체적으로 명시하면 구성원 신뢰도가 높아집니다.

**해결 방안:** 안내 문구 보강

```bash
echo "📊 수집하는 데이터:"
echo "   - 전체 프로젝트의 세션 수, 시작/종료 시각, 작업 시간"
echo "   - 도구 사용 횟수 (Read, Write, Bash, MCP 도구 등)"
echo "   - 사용한 스킬 및 에이전트 타입"
echo "   - 작업 디렉토리 경로 (홈 디렉토리는 ~ 로 치환)"
echo "   - ❌ 대화 내용·프롬프트는 수집하지 않습니다"
echo ""
echo "🔍 수집 내용을 미리 확인하려면:"
echo "   python ai-monitor/session_collector.py --dry-run"
```

---

### [HIGH] SEC-H02. git push 자동 실행 — 다중 위험

**위치**: 183-202행

```python
subprocess.run(["git", "add", str(filepath)], ...)
subprocess.run(["git", "commit", "-m", f"ai-monitor: {data['username']} ..."], ...)
subprocess.run(["git", "push"], ...)
```

발견된 문제:

1. **현재 브랜치 미확인** — 구성원이 feature 브랜치에서 작업 중일 때 해당 브랜치에 커밋/push
2. **git pull 없음** — 다른 구성원의 push와 충돌 시 실패, 다음날까지 데이터 누락
3. **commit 실패 시 staged 상태 잔류** — 구성원의 다음 수동 커밋에 세션 데이터가 포함될 수 있음
4. **push stderr에 자격증명 포함 가능** — `result.stderr[:200]` 출력 시 토큰 노출

**해결 방안:**

```python
import re

def _redact_credentials(text: str) -> str:
    """stderr에서 자격증명 패턴 제거"""
    text = re.sub(r'https?://[^@\s]+@', 'https://[redacted]@', text)
    return re.sub(r'(ghp_|github_pat_|ghs_)[A-Za-z0-9]+', '[TOKEN]', text)

def save_and_push(data: dict, repo_path: str | None = None):
    if not repo_path:
        repo_path = str(Path(__file__).parent.parent)

    output_dir = Path(repo_path) / "ai-monitor" / "team-data" / data["username"]
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = output_dir / f"{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[collector] 저장: {filepath}")

    try:
        # 1. 브랜치 확인
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=5
        )
        current_branch = branch_result.stdout.strip()
        if current_branch != "main":
            print(f"[collector] 경고: '{current_branch}' 브랜치. main에서만 push합니다.")
            return

        # 2. pull --rebase로 충돌 방지
        pull_result = subprocess.run(
            ["git", "pull", "--rebase", "--quiet"],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        if pull_result.returncode != 0:
            print(f"[collector] pull 실패, push 중단")
            return

        # 3. add
        add_result = subprocess.run(
            ["git", "add", str(filepath)],
            cwd=repo_path, capture_output=True, timeout=10
        )
        if add_result.returncode != 0:
            print("[collector] git add 실패")
            return

        # 4. commit
        commit_result = subprocess.run(
            ["git", "commit", "-m",
             f"ai-monitor: {data['username']} daily session data ({date_str})"],
            cwd=repo_path, capture_output=True, timeout=10
        )
        if commit_result.returncode != 0:
            # staged 상태 롤백
            subprocess.run(["git", "reset", "HEAD", str(filepath)],
                           cwd=repo_path, capture_output=True, timeout=5)
            print("[collector] commit 실패, staged 상태 롤백 완료")
            return

        # 5. push
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print("[collector] push 완료")
        else:
            safe_stderr = _redact_credentials(result.stderr)
            print(f"[collector] push 실패: {safe_stderr[:200]}")

    except subprocess.TimeoutExpired:
        print("[collector] git 명령 타임아웃")
    except Exception as e:
        print(f"[collector] git 오류: {type(e).__name__}: {e}")
```

---

### [MAJOR] SEC-M01. cutoff 비교 로직 — 유효한 세션 누락

**위치**: 92-94행

```python
if not first_ts or first_ts < cutoff:
    return None
```

세션 **시작 시간**이 cutoff 이전이면 전체 세션을 버립니다. 자정 전에 시작해서 자정 후까지 이어진 세션은 완전히 누락됩니다.

**해결 방안:** `last_ts` 기준으로 변경

```python
# 마지막 활동 시간 기준으로 판단
if not last_ts or last_ts < cutoff:
    return None
```

---

### [MAJOR] SEC-M02. install.sh와 run_daily.sh 실행 경로 혼재

**install.sh** cron은 `session_collector.py`만 실행하지만, **run_daily.sh**는 추가로 `daily_digest.py`, `generate_dashboard.py`, 대시보드 배포까지 수행합니다. 클라이언트 PC용과 서버/관리자 PC용이 구분되지 않아 혼란을 줍니다.

**해결 방안:**

```bash
# 방법 1: run_daily.sh 상단에 역할 명시
# ============================================================
# 이 스크립트는 관리자 PC 또는 서버에서만 실행합니다.
# 일반 구성원은 install.sh가 등록한 cron으로 session_collector.py만 실행됩니다.
# ============================================================

# 방법 2: 파일 분리
# run_client.sh  — session_collector.py만 (cron용)
# run_server.sh  — digest + dashboard + 배포 (관리자용)
```

---

### [MEDIUM] SEC-M03~M05

| ID | 위치 | 내용 | 해결 방안 |
|----|------|------|----------|
| SEC-M03 | 47행 | 파일 인코딩 미지정 + PermissionError 미처리 | 아래 코드 참조 |
| SEC-M04 | 207행 | `--hours` 입력값 미검증 — 음수·극대값 허용 | 아래 코드 참조 |
| SEC-M05 | 178행 | 파일 생성 시 권한 미설정 — 기본 644로 타인 읽기 가능 | 아래 코드 참조 |

**SEC-M03 해결 방안:**

```python
def analyze_session(filepath: Path, cutoff: datetime) -> dict | None:
    """단일 세션 JSONL 분석 — 메타데이터만 추출, 대화 내용 제거"""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # ... 기존 로직
    except PermissionError:
        print(f"[collector] 파일 권한 없음, 건너뜀: {filepath.name}")
        return None
    except OSError as e:
        print(f"[collector] 파일 읽기 오류: {type(e).__name__}: {filepath.name}")
        return None
```

**SEC-M04 해결 방안:**

```python
def validate_hours(value: str) -> int:
    ivalue = int(value)
    if ivalue < 1:
        raise argparse.ArgumentTypeError("--hours는 1 이상이어야 합니다")
    if ivalue > 168:  # 7일 최대
        raise argparse.ArgumentTypeError("--hours는 168(7일) 이하여야 합니다")
    return ivalue

parser.add_argument("--hours", type=validate_hours, default=24, help="수집 기간 (시간, 1~168)")
```

**SEC-M05 해결 방안:**

```python
import os

# save_and_push 내부 — 파일 생성 시 권한 설정
old_umask = os.umask(0o077)
try:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
finally:
    os.umask(old_umask)
```

---

### [LOW/INFO] 기타

| ID | 내용 | 해결 방안 |
|----|------|----------|
| SEC-L01 | `import glob` 미사용 (12행) | `import glob` 라인 삭제 |
| SEC-L02 | Python 3.10+ 전용 타입 힌트 (`list[Path]`, `str \| None`) | 파일 상단에 `from __future__ import annotations` 추가 |
| SEC-L03 | `TimeoutExpired` 예외와 일반 예외 구분 없이 처리 | SEC-H02 해결 방안에 포함 |
| SEC-I01 | 데이터 무결성 검증 없음 | 수집 시점 해시 추가 권장 (아래 참조) |

**SEC-I01 해결 방안 (선택):**

```python
import hashlib

def _compute_checksum(data: dict) -> str:
    """수집 데이터 무결성 해시"""
    raw = json.dumps(data["summary"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

# collect_all_sessions 반환 시
data["checksum"] = _compute_checksum(data)
```

---

## Part 3: 서버 사이드 (요약)

| 심각도 | 파일 | 이슈 | 해결 방안 |
|--------|------|------|----------|
| High | `generate_dashboard.py` | XSS — JSON 데이터가 HTML에 이스케이프 없이 삽입 | `import html`후 모든 동적 값에 `html.escape()` 적용 |
| High | `daily_digest.py:18` | `.env` 경로가 `telegram/.env`로 하드코딩 | `ai-monitor/.env` 우선 탐색, 없으면 상위 `.env` 폴백 |
| Major | `run_daily.sh` | `set -e` 누락, `/tmp` 공유 디렉토리 사용 | `set -euo pipefail` + `$HOME/.cache/ai-dashboard` 사용 |
| Medium | `daily_digest.py:32` | 날짜 계산 버그 — 매월 1일 실패 | `yesterday = (date.today() - timedelta(days=1)).isoformat()` |
| Medium | `slack_analyzer.py` | 페이지네이션 미구현, 빈 토큰 조용한 실패 | `cursor` 기반 반복 조회 + 토큰 부재 시 `EnvironmentError` |
| Minor | `config.py` | 서버/클라이언트 설정 혼재 | `config_common.py` (KST) / `config_server.py` 분리 |
| Minor | `requirements.txt` | 클라이언트에 불필요한 `slack_sdk` 설치 | `requirements-client.txt` / `requirements-server.txt` 분리 |

---

## 조치 로드맵

### 즉시 (배포 전 필수)

| 항목 | 공수 | 설명 |
|------|------|------|
| IST-H02 | 5분 | cron 명령을 `.venv/bin/python` 직접 호출로 변경 — cron 환경에서 안정적 실행 보장 |
| SEC-M01 | 10분 | cutoff 비교를 `last_ts` 기준으로 변경 — 세션 누락 방지 |

### 단기 (1주 이내)

| 항목 | 공수 | 설명 |
|------|------|------|
| SEC-H02 | 1시간 | git push 안전장치 (브랜치 확인, pull --rebase, staged 롤백, stderr 자격증명 제거) |
| SEC-H01 | 15분 | 수집 안내 문구 보강 — 실제 수집 항목 구체적 명시 |
| IST-M01 | 15분 | cron 마커 도입 — 다른 cron 항목 삭제 방지 |
| IST-M02 | 5분 | `set -euo pipefail` + 에러 trap |
| IST-M03 | 15분 | git pull 충돌 시 stash + 사용자 안내 |

### 중기 (2주 이내)

| 항목 | 공수 | 설명 |
|------|------|------|
| SEC-M03 | 15분 | 파일 I/O 예외 처리 + 인코딩 지정 |
| SEC-M04 | 10분 | `--hours` 입력값 범위 검증 (1~168) |
| SEC-M05 | 10분 | 파일 생성 시 `0o600` 권한 설정 |
| IST-H01 | 15분 | cron에서 코드 pull과 데이터 push를 분리 |
| SEC-M02 | 30분 | 클라이언트/서버 실행 경로 분리 또는 역할 명시 |
| 서버 사이드 | 1시간 | XSS 방어, 날짜 계산 버그 수정, 페이지네이션 구현 |
