"""GitLab issue source using the glab CLI."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime

from .models import Issue, IssueComment, PullRequest


def _filter_since(items, since: str):
    """Filter items by updated >= since date (YYYY-MM-DD)."""
    cutoff = datetime.fromisoformat(since)
    filtered = []
    for item in items:
        updated = item.updated or item.created
        if not updated:
            filtered.append(item)
            continue
        try:
            item_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if item_dt.replace(tzinfo=None) >= cutoff:
                filtered.append(item)
        except (ValueError, TypeError):
            filtered.append(item)
    return filtered


class GitLabSource:
    """Fetch issues from GitLab via the glab CLI."""

    def __init__(self, repo: str):
        """Args:
            repo: group/project slug (e.g., "mygroup/myproject")
        """
        self.repo = repo
        self.platform = "gitlab"

    def list_issues(
        self,
        state: str = "opened",
        labels: list[str] | None = None,
        limit: int = 100,
        page: int = 1,
        since: str | None = None,
    ) -> list[Issue]:
        """List issues from the project."""
        cmd = [
            "glab", "issue", "list",
            "--repo", self.repo,
            "--per-page", str(limit),
            "--page", str(page),
            "--output", "json",
            "--order", "updated_at",
            "--sort", "desc",
        ]
        if state:
            if state == "closed":
                cmd.append("--closed")
            elif state == "all":
                cmd.append("--all")
        if labels:
            cmd.extend(["--label", ",".join(labels)])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"glab issue list failed: {result.stderr.strip()}")

        raw_issues = json.loads(result.stdout)
        issues = [self._normalize(raw) for raw in raw_issues]

        if since:
            issues = _filter_since(issues, since)

        return issues

    def get_issue(self, iid: int) -> Issue:
        """Get a single issue with comments."""
        cmd = [
            "glab", "issue", "view", str(iid),
            "--repo", self.repo,
            "--output", "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"glab issue view failed: {result.stderr.strip()}")

        raw = json.loads(result.stdout)
        issue = self._normalize(raw)

        # Fetch comments separately
        comments_cmd = [
            "glab", "issue", "note", "list", str(iid),
            "--repo", self.repo,
            "--output", "json",
        ]
        comments_result = subprocess.run(comments_cmd, capture_output=True, text=True)
        if comments_result.returncode == 0 and comments_result.stdout.strip():
            try:
                raw_comments = json.loads(comments_result.stdout)
                for c in raw_comments:
                    issue.comments.append(IssueComment(
                        author=c.get("author", {}).get("username", ""),
                        body=c.get("body", ""),
                        created=c.get("created_at", ""),
                    ))
                issue.comment_count = len(issue.comments)
            except (json.JSONDecodeError, TypeError):
                pass

        return issue

    def list_prs(
        self,
        state: str = "open",
        limit: int = 100,
        since: str | None = None,
    ) -> list[PullRequest]:
        """List merge requests from the project."""
        cmd = [
            "glab", "mr", "list",
            "--repo", self.repo,
            "--per-page", str(limit),
            "--output", "json",
        ]
        if state == "merged":
            cmd.append("--merged")
        elif state == "closed":
            cmd.append("--closed")
        elif state == "all":
            cmd.append("--all")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"glab mr list failed: {result.stderr.strip()}")

        raw_mrs = json.loads(result.stdout)
        prs = [self._normalize_pr(raw) for raw in raw_mrs]

        if since:
            prs = _filter_since(prs, since)

        return prs

    def _normalize_pr(self, raw: dict) -> PullRequest:
        """Convert glab MR JSON to normalized PullRequest."""
        iid = raw.get("iid", raw.get("id", 0))
        labels = raw.get("labels", [])
        if isinstance(labels, str):
            labels = [l.strip() for l in labels.split(",") if l.strip()]

        author = ""
        auth = raw.get("author")
        if auth and isinstance(auth, dict):
            author = auth.get("username", "")

        merged_by = ""
        mb = raw.get("merged_by") or raw.get("merge_user")
        if mb and isinstance(mb, dict):
            merged_by = mb.get("username", "")

        # Extract reviewers as review entries
        reviews = []
        for r in raw.get("reviewers", []):
            if isinstance(r, dict):
                reviews.append({
                    "author": r.get("username", ""),
                    "state": "reviewer",
                    "body": "",
                })

        # Extract linked issues from source branch name (convention: issue-NNN)
        linked_issues = []
        source_branch = raw.get("source_branch", "")
        import re
        issue_refs = re.findall(r"(?:issue[s]?[-_]?)(\d+)", source_branch, re.IGNORECASE)
        for ref in issue_refs:
            linked_issues.append(f"GL-{ref}")

        state = raw.get("state", "").lower()
        if raw.get("merged_at"):
            state = "merged"

        return PullRequest(
            id=f"MR-{iid}",
            title=raw.get("title", ""),
            url=raw.get("web_url", ""),
            platform=self.platform,
            body=raw.get("description", ""),
            state=state,
            labels=labels,
            author=author,
            created=raw.get("created_at", ""),
            updated=raw.get("updated_at", ""),
            merged=raw.get("merged_at", "") or "",
            merged_by=merged_by,
            linked_issues=linked_issues,
            files=[],  # glab list doesn't include files
            additions=0,
            deletions=0,
            changed_files=0,
            reviews=reviews,
            comment_count=raw.get("user_notes_count", 0),
            raw=raw,
        )

    def _normalize(self, raw: dict) -> Issue:
        """Convert glab JSON to normalized Issue."""
        iid = raw.get("iid", raw.get("id", 0))
        labels = raw.get("labels", [])
        if isinstance(labels, str):
            labels = [l.strip() for l in labels.split(",") if l.strip()]

        assignees = []
        for a in raw.get("assignees", []):
            if isinstance(a, dict):
                assignees.append(a.get("username", ""))
            else:
                assignees.append(str(a))

        milestone = ""
        ms = raw.get("milestone")
        if ms and isinstance(ms, dict):
            milestone = ms.get("title", "")

        author = ""
        auth = raw.get("author")
        if auth and isinstance(auth, dict):
            author = auth.get("username", "")

        return Issue(
            id=f"GL-{iid}",
            title=raw.get("title", ""),
            url=raw.get("web_url", ""),
            platform=self.platform,
            body=raw.get("description", ""),
            state=raw.get("state", "").lower(),
            labels=labels,
            assignees=assignees,
            milestone=milestone,
            priority=raw.get("priority", "") or "",
            issue_type=raw.get("issue_type", "") or "",
            author=author,
            created=raw.get("created_at", ""),
            updated=raw.get("updated_at", ""),
            closed=raw.get("closed_at", "") or "",
            comment_count=raw.get("user_notes_count", 0),
            raw=raw,
        )
