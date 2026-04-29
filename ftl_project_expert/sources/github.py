"""GitHub issue source using the gh CLI."""

from __future__ import annotations

import json
import subprocess

from .models import Issue, IssueComment, PullRequest


class GitHubSource:
    """Fetch issues from GitHub via the gh CLI."""

    def __init__(self, repo: str):
        """Args:
            repo: owner/repo slug (e.g., "benthomasson/ftl-code-expert")
        """
        self.repo = repo
        self.platform = "github"

    def list_issues(
        self,
        state: str = "open",
        labels: list[str] | None = None,
        limit: int = 100,
        since: str | None = None,
    ) -> list[Issue]:
        """List issues from the repository."""
        cmd = [
            "gh", "issue", "list",
            "--repo", self.repo,
            "--state", state,
            "--json", "number,title,url,body,state,labels,assignees,"
                      "milestone,author,createdAt,updatedAt,closedAt,comments",
            "--limit", str(limit),
        ]
        if labels:
            for label in labels:
                cmd.extend(["--label", label])
        if since:
            cmd.extend(["--search", f"updated:>={since}"])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"gh issue list failed: {result.stderr.strip()}")

        raw_issues = json.loads(result.stdout)
        return [self._normalize(raw) for raw in raw_issues]

    def get_issue(self, number: int) -> Issue:
        """Get a single issue with full details and comments."""
        cmd = [
            "gh", "issue", "view", str(number),
            "--repo", self.repo,
            "--json", "number,title,url,body,state,labels,assignees,"
                      "milestone,author,createdAt,updatedAt,closedAt,comments",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"gh issue view failed: {result.stderr.strip()}")

        raw = json.loads(result.stdout)
        return self._normalize(raw)

    def list_prs(
        self,
        state: str = "open",
        limit: int = 100,
        since: str | None = None,
    ) -> list[PullRequest]:
        """List pull requests from the repository."""
        # Map issue states to PR states
        pr_state = state
        if state == "closed":
            pr_state = "merged"
        cmd = [
            "gh", "pr", "list",
            "--repo", self.repo,
            "--state", pr_state,
            "--json", "number,title,url,body,state,labels,author,"
                      "createdAt,updatedAt,mergedAt,mergedBy,"
                      "files,additions,deletions,changedFiles,"
                      "reviews,comments,closingIssuesReferences",
            "--limit", str(limit),
        ]
        if since:
            cmd.extend(["--search", f"updated:>={since}"])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"gh pr list failed: {result.stderr.strip()}")

        raw_prs = json.loads(result.stdout)
        return [self._normalize_pr(raw) for raw in raw_prs]

    def _normalize_pr(self, raw: dict) -> PullRequest:
        """Convert gh PR JSON to normalized PullRequest."""
        number = raw.get("number", 0)
        labels = [l.get("name", "") for l in raw.get("labels", [])]

        # Extract linked issues
        linked_issues = []
        for ref in raw.get("closingIssuesReferences", []):
            num = ref.get("number")
            if num:
                linked_issues.append(f"GH-{num}")

        # Extract files
        files = [f.get("path", "") for f in raw.get("files", [])]

        # Extract reviews
        reviews = []
        for r in raw.get("reviews", []):
            reviews.append({
                "author": r.get("author", {}).get("login", ""),
                "state": r.get("state", ""),
                "body": r.get("body", ""),
            })

        # Extract comments
        comments = []
        for c in raw.get("comments", []):
            comments.append(IssueComment(
                author=c.get("author", {}).get("login", ""),
                body=c.get("body", ""),
                created=c.get("createdAt", ""),
                url=c.get("url", ""),
            ))

        merged_by = ""
        mb = raw.get("mergedBy")
        if mb and isinstance(mb, dict):
            merged_by = mb.get("login", "")

        return PullRequest(
            id=f"PR-{number}",
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            platform=self.platform,
            body=raw.get("body", ""),
            state=raw.get("state", "").lower(),
            labels=labels,
            author=raw.get("author", {}).get("login", ""),
            created=raw.get("createdAt", ""),
            updated=raw.get("updatedAt", ""),
            merged=raw.get("mergedAt", "") or "",
            merged_by=merged_by,
            linked_issues=linked_issues,
            files=files,
            additions=raw.get("additions", 0),
            deletions=raw.get("deletions", 0),
            changed_files=raw.get("changedFiles", 0),
            reviews=reviews,
            comments=comments,
            comment_count=len(comments),
            raw=raw,
        )

    def _normalize(self, raw: dict) -> Issue:
        """Convert gh JSON to normalized Issue."""
        number = raw.get("number", 0)
        comments = []
        for c in raw.get("comments", []):
            comments.append(IssueComment(
                author=c.get("author", {}).get("login", ""),
                body=c.get("body", ""),
                created=c.get("createdAt", ""),
                url=c.get("url", ""),
            ))

        labels = [l.get("name", "") for l in raw.get("labels", [])]
        assignees = [a.get("login", "") for a in raw.get("assignees", [])]

        milestone = ""
        ms = raw.get("milestone")
        if ms:
            milestone = ms.get("title", "") if isinstance(ms, dict) else str(ms)

        return Issue(
            id=f"GH-{number}",
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            platform=self.platform,
            body=raw.get("body", ""),
            state=raw.get("state", "").lower(),
            labels=labels,
            assignees=assignees,
            milestone=milestone,
            author=raw.get("author", {}).get("login", ""),
            created=raw.get("createdAt", ""),
            updated=raw.get("updatedAt", ""),
            closed=raw.get("closedAt", "") or "",
            comments=comments,
            comment_count=len(comments),
            raw=raw,
        )
