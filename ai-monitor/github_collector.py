"""
GitHub 활동 수집기
Ark-Point org의 모든 repo에서 최근 N시간 커밋 분석
GraphQL API 사용 (REST API 접근 제한 대응)
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from config import TEAM_MEMBERS, GITHUB_ORG, AI_COMMIT_MARKERS


def run_gh(args: list[str], timeout: int = 30) -> str:
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_org_repos() -> list[str]:
    output = run_gh([
        "repo", "list", GITHUB_ORG,
        "--limit", "50",
        "--json", "name",
        "--jq", ".[].name"
    ])
    return [r for r in output.split("\n") if r] if output else []


def get_recent_commits_graphql(repo: str, since: str) -> list[dict]:
    """GraphQL로 커밋 조회 (REST API 404 문제 우회)"""
    query = """
    query($owner: String!, $repo: String!, $since: GitTimestamp!) {
      repository(owner: $owner, name: $repo) {
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 100, since: $since) {
                nodes {
                  oid
                  message
                  committedDate
                  author {
                    user { login }
                    name
                    date
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    output = run_gh([
        "api", "graphql",
        "-f", f"query={query}",
        "-f", f"owner={GITHUB_ORG}",
        "-f", f"repo={repo}",
        "-f", f"since={since}",
    ], timeout=15)

    if not output:
        return []

    try:
        data = json.loads(output)
        branch = data.get("data", {}).get("repository", {}).get("defaultBranchRef")
        if not branch:
            return []
        nodes = branch["target"]["history"]["nodes"]
        # GraphQL 결과를 REST API 호환 포맷으로 변환
        commits = []
        for node in nodes:
            author_login = ""
            if node.get("author", {}).get("user"):
                author_login = node["author"]["user"].get("login", "")
            commits.append({
                "sha": node["oid"],
                "commit": {
                    "message": node["message"],
                    "author": {
                        "name": node["author"].get("name", ""),
                        "date": node["committedDate"],
                    },
                },
                "author": {"login": author_login} if author_login else None,
            })
        return commits
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def is_ai_commit(commit: dict) -> bool:
    message = commit.get("commit", {}).get("message", "")
    return any(marker.lower() in message.lower() for marker in AI_COMMIT_MARKERS)


def collect_github_activity(hours: int = 24) -> dict:
    """최근 N시간의 GitHub 활동을 수집"""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    repos = get_org_repos()

    activity = {
        "period": f"최근 {hours}시간",
        "repos_scanned": len(repos),
        "by_member": {},
        "by_repo": {},
        "ai_commits": [],
        "total_commits": 0,
        "total_ai_commits": 0,
    }

    for member in TEAM_MEMBERS:
        activity["by_member"][member] = {
            "display_name": TEAM_MEMBERS[member],
            "total_commits": 0,
            "ai_commits": 0,
            "repos_active": [],
        }

    for repo in repos:
        commits = get_recent_commits_graphql(repo, since)
        if not commits:
            continue

        repo_stats = {"total": 0, "ai": 0, "contributors": []}

        for commit in commits:
            author_login = (commit.get("author") or {}).get("login", "")
            commit_author = commit.get("commit", {}).get("author", {}).get("name", "")
            is_ai = is_ai_commit(commit)
            message_first_line = commit.get("commit", {}).get("message", "").split("\n")[0]
            commit_date = commit.get("commit", {}).get("author", {}).get("date", "")

            activity["total_commits"] += 1
            repo_stats["total"] += 1

            if is_ai:
                activity["total_ai_commits"] += 1
                repo_stats["ai"] += 1
                activity["ai_commits"].append({
                    "repo": repo,
                    "author": author_login or commit_author,
                    "message": message_first_line[:80],
                    "date": commit_date,
                })

            if author_login in TEAM_MEMBERS:
                member = activity["by_member"][author_login]
                member["total_commits"] += 1
                if is_ai:
                    member["ai_commits"] += 1
                if repo not in member["repos_active"]:
                    member["repos_active"].append(repo)
                if author_login not in repo_stats["contributors"]:
                    repo_stats["contributors"].append(author_login)

        if repo_stats["total"] > 0:
            activity["by_repo"][repo] = repo_stats

    return activity


if __name__ == "__main__":
    data = collect_github_activity(hours=168)
    print(json.dumps(data, indent=2, ensure_ascii=False))
