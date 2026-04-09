"""Scan prompt — overview of project issues."""

from .common import BELIEFS_INSTRUCTIONS, TOPICS_INSTRUCTIONS


def build_scan_prompt(
    issues_text: str,
    project_name: str,
    platform: str,
    issue_count: int,
) -> str:
    """Build a prompt for scanning project issues."""
    return f"""You are a senior project manager analyzing a project's issue tracker.

## Project: {project_name}
## Platform: {platform}
## Total issues scanned: {issue_count}

## Issues

{issues_text}

## Instructions

Analyze these issues and provide:

1. **Project Overview** — What is this project about, based on the issues?
2. **Current State** — What's actively being worked on? What's blocked?
3. **Risk Areas** — Where are the bottlenecks, stale issues, or under-resourced areas?
4. **Milestone/Release Status** — Are any milestones at risk?
5. **Team Distribution** — Who's overloaded? Who has capacity?
6. **Patterns** — Common themes across issues (recurring bugs, feature areas, tech debt)

Be specific — reference issue IDs, assignees, and labels.

{TOPICS_INSTRUCTIONS}

{BELIEFS_INSTRUCTIONS}
"""
