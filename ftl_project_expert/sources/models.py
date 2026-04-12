"""Normalized issue model shared across all source adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class IssueComment:
    """A comment on an issue."""
    author: str
    body: str
    created: str
    url: str = ""


@dataclass
class PullRequest:
    """Normalized pull request / merge request from any platform."""
    # Identity
    id: str              # e.g., "PR-10", "MR-42"
    title: str
    url: str
    platform: str        # "github", "gitlab"

    # Content
    body: str = ""
    state: str = ""      # "open", "merged", "closed"
    labels: list[str] = field(default_factory=list)
    author: str = ""
    created: str = ""
    updated: str = ""
    merged: str = ""
    merged_by: str = ""

    # Relationships
    linked_issues: list[str] = field(default_factory=list)  # issue IDs this PR closes/fixes

    # Files
    files: list[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0

    # Review
    reviews: list[dict] = field(default_factory=list)  # [{author, state, body}]
    comment_count: int = 0
    comments: list[IssueComment] = field(default_factory=list)

    # Raw data
    raw: dict = field(default_factory=dict)

    def to_prompt_text(self) -> str:
        """Format PR for inclusion in an LLM prompt."""
        lines = [
            f"## {self.id}: {self.title}",
            f"- URL: {self.url}",
            f"- State: {self.state}",
        ]
        if self.author:
            lines.append(f"- Author: {self.author}")
        if self.labels:
            lines.append(f"- Labels: {', '.join(self.labels)}")
        if self.linked_issues:
            lines.append(f"- Linked issues: {', '.join(self.linked_issues)}")
        lines.append(f"- Created: {self.created}")
        if self.merged:
            lines.append(f"- Merged: {self.merged}")
            if self.merged_by:
                lines.append(f"- Merged by: {self.merged_by}")
        lines.append(f"- Changed files: {self.changed_files} (+{self.additions}/-{self.deletions})")
        if self.files:
            test_files = [f for f in self.files if "test" in f.lower()]
            src_files = [f for f in self.files if "test" not in f.lower()]
            if src_files:
                lines.append(f"- Source files: {', '.join(src_files)}")
            if test_files:
                lines.append(f"- Test files: {', '.join(test_files)}")
        if self.reviews:
            lines.append(f"\n### Reviews ({len(self.reviews)})\n")
            for r in self.reviews[:10]:
                lines.append(f"**{r.get('author', '?')}** [{r.get('state', '?')}]: {r.get('body', '')[:200]}")
            if len(self.reviews) > 10:
                lines.append(f"... and {len(self.reviews) - 10} more reviews")
        if self.body:
            lines.append(f"\n### Description\n\n{self.body}")
        if self.comments:
            lines.append(f"\n### Comments ({len(self.comments)})\n")
            for c in self.comments[:10]:
                lines.append(f"**{c.author}** ({c.created}):\n{c.body}\n")
            if len(self.comments) > 10:
                lines.append(f"... and {len(self.comments) - 10} more comments")
        return "\n".join(lines)


@dataclass
class Issue:
    """Normalized issue from any platform."""
    # Identity
    id: str              # e.g., "GH-123", "GL-456", "PROJ-789"
    title: str
    url: str
    platform: str        # "github", "gitlab", "jira"

    # Content
    body: str = ""
    state: str = ""      # "open", "closed", "in_progress", etc.
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    milestone: str = ""
    priority: str = ""   # "critical", "high", "medium", "low", ""
    issue_type: str = "" # "bug", "feature", "epic", "story", "task", ""

    # Relationships
    parent: str = ""     # parent epic/issue ID
    children: list[str] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)  # related issues

    # Metadata
    author: str = ""
    created: str = ""
    updated: str = ""
    closed: str = ""
    comments: list[IssueComment] = field(default_factory=list)
    comment_count: int = 0

    # Raw data for platform-specific fields
    raw: dict = field(default_factory=dict)

    def summary(self) -> str:
        """One-line summary for topic queues."""
        parts = [f"[{self.state}]" if self.state else ""]
        if self.issue_type:
            parts.append(f"({self.issue_type})")
        parts.append(self.title)
        if self.assignees:
            parts.append(f"→ {', '.join(self.assignees)}")
        return " ".join(p for p in parts if p)

    def to_prompt_text(self) -> str:
        """Format issue for inclusion in an LLM prompt."""
        lines = [
            f"## {self.id}: {self.title}",
            f"- URL: {self.url}",
            f"- State: {self.state}",
        ]
        if self.issue_type:
            lines.append(f"- Type: {self.issue_type}")
        if self.priority:
            lines.append(f"- Priority: {self.priority}")
        if self.labels:
            lines.append(f"- Labels: {', '.join(self.labels)}")
        if self.assignees:
            lines.append(f"- Assignees: {', '.join(self.assignees)}")
        if self.milestone:
            lines.append(f"- Milestone: {self.milestone}")
        if self.parent:
            lines.append(f"- Parent: {self.parent}")
        if self.children:
            lines.append(f"- Children: {', '.join(self.children)}")
        if self.linked:
            lines.append(f"- Linked: {', '.join(self.linked)}")
        lines.append(f"- Created: {self.created}")
        if self.updated:
            lines.append(f"- Updated: {self.updated}")
        if self.author:
            lines.append(f"- Author: {self.author}")
        if self.body:
            lines.append(f"\n### Description\n\n{self.body}")
        if self.comments:
            lines.append(f"\n### Comments ({len(self.comments)})\n")
            for c in self.comments[:10]:
                lines.append(f"**{c.author}** ({c.created}):\n{c.body}\n")
            if len(self.comments) > 10:
                lines.append(f"... and {len(self.comments) - 10} more comments")
        return "\n".join(lines)
